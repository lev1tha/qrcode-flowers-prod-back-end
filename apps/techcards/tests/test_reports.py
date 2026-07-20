"""ОПиУ, ОДДС и журнал операций."""
from datetime import date

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import User
from apps.techcards import reports, services
from apps.techcards.models import (
    FinalProduct, FinanceSettings, Invoice, InvoiceLine, Operation, OperationType,
)

pytestmark = pytest.mark.django_db

PNL   = '/api/tech-cards/reports/pnl/'
CF    = '/api/tech-cards/reports/cashflow/'
DASH  = '/api/tech-cards/reports/dashboard/'
OPS   = '/api/tech-cards/operations/'


@pytest.fixture
def tech_admin(active_shop):
    return User.objects.create_user(
        username='fintech', password='pass12345',
        shop=active_shop, role=User.ROLE_TECH_ADMIN)


@pytest.fixture
def tech_api(tech_admin):
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(tech_admin).access_token}')
    return c


@pytest.fixture
def settings_obj(active_shop):
    return FinanceSettings.objects.create(
        shop=active_shop, tax_rate=0.04, opening_cash=0, target_profit=500000)


@pytest.fixture
def rent_type(active_shop):
    return OperationType.objects.create(
        shop=active_shop, name='Аренда', flow=OperationType.FLOW_OUT,
        pnl_article='Аренда', cf_article='Аренда оплачено',
        cf_section='Операционная деятельность')


@pytest.fixture
def purchase_type(active_shop):
    """Закуп сырья: в ОДДС попадает, в ОПиУ — нет (иначе двойной учёт)."""
    return OperationType.objects.create(
        shop=active_shop, name='Закуп сырья/материалов', flow=OperationType.FLOW_OUT,
        pnl_article=OperationType.NO_PNL, cf_article='Закупки/сырье оплачено',
        cf_section='Операционная деятельность')


@pytest.fixture
def sale(active_shop):
    """Накладная на 1000 сом выручки при себестоимости 400."""
    product = FinalProduct.objects.create(
        shop=active_shop, name='Торт', manual_unit_cost=400, retail_price=1000)
    inv = Invoice.objects.create(
        shop=active_shop, number='2026-0001', date=date(2026, 3, 10),
        from_department='outlet', to_client='Глобус')
    InvoiceLine.objects.create(
        invoice=inv, product=product, quantity=1, unit_cost=400, sell_price=1000)
    return inv


# ── ОПиУ ──────────────────────────────────────────────────

def test_pnl_takes_revenue_from_invoices(active_shop, sale, settings_obj):
    p = reports.pnl(active_shop, 2026)
    march = 2  # индекс марта
    assert p['incomeTotal']['values'][march] == pytest.approx(1000)
    assert p['cogsTotal']['values'][march]   == pytest.approx(400)
    assert p['grossProfit']['values'][march] == pytest.approx(600)


def test_pnl_applies_tax_only_to_profit(active_shop, sale, settings_obj):
    """С убытка налог не начисляется — иначе убыток вырос бы на ровном месте."""
    p = reports.pnl(active_shop, 2026)
    march = 2
    assert p['ebt']['values'][march] == pytest.approx(600)
    assert p['tax']['values'][march] == pytest.approx(24)     # 600 × 4 %
    assert p['netProfit']['values'][march] == pytest.approx(576)
    # апрель пустой → налога нет
    assert p['tax']['values'][3] == 0


def test_pnl_loss_month_has_no_tax(active_shop, rent_type, settings_obj):
    Operation.objects.create(shop=active_shop, date=date(2026, 4, 5),
                             op_type=rent_type, accrual=115000, cash=115000)
    p = reports.pnl(active_shop, 2026)
    april = 3
    assert p['ebt']['values'][april] == pytest.approx(-115000)
    assert p['tax']['values'][april] == 0
    assert p['netProfit']['values'][april] == pytest.approx(-115000)


def test_purchase_does_not_hit_pnl(active_shop, purchase_type, settings_obj):
    """
    Закуп сырья не должен попадать в ОПиУ: себестоимость уже учтена
    в накладной. Это главный защитный механизм от двойного счёта.
    """
    Operation.objects.create(shop=active_shop, date=date(2026, 5, 5),
                             op_type=purchase_type, accrual=50000, cash=50000)
    p = reports.pnl(active_shop, 2026)
    c = reports.cash_flow(active_shop, 2026)
    may = 4
    assert p['opexTotal']['values'][may] == 0            # в ОПиУ не видно
    assert c['outflowTotal']['values'][may] == pytest.approx(50000)  # в ОДДС видно


def test_disposal_lands_in_pnl(active_shop, settings_obj):
    """Списание брака идёт в ОПиУ отдельной статьёй."""
    product = FinalProduct.objects.create(
        shop=active_shop, name='Кекс', manual_unit_cost=100)
    services.receive_raw  # noqa: B018 — просто фиксируем импорт
    from apps.techcards.models import Disposal
    Disposal.objects.create(shop=active_shop, product=product, quantity=3,
                            unit_cost=100, reason=Disposal.REASON_DEFECT)
    p = reports.pnl(active_shop, 2026)
    row = next(r for r in p['opex'] if r['article'] == 'Брак/списание')
    assert row['total'] == pytest.approx(300)


