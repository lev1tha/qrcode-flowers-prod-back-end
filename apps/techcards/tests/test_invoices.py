"""Накладные реализации и списание брака."""
import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import User
from apps.techcards import services
from apps.techcards.models import (
    Disposal, FinalProduct, Invoice, ProductComponent, RawIngredient, StockMovement,
)

pytestmark = pytest.mark.django_db

INVOICES  = '/api/tech-cards/invoices/'
DISPOSALS = '/api/tech-cards/disposals/'
STOCK     = '/api/tech-cards/stock/'
TODAY     = '2026-07-20'


@pytest.fixture
def tech_admin(active_shop):
    return User.objects.create_user(
        username='invtech', password='pass12345',
        shop=active_shop, role=User.ROLE_TECH_ADMIN)


@pytest.fixture
def tech_api(tech_admin):
    client = APIClient()
    client.credentials(
        HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(tech_admin).access_token}')
    return client


@pytest.fixture
def flour(active_shop):
    """50 кг за 3000 сом → 0.06 сом/гр."""
    return RawIngredient.objects.create(
        shop=active_shop, name='Мука', unit='кг',
        purchase_volume=50, purchase_price=3000)


@pytest.fixture
def cake(active_shop, flour):
    """200 гр муки на штуку → себестоимость 12.00 сом."""
    product = FinalProduct.objects.create(
        shop=active_shop, name='Кекс', markup_percent=50)
    ProductComponent.objects.create(product=product, raw=flour, quantity=200)
    return product


@pytest.fixture
def stocked(active_shop, flour, cake):
    """Склад с 20 выпущенными кексами."""
    services.receive_raw(active_shop, flour, 10)      # 10 000 гр
    services.run_production(active_shop, cake, 20)    # −4 000 гр, +20 шт
    return cake


def line(product, qty=5, price=18.0):
    return {'product_id': product.id, 'quantity': qty, 'sell_price': price}


# ── Проведение накладной ──────────────────────────────────

def test_post_invoice_deducts_stock(tech_api, stocked):
    r = tech_api.post(INVOICES, {
        'date': TODAY, 'from_department': 'workshop', 'to_client': 'Глобус',
        'lines': [line(stocked, 5, 18)],
    }, format='json')
    assert r.status_code == 201

    inv = r.json()['invoice']
    assert inv['toClient'] == 'Глобус'
    assert inv['fromDepartmentLabel'] == 'Цех'
    # 5 × 12.00 = 60.00 себестоимость; 5 × 18.00 = 90.00 выручка
    assert inv['costTotal']    == pytest.approx(60.0)
    assert inv['revenueTotal'] == pytest.approx(90.0)
    assert inv['marginTotal']  == pytest.approx(30.0)
    # склад уменьшился на 5
    assert r.json()['stock']['products'][0]['balance'] == 15


def test_invoice_number_is_sequential(tech_api, stocked):
    numbers = []
    for _ in range(3):
        r = tech_api.post(INVOICES, {
            'date': TODAY, 'from_department': 'workshop', 'to_client': 'Артём',
            'lines': [line(stocked, 1, 20)],
        }, format='json')
        numbers.append(r.json()['invoice']['number'])
    assert numbers == ['2026-0001', '2026-0002', '2026-0003']


def test_invoice_freezes_cost(tech_api, stocked, flour):
    """Правка техкарты не переписывает проведённый документ."""
    r = tech_api.post(INVOICES, {
        'date': TODAY, 'from_department': 'workshop', 'to_client': 'Глобус',
        'lines': [line(stocked, 5, 18)],
    }, format='json')
    invoice_id = r.json()['invoice']['id']

    flour.purchase_price = 9000   # мука подорожала втрое
    flour.save()

    again = tech_api.get(f'{INVOICES}{invoice_id}/').json()
    assert again['costTotal'] == pytest.approx(60.0)
    assert again['lines'][0]['unitCost'] == pytest.approx(12.0)


def test_invoice_rejects_more_than_stock(tech_api, stocked):
    r = tech_api.post(INVOICES, {
        'date': TODAY, 'from_department': 'workshop', 'to_client': 'Глобус',
        'lines': [line(stocked, 999, 18)],
    }, format='json')
    assert r.status_code == 400
    assert 'Кекс' in str(r.json())


def test_invoice_sums_duplicate_lines_before_check(tech_api, stocked):
    """
    Две строки по одной позиции нельзя провести в обход остатка:
    20 на складе, 15 + 10 = 25 — должно упасть.
    """
    r = tech_api.post(INVOICES, {
        'date': TODAY, 'from_department': 'workshop', 'to_client': 'Глобус',
        'lines': [line(stocked, 15, 18), line(stocked, 10, 18)],
    }, format='json')
    assert r.status_code == 400
    assert tech_api.get(STOCK).json()['products'][0]['balance'] == 20


def test_failed_invoice_leaves_no_trace(tech_api, stocked):
    """Провалившееся проведение не оставляет ни документа, ни движений."""
    before_inv = Invoice.objects.count()
    before_mov = StockMovement.objects.count()
    tech_api.post(INVOICES, {
        'date': TODAY, 'from_department': 'workshop', 'to_client': 'Глобус',
        'lines': [line(stocked, 999, 18)],
    }, format='json')
    assert Invoice.objects.count() == before_inv
    assert StockMovement.objects.count() == before_mov


def test_invoice_rejects_empty_lines(tech_api, stocked):
    r = tech_api.post(INVOICES, {
        'date': TODAY, 'from_department': 'workshop',
        'to_client': 'Глобус', 'lines': [],
    }, format='json')
    assert r.status_code == 400


