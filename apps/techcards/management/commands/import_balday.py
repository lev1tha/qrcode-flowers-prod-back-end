"""
python manage.py import_balday [--shop Balday] [--year 2026]

Импорт исторических данных из Excel-модели «Финансовый учет
кондитерского цеха Бал-Дай» (выгрузка в fixtures/balday_2026.json).

Что переносится:
  • справочник видов операций (21) — ядро классификации ОПиУ/ОДДС;
  • номенклатура (82) → FinalProduct с ценой и ручной себестоимостью;
  • продажи (750 строк) → накладные, сгруппированные по дате и каналу;
  • операции (63) → журнал операций, включая историческую выручку
    за январь–апрель (тогда продажи вели одной суммой);
  • настройки: ставка налога, постоянные расходы.

Идемпотентна: повторный запуск обновляет справочники и НЕ дублирует
документы — импортированные накладные и операции удаляются и создаются
заново. Документы, введённые в системе руками, не трогаются
(у накладных проверяется is_imported).
"""
import json
from collections import defaultdict
from datetime import date
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import Shop
from apps.techcards.models import (
    Department, FinalProduct, FinanceSettings, FixedCost, Invoice, InvoiceLine,
    Operation, OperationType,
)

FIXTURE = Path(__file__).resolve().parents[2] / 'fixtures' / 'balday_2026.json'

# Канал продаж из Excel → подразделение-отправитель в накладной.
CHANNEL_TO_DEPT = {
    'Точка продаж': Department.OUTLET,
    'Цех Бал-Дай':  Department.WORKSHOP,
}

FLOW_MAP = {'Поступление': OperationType.FLOW_IN, 'Расход': OperationType.FLOW_OUT}

# Этими видами в Excel заведена выручка и себестоимость за январь–апрель,
# когда продажи вели одной суммой без разбивки по позициям. Импортировать
# их ОБЯЗАТЕЛЬНО — иначе потеряется 3.2 млн выручки. Но для ручного ввода
# они закрыты (is_legacy): сегодня выручку даёт накладная, и повторная
# строка в журнале создала бы двойной учёт.
LEGACY_OPERATION_TYPES = {
    'Поступление от продаж',
    'Себестоимость проданной продукции',
}