# ── ОДДС ──────────────────────────────────────────────────

def test_cash_flow_accrual_vs_cash_differ(active_shop, rent_type, settings_obj):
    """
    Аренда начислена в июне, оплачена частично — ОПиУ и ОДДС
    покажут разные суммы. Ради этого и держим два отчёта.
    """
    Operation.objects.create(shop=active_shop, date=date(2026, 6, 30),
                             op_type=rent_type, accrual=115000, cash=50000)
    p = reports.pnl(active_shop, 2026)
    c = reports.cash_flow(active_shop, 2026)
    june = 5
    assert p['opexTotal']['values'][june]    == pytest.approx(115000)
    assert c['outflowTotal']['values'][june] == pytest.approx(50000)


def test_cash_balance_accumulates(active_shop, sale, rent_type, settings_obj):
    Operation.objects.create(shop=active_shop, date=date(2026, 4, 1),
                             op_type=rent_type, accrual=300, cash=300)
    c = reports.cash_flow(active_shop, 2026)
    # март +1000, апрель −300 → остаток на конец апреля 700
    assert c['closing'][2] == pytest.approx(1000)
    assert c['closing'][3] == pytest.approx(700)
    assert c['closing'][11] == pytest.approx(700)   # тянется до конца года


def test_opening_cash_respected(active_shop, settings_obj):
    settings_obj.opening_cash = 5000
    settings_obj.save()
    c = reports.cash_flow(active_shop, 2026)
    assert c['opening'][0] == pytest.approx(5000)
    assert c['closing'][11] == pytest.approx(5000)


# ── API ───────────────────────────────────────────────────

def test_pnl_endpoint(tech_api, sale, settings_obj):
    r = tech_api.get(PNL, {'year': 2026})
    assert r.status_code == 200
    assert r.json()['incomeTotal']['total'] == pytest.approx(1000)


def test_cashflow_endpoint(tech_api, sale, settings_obj):
    assert tech_api.get(CF, {'year': 2026}).status_code == 200


def test_dashboard_top_products(tech_api, sale, settings_obj):
    r = tech_api.get(DASH, {'year': 2026, 'month': 3})
    body = r.json()
    assert body['summary']['revenue'] == pytest.approx(1000)
    assert body['topProducts'][0]['name'] == 'Торт'
    assert body['topProducts'][0]['marginPct'] == pytest.approx(60.0)


def test_create_operation(tech_api, rent_type, settings_obj):
    r = tech_api.post(OPS, {
        'date': '2026-06-30', 'op_type_id': rent_type.id,
        'counterparty': 'Бал-Дай', 'description': 'Аренда точки',
        'accrual': 115000, 'cash': 115000,
    }, format='json')
    assert r.status_code == 201
    assert r.json()['pnlArticle'] == 'Аренда'
    assert r.json()['receivable'] == 0


def test_operation_receivable(tech_api, rent_type, settings_obj):
    r = tech_api.post(OPS, {
        'date': '2026-06-30', 'op_type_id': rent_type.id,
        'accrual': 100, 'cash': 40,
    }, format='json')
    assert r.json()['receivable'] == pytest.approx(60)


def test_operation_rejects_foreign_type(tech_api, other_shop):
    foreign = OperationType.objects.create(
        shop=other_shop, name='Чужая аренда', flow=OperationType.FLOW_OUT,
        pnl_article='Аренда', cf_article='Аренда оплачено')
    r = tech_api.post(OPS, {'date': '2026-06-30', 'op_type_id': foreign.id,
                            'accrual': 1, 'cash': 1}, format='json')
    assert r.status_code == 404


def test_reports_require_tech_admin(auth_api):
    assert auth_api.get(PNL).status_code == 403
    assert auth_api.get(CF).status_code == 403
    assert auth_api.get(OPS).status_code == 403


def test_reports_isolated_between_shops(tech_api, sale, other_shop):
    other_user = User.objects.create_user(
        username='otherfin', password='pass12345',
        shop=other_shop, role=User.ROLE_TECH_ADMIN)
    other = APIClient()
    other.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(other_user).access_token}')
    assert other.get(PNL, {'year': 2026}).json()['incomeTotal']['total'] == 0


# ── Расшифровка ячейки ────────────────────────────────────

DRILL = '/api/tech-cards/reports/drilldown/'


def test_drilldown_revenue_shows_invoice(tech_api, sale, settings_obj):
    r = tech_api.get(DRILL, {'year': 2026, 'month': 3, 'article': 'Выручка'})
    assert r.status_code == 200
    body = r.json()
    assert body['total'] == pytest.approx(1000)
    assert body['items'][0]['kind'] == 'invoice'
    assert body['items'][0]['title'] == 'Накладная 2026-0001'
    assert body['items'][0]['lines'][0]['name'] == 'Торт'