def test_invoice_rejects_foreign_product(tech_api, other_shop):
    foreign = FinalProduct.objects.create(
        shop=other_shop, name='Чужой торт', markup_percent=50)
    r = tech_api.post(INVOICES, {
        'date': TODAY, 'from_department': 'workshop', 'to_client': 'Глобус',
        'lines': [line(foreign, 1, 10)],
    }, format='json')
    assert r.status_code == 400


def test_client_cannot_forge_cost(tech_api, stocked):
    """Себестоимость приходит с сервера — подсунутая клиентом игнорируется."""
    r = tech_api.post(INVOICES, {
        'date': TODAY, 'from_department': 'workshop', 'to_client': 'Глобус',
        'lines': [{'product_id': stocked.id, 'quantity': 5,
                   'sell_price': 18, 'unit_cost': 0.01}],
    }, format='json')
    assert r.json()['invoice']['lines'][0]['unitCost'] == pytest.approx(12.0)


# ── Архив ─────────────────────────────────────────────────

def test_archive_lists_invoices(tech_api, stocked):
    tech_api.post(INVOICES, {
        'date': TODAY, 'from_department': 'sales', 'to_client': 'Артём',
        'lines': [line(stocked, 2, 25)],
    }, format='json')
    archive = tech_api.get(INVOICES).json()
    assert len(archive) == 1
    assert archive[0]['toClient'] == 'Артём'
    assert archive[0]['fromDepartmentLabel'] == 'Отдел продаж'
    assert archive[0]['revenueTotal'] == pytest.approx(50.0)


def test_archive_isolated_between_shops(tech_api, stocked, other_shop):
    tech_api.post(INVOICES, {
        'date': TODAY, 'from_department': 'workshop', 'to_client': 'Глобус',
        'lines': [line(stocked, 1, 18)],
    }, format='json')
    other_user = User.objects.create_user(
        username='othertech3', password='pass12345',
        shop=other_shop, role=User.ROLE_TECH_ADMIN)
    other = APIClient()
    other.credentials(
        HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(other_user).access_token}')
    assert other.get(INVOICES).json() == []


# ── Списание ──────────────────────────────────────────────

def test_dispose_product(tech_api, stocked):
    r = tech_api.post(DISPOSALS, {
        'item_type': 'product', 'item_id': stocked.id,
        'quantity': 3, 'reason': 'defect',
    }, format='json')
    assert r.status_code == 201
    d = r.json()['disposal']
    assert d['lossAmount'] == pytest.approx(36.0)   # 3 × 12.00
    assert d['reasonLabel'] == 'Брак'
    assert d['unitLabel'] == 'шт'
    assert r.json()['stock']['products'][0]['balance'] == 17


def test_dispose_raw(tech_api, stocked, flour):
    """Списание сырья идёт в базовых единицах."""
    r = tech_api.post(DISPOSALS, {
        'item_type': 'raw', 'item_id': flour.id,
        'quantity': 1000, 'reason': 'expired',
    }, format='json')
    assert r.status_code == 201
    assert r.json()['disposal']['lossAmount'] == pytest.approx(60.0)  # 1000 × 0.06
    assert r.json()['disposal']['unitLabel'] == 'гр'
    # было 10 000 − 4 000 (производство) = 6 000, минус 1 000
    assert r.json()['stock']['raw'][0]['balance'] == pytest.approx(5_000)


def test_dispose_rejects_more_than_stock(tech_api, stocked):
    r = tech_api.post(DISPOSALS, {
        'item_type': 'product', 'item_id': stocked.id,
        'quantity': 999, 'reason': 'defect',
    }, format='json')
    assert r.status_code == 400
    assert tech_api.get(STOCK).json()['products'][0]['balance'] == 20


def test_dispose_rejects_unknown_reason(tech_api, stocked):
    r = tech_api.post(DISPOSALS, {
        'item_type': 'product', 'item_id': stocked.id,
        'quantity': 1, 'reason': 'потому что',
    }, format='json')
    assert r.status_code == 400


def test_disposal_journal_totals_loss(tech_api, stocked, flour):
    tech_api.post(DISPOSALS, {'item_type': 'product', 'item_id': stocked.id,
                              'quantity': 2, 'reason': 'defect'}, format='json')
    tech_api.post(DISPOSALS, {'item_type': 'raw', 'item_id': flour.id,
                              'quantity': 500, 'reason': 'tasting'}, format='json')
    body = tech_api.get(DISPOSALS).json()
    assert len(body['disposals']) == 2
    # 2 × 12.00 + 500 × 0.06 = 24.00 + 30.00
    assert body['lossTotal'] == pytest.approx(54.0)


def test_disposal_then_invoice_respects_new_balance(tech_api, stocked):
    """Списание уменьшает остаток и для последующей отгрузки."""
    tech_api.post(DISPOSALS, {'item_type': 'product', 'item_id': stocked.id,
                              'quantity': 18, 'reason': 'defect'}, format='json')
    r = tech_api.post(INVOICES, {
        'date': TODAY, 'from_department': 'workshop', 'to_client': 'Глобус',
        'lines': [line(stocked, 5, 18)],
    }, format='json')
    assert r.status_code == 400   # осталось всего 2


# ── Доступ ────────────────────────────────────────────────

def test_endpoints_require_tech_admin(auth_api):
    assert auth_api.get(INVOICES).status_code == 403
    assert auth_api.post(INVOICES, {}, format='json').status_code == 403
    assert auth_api.get(DISPOSALS).status_code == 403
    assert auth_api.post(DISPOSALS, {}, format='json').status_code == 403
