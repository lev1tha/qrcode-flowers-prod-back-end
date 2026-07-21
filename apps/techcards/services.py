"""
Операции склада цеха: приход сырья, расчёт остатков, запуск производства.

Всё, что меняет остатки, проходит только здесь и только внутри транзакции —
чтобы не появилось второго места, где склад можно поправить в обход истории.
"""
from django.db import transaction
from django.db.models import Sum
from rest_framework.exceptions import ValidationError

from . import costing
from .models import (
    Disposal, FinalProduct, Invoice, InvoiceLine, ProductionRun,
    RawIngredient, StockMovement,
)


# ── Остатки ───────────────────────────────────────────────────

def raw_balances(shop):
    """{raw_id: остаток в базовых единицах}. Позиции без движений опускаются."""
    rows = (StockMovement.objects
            .filter(shop=shop, raw__isnull=False)
            .values('raw_id')
            .annotate(total=Sum('quantity')))
    return {r['raw_id']: r['total'] or 0.0 for r in rows}


def product_balances(shop):
    """{product_id: остаток готовой продукции, шт}."""
    rows = (StockMovement.objects
            .filter(shop=shop, product__isnull=False)
            .values('product_id')
            .annotate(total=Sum('quantity')))
    return {r['product_id']: r['total'] or 0.0 for r in rows}


def stock_snapshot(shop):
    """
    Полный срез склада для вкладки «Производство»: остатки сырья,
    остатки продукции и суточный потенциал выпуска по каждому десерту.
    """
    raw_bal = raw_balances(shop)
    prod_bal = product_balances(shop)

    # Удалённые позиции в срез не попадают, но их движения остаются
    # в реестре: баланс истории от этого не меняется.
    raws = list(RawIngredient.objects.filter(shop=shop).live())
    products = list(
        FinalProduct.objects.filter(shop=shop).live()
        .prefetch_related('components__semi__ingredients__ingredient', 'components__raw')
    )

    raw_rows = [{
        'id':       r.id,
        'name':     r.name,
        'unit':     r.unit,
        'baseUnit': costing.BASE_UNITS.get(r.unit, r.unit),
        'balance':  raw_bal.get(r.id, 0.0),
        'unitCost': costing.raw_unit_cost(r),
    } for r in raws]

    product_rows = []
    for p in products:
        cost = costing.effective_unit_cost(p)
        bottleneck_id, _ = costing.bottleneck(p, raw_bal)
        product_rows.append({
            'id':           p.id,
            'name':         p.name,
            'balance':      prod_bal.get(p.id, 0.0),
            'unitCost':     cost,
            'canProduce':   costing.max_producible(p, raw_bal),
            'bottleneckId': bottleneck_id,
        })

    return {'raw': raw_rows, 'products': product_rows}


# ── Приход сырья ──────────────────────────────────────────────

@transaction.atomic
def receive_raw(shop, raw, quantity, unit=None, note=''):
    """
    Приход сырья на склад. quantity задаётся в unit (по умолчанию —
    закупочная единица позиции) и переводится в базовые единицы,
    потому что рецептуры считаются только в них.
    """
    if quantity is None or quantity <= 0:
        raise ValidationError({'quantity': 'Количество должно быть больше нуля'})

    unit = unit or raw.unit
    if unit not in costing.UNIT_FACTORS:
        raise ValidationError({'unit': f'Неизвестная единица «{unit}»'})

    base_qty = costing.to_base_units(quantity, unit)
    return StockMovement.objects.create(
        shop=shop,
        kind=StockMovement.KIND_RECEIPT,
        raw=raw,
        quantity=base_qty,
        unit_cost=costing.raw_unit_cost(raw),
        note=note,
    )


# ── Производство ──────────────────────────────────────────────