def test_drilldown_matches_report_cell(tech_api, sale, rent_type, settings_obj):
    """Расшифровка обязана сходиться с самой цифрой — иначе ей нельзя верить."""
    Operation.objects.create(shop=sale.shop, date=date(2026, 3, 20),
                             op_type=rent_type, accrual=115000, cash=115000)
    pnl_row = next(x for x in tech_api.get(PNL, {'year': 2026}).json()['opex']
                   if x['article'] == 'Аренда')
    drill = tech_api.get(DRILL, {'year': 2026, 'month': 3, 'article': 'Аренда'}).json()
    assert drill['total'] == pytest.approx(pnl_row['values'][2])


def test_drilldown_cashflow_uses_cash_not_accrual(tech_api, rent_type, settings_obj):
    """В разрезе ОДДС показываем фактические деньги, а не начисление."""
    Operation.objects.create(shop=rent_type.shop, date=date(2026, 6, 30),
                             op_type=rent_type, accrual=115000, cash=50000)
    r = tech_api.get(DRILL, {'year': 2026, 'month': 6,
                             'article': 'Аренда оплачено', 'report': 'cf'})
    assert r.json()['total'] == pytest.approx(50000)


def test_drilldown_empty_month(tech_api, sale, settings_obj):
    r = tech_api.get(DRILL, {'year': 2026, 'month': 9, 'article': 'Выручка'})
    assert r.json()['items'] == []
    assert r.json()['total'] == 0


def test_drilldown_validates_params(tech_api, settings_obj):
    assert tech_api.get(DRILL, {'year': 2026}).status_code == 400
    assert tech_api.get(DRILL, {'year': 2026, 'month': 13,
                                'article': 'Выручка'}).status_code == 400


def test_drilldown_isolated_between_shops(tech_api, sale, other_shop):
    other_user = User.objects.create_user(
        username='otherdrill', password='pass12345',
        shop=other_shop, role=User.ROLE_TECH_ADMIN)
    other = APIClient()
    other.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(other_user).access_token}')
    assert other.get(DRILL, {'year': 2026, 'month': 3,
                             'article': 'Выручка'}).json()['items'] == []


# ── Реализация по дням ────────────────────────────────────

DAILY = '/api/tech-cards/reports/daily/'


def test_daily_counts_sales(tech_api, sale, settings_obj):
    r = tech_api.get(DAILY, {'year': 2026, 'month': 3})
    body = r.json()['daily']
    day = next(d for d in body['days'] if d['date'] == '2026-03-10')
    assert day['docs'] == 1
    assert day['units'] == pytest.approx(1)
    assert day['revenue'] == pytest.approx(1000)
    assert day['margin'] == pytest.approx(600)


def test_daily_covers_whole_month(tech_api, sale, settings_obj):
    """Дни без продаж тоже в таблице — иначе не видно провалов."""
    body = tech_api.get(DAILY, {'year': 2026, 'month': 3}).json()['daily']
    assert len(body['days']) == 31
    assert body['activeDays'] == 1
    empty = next(d for d in body['days'] if d['date'] == '2026-03-11')
    assert empty['docs'] == 0 and empty['revenue'] == 0


def test_daily_february_length(tech_api, settings_obj):
    body = tech_api.get(DAILY, {'year': 2026, 'month': 2}).json()['daily']
    assert len(body['days']) == 28


def test_daily_cash_differs_from_revenue(tech_api, sale, rent_type, active_shop, settings_obj):
    """
    Реализация и деньги — разные колонки: часть выручки уходит в дебиторку.
    Поступление деньгами добавляется к отгрузке того же дня.
    """
    income = OperationType.objects.create(
        shop=active_shop, name='Поступление от продаж', flow=OperationType.FLOW_IN,
        pnl_article='Выручка', cf_article='Поступления от продаж',
        cf_section='Операционная деятельность')
    Operation.objects.create(shop=active_shop, date=date(2026, 3, 10),
                             op_type=income, accrual=500, cash=200)
    day = next(d for d in tech_api.get(DAILY, {'year': 2026, 'month': 3}).json()['daily']['days']
               if d['date'] == '2026-03-10')
    assert day['revenue'] == pytest.approx(1000)   # только накладная
    assert day['cashIn'] == pytest.approx(1200)    # накладная + деньги операции


def test_daily_avg_uses_active_days_only(tech_api, sale, settings_obj):
    """Средний день считается по дням с продажами, а не по всему месяцу."""
    body = tech_api.get(DAILY, {'year': 2026, 'month': 3}).json()['daily']
    assert body['avgPerDay'] == pytest.approx(1000)   # не 1000/31


def test_daily_today_summary(tech_api, settings_obj):
    body = tech_api.get(DAILY).json()['today']
    assert 'revenue' in body and 'docs' in body


def test_daily_validates_month(tech_api, settings_obj):
    assert tech_api.get(DAILY, {'year': 2026, 'month': 13}).status_code == 400


def test_daily_requires_tech_admin(auth_api):
    assert auth_api.get(DAILY).status_code == 403