class Command(BaseCommand):
    help = 'Импортирует историю Бал-Дай из Excel-выгрузки в систему'

    def add_arguments(self, parser):
        parser.add_argument('--shop', default='Balday')
        parser.add_argument('--year', type=int, default=2026)

    @transaction.atomic
    def handle(self, *args, **opts):
        if not FIXTURE.exists():
            raise CommandError(f'Нет файла выгрузки: {FIXTURE}')
        data = json.loads(FIXTURE.read_text(encoding='utf-8'))

        try:
            shop = Shop.objects.get(name=opts['shop'])
        except Shop.DoesNotExist:
            raise CommandError(
                f'Магазин «{opts["shop"]}» не найден. '
                f'Сначала: python manage.py create_tech_admin')

        w = self.stdout.write
        w(f'Импорт в магазин «{shop.name}»…')

        types    = self._types(shop, data['operation_types'])
        products = self._nomenclature(shop, data['nomenclature'])
        self._settings(shop, data['settings'])
        invoices = self._sales(shop, data['sales'], products)
        ops      = self._operations(shop, data['operations'], types)

        w(self.style.SUCCESS(
            f'\nГотово: {len(types)} видов операций, {len(products)} позиций, '
            f'{invoices} накладных, {ops} операций.'))

    # ── Справочник ────────────────────────────────────────────

    def _types(self, shop, rows):
        result = {}
        for i, r in enumerate(rows):
            obj, _ = OperationType.objects.update_or_create(
                shop=shop, name=r['name'],
                defaults={
                    'flow': FLOW_MAP.get(r['flow'], OperationType.FLOW_OUT),
                    'pnl_article': r['pnl_article'],
                    'cf_article':  r['cf_article'],
                    'cf_section':  r['cf_section'],
                    'sort_order':  i,
                    'is_legacy':   r['name'] in LEGACY_OPERATION_TYPES,
                },
            )
            result[r['name']] = obj
        self.stdout.write(f'  справочник операций: {len(result)}')
        return result

    # ── Номенклатура ──────────────────────────────────────────

    def _nomenclature(self, shop, rows):
        result = {}
        for r in rows:
            if not r['name']:
                continue
            # Наценка из цены и себестоимости; без себестоимости оставляем 50 %.
            cost, price = r['unit_cost'], r['price']
            markup = round((price / cost - 1) * 100, 2) if cost > 0 and price > 0 else 50.0
            obj, _ = FinalProduct.objects.update_or_create(
                shop=shop, name=r['name'],
                defaults={
                    'category': r['category'],
                    'retail_price': price or None,
                    'manual_unit_cost': cost or None,
                    'markup_percent': markup,
                },
            )
            result[r['name']] = obj
        self.stdout.write(f'  номенклатура: {len(result)}')
        return result

    # ── Настройки ─────────────────────────────────────────────

    def _settings(self, shop, s):
        FinanceSettings.objects.update_or_create(
            shop=shop,
            defaults={'tax_rate': s['tax_rate'],
                      'opening_cash': s['opening_cash'],
                      'target_profit': s['target_profit']},
        )
        shop.fixed_costs.all().delete()
        FixedCost.objects.bulk_create([
            FixedCost(shop=shop, name=f['name'], amount=f['amount'])
            for f in s['fixed_costs']
        ])
        self.stdout.write(f'  постоянные расходы: {len(s["fixed_costs"])}')

    # ── Продажи → накладные ───────────────────────────────────

    def _sales(self, shop, rows, products):
        """
        750 строк продаж — это не 750 документов, а дневная выручка.
        Группируем по (дата, канал): один документ на день и точку,
        как и работает цех в реальности.
        """
        Invoice.objects.filter(shop=shop, is_imported=True).delete()

        groups = defaultdict(list)
        for r in rows:
            if not r['date'] or not r['product'] or r['qty'] <= 0:
                continue
            groups[(r['date'], r['channel'])].append(r)

        created = 0
        for seq, ((iso, channel), items) in enumerate(sorted(groups.items()), start=1):
            d = date.fromisoformat(iso)
            invoice = Invoice.objects.create(
                shop=shop,
                number=f'ИМП-{d.year}-{seq:04d}',
                date=d,
                from_department=CHANNEL_TO_DEPT.get(channel, Department.OUTLET),
                to_client=channel or 'Розница',
                is_imported=True,
            )
            lines = []
            for r in items:
                product = products.get(r['product'])
                if product is None:
                    # Позиция продавалась, но в номенклатуре её нет —
                    # заводим, иначе потеряли бы выручку.
                    product = FinalProduct.objects.create(
                        shop=shop, name=r['product'], category=r['direction'],
                        retail_price=r['price'] or None,
                        manual_unit_cost=r['unit_cost'] or None)
                    products[r['product']] = product
                lines.append(InvoiceLine(
                    invoice=invoice, product=product, quantity=r['qty'],
                    unit_cost=r['unit_cost'], sell_price=r['price']))
            InvoiceLine.objects.bulk_create(lines)
            created += 1

        self.stdout.write(f'  продажи: {len(rows)} строк → {created} накладных')
        return created

    # ── Операции ──────────────────────────────────────────────

    def _operations(self, shop, rows, types):
        Operation.objects.filter(shop=shop).delete()

        created, skipped = [], 0
        for r in rows:
            t = types.get(r['op_type'])
            if t is None:
                skipped += 1
                continue
            created.append(Operation(
                shop=shop, date=date.fromisoformat(r['date']), op_type=t,
                counterparty=r['counterparty'][:200],
                description=r['description'][:300],
                accrual=r['accrual'], cash=r['cash'], method=r['method'][:50]))
        Operation.objects.bulk_create(created)

        legacy = sum(1 for o in created if o.op_type.is_legacy)
        self.stdout.write(
            f'  операции: {len(created)} импортировано '
            f'({legacy} — историческая выручка/себестоимость за янв–апр), '
            f'{skipped} пропущено')
        return len(created)