@transaction.atomic
def run_production(shop, product, quantity):
    """
    Проведение документа «Выпуск продукции».

    Цех вводит только товар и количество. Дальше всё считает бэкенд:
      1. создаётся ProductionRun;
      2. готовая продукция приходуется на склад (+quantity);
      3. по техкарте считается потребность в сырье (расход × quantity);
      4. сырьё списывается со склада;
      5. себестоимость партии = сумма стоимости списанного сырья.

    Нехватка сырья НЕ блокирует проведение — как «списание при отсутствии
    остатков» в 1С. Цех не должен стоять из-за непроведённого прихода,
    а расхождение закрывается инвентаризацией. Позиции, ушедшие в минус,
    возвращаются отдельно, чтобы показать их ПОСЛЕ проведения.

    Блокируем строку магазина: два одновременных выпуска иначе
    прочитали бы один и тот же остаток.
    """
    if quantity is None or quantity <= 0:
        raise ValidationError({'quantity': 'Количество должно быть больше нуля'})

    # Сериализуем все складские операции магазина между собой.
    type(shop).objects.select_for_update().get(pk=shop.pk)

    usage = costing.raw_usage_per_product(product)
    if not usage:
        raise ValidationError(
            {'product': f'У десерта «{product.name}» пустой состав — производить нечего'}
        )

    balances = raw_balances(shop)
    raws = {r.id: r for r in RawIngredient.objects.filter(id__in=usage.keys())}

    movements, negatives, cost_total = [], [], 0.0
    for raw_id, per_unit in usage.items():
        raw = raws.get(raw_id)
        required  = per_unit * quantity
        unit_cost = costing.raw_unit_cost(raw) if raw else 0.0
        cost_total += required * unit_cost

        rest = balances.get(raw_id, 0.0) - required
        if rest < -1e-9 and raw:
            negatives.append({
                'rawId':    raw_id,
                'name':     raw.name,
                'unit':     costing.BASE_UNITS.get(raw.unit, ''),
                'required': round(required, 2),
                'was':      round(balances.get(raw_id, 0.0), 2),
                'rest':     round(rest, 2),
            })

        movements.append(StockMovement(
            shop=shop,
            kind=StockMovement.KIND_PRODUCTION_OUT,
            raw_id=raw_id,
            quantity=-required,
            unit_cost=unit_cost,
            run=None,           # проставим после создания документа
        ))

    # Себестоимость единицы — из фактически списанного сырья на партию.
    unit_cost = cost_total / quantity if quantity else 0.0
    run = ProductionRun.objects.create(
        shop=shop, product=product, quantity=quantity, unit_cost=unit_cost,
    )
    for m in movements:
        m.run = run

    movements.append(StockMovement(
        shop=shop,
        kind=StockMovement.KIND_PRODUCTION_IN,
        product=product,
        quantity=quantity,
        unit_cost=unit_cost,
        run=run,
    ))
    StockMovement.objects.bulk_create(movements)
    return run, negatives


# ── Себестоимость отгрузки ────────────────────────────────────

def frozen_unit_cost(product):
    """
    Себестоимость 1 шт для документа отгрузки/списания.

    Берём себестоимость ПОСЛЕДНЕГО выпуска: именно по ней продукция
    легла на склад, и она уже заморожена в ProductionRun. Если выпусков
    не было (продукцию заводят задним числом) — считаем по текущей техкарте.
    """
    last_run = product.production_runs.order_by('-created_at', '-id').first()
    if last_run:
        return last_run.unit_cost
    return costing.effective_unit_cost(product)


# ── Накладные ─────────────────────────────────────────────────

def _next_invoice_number(shop, date):
    """Сквозная нумерация в пределах года: 2026-0001."""
    year = date.year
    prefix = f'{year}-'
    last = (Invoice.objects
            .filter(shop=shop, number__startswith=prefix)
            .order_by('-number')
            .values_list('number', flat=True)
            .first())
    seq = int(last.split('-')[1]) + 1 if last else 1
    return f'{prefix}{seq:04d}'


@transaction.atomic
def post_invoice(shop, date, from_department, to_client, lines):
    """
    Провести накладную: заморозить строки и списать продукцию со склада.

    lines — [{'product_id': int, 'quantity': float, 'sell_price': float}].
    Себестоимость клиент не передаёт: её определяет сервер, иначе маржу
    в документе можно было бы нарисовать любую.
    """
    if not lines:
        raise ValidationError({'lines': 'Накладная без позиций'})

    # Сериализуем складские операции магазина (см. run_production).
    type(shop).objects.select_for_update().get(pk=shop.pk)

    products = {
        p.id: p for p in FinalProduct.objects.filter(
            shop=shop, id__in=[l['product_id'] for l in lines])
    }
    balances = product_balances(shop)

    # Одна позиция может встретиться в нескольких строках — проверяем сумму,
    # иначе двумя строками по половине остатка можно увести склад в минус.
    wanted = {}
    for line in lines:
        pid = line['product_id']
        if pid not in products:
            raise ValidationError({'lines': f'Десерт id={pid} не найден в этом магазине'})
        qty = line['quantity']
        if qty is None or qty <= 0:
            raise ValidationError({'lines': 'Количество должно быть больше нуля'})
        wanted[pid] = wanted.get(pid, 0.0) + qty

    shortages = [
        f'{products[pid].name}: нужно {qty:.2f} шт, есть {balances.get(pid, 0.0):.2f} шт'
        for pid, qty in wanted.items()
        if balances.get(pid, 0.0) + 1e-9 < qty
    ]
    if shortages:
        raise ValidationError({'detail': 'Не хватает продукции — ' + '; '.join(shortages)})

    invoice = Invoice.objects.create(
        shop=shop,
        number=_next_invoice_number(shop, date),
        date=date,
        from_department=from_department,
        to_client=to_client,
    )

    movements = []
    for line in lines:
        product = products[line['product_id']]
        unit_cost = frozen_unit_cost(product)
        InvoiceLine.objects.create(
            invoice=invoice,
            product=product,
            quantity=line['quantity'],
            unit_cost=unit_cost,
            sell_price=line['sell_price'],
        )
        movements.append(StockMovement(
            shop=shop,
            kind=StockMovement.KIND_SALE,
            product=product,
            quantity=-line['quantity'],
            unit_cost=unit_cost,
            invoice=invoice,
        ))
    StockMovement.objects.bulk_create(movements)
    return invoice


# ── Списание ──────────────────────────────────────────────────

@transaction.atomic
def dispose(shop, reason, quantity, raw=None, product=None):
    """
    Списать брак/просрочку со склада. Ровно одно из raw/product.
    Сырьё списывается в базовых единицах, продукция — в штуках.
    """
    if (raw is None) == (product is None):
        raise ValidationError({'detail': 'Укажите либо сырьё, либо готовый десерт'})
    if quantity is None or quantity <= 0:
        raise ValidationError({'quantity': 'Количество должно быть больше нуля'})

    type(shop).objects.select_for_update().get(pk=shop.pk)

    if raw is not None:
        available = raw_balances(shop).get(raw.id, 0.0)
        unit_cost = costing.raw_unit_cost(raw)
        label, unit = raw.name, costing.BASE_UNITS.get(raw.unit, '')
    else:
        available = product_balances(shop).get(product.id, 0.0)
        unit_cost = frozen_unit_cost(product)
        label, unit = product.name, 'шт'

    if available + 1e-9 < quantity:
        raise ValidationError({'detail':
            f'Не хватает: {label} — списываем {quantity:.2f} {unit}, '
            f'есть {available:.2f} {unit}'})

    disposal = Disposal.objects.create(
        shop=shop, raw=raw, product=product,
        quantity=quantity, unit_cost=unit_cost, reason=reason,
    )
    StockMovement.objects.create(
        shop=shop,
        kind=StockMovement.KIND_DISPOSAL,
        raw=raw, product=product,
        quantity=-quantity,
        unit_cost=unit_cost,
        disposal=disposal,
    )
    return disposal


def disposal_total(shop, date_from=None, date_to=None):
    """Сумма убытка от списаний за период — для финансовой аналитики."""
    qs = Disposal.objects.filter(shop=shop)
    if date_from:
        qs = qs.filter(created_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(created_at__date__lte=date_to)
    return sum(d.loss_amount for d in qs)
