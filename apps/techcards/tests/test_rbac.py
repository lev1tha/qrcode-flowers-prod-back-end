"""Ролевой доступ к участкам цеха (модель 1С)."""
import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import User
from apps.techcards.models import FinalProduct, ProductComponent, RawIngredient

pytestmark = pytest.mark.django_db

RAW        = '/api/tech-cards/raw/'
RECEIPTS   = '/api/tech-cards/receipts/'
STOCK      = '/api/tech-cards/stock/'
PRODUCTION = '/api/tech-cards/production/'
INVOICES   = '/api/tech-cards/invoices/'
PRODUCTS   = '/api/tech-cards/products/'
PNL        = '/api/tech-cards/reports/pnl/'
OPS        = '/api/tech-cards/operations/'
DISPOSALS  = '/api/tech-cards/disposals/'


def client_for(shop, role, username):
    user = User.objects.create_user(
        username=username, password='pass12345', shop=shop, role=role)
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(user).access_token}')
    return c


@pytest.fixture
def storekeeper(active_shop):
    return client_for(active_shop, User.ROLE_STOREKEEPER, 'sklad')


@pytest.fixture
def production(active_shop):
    return client_for(active_shop, User.ROLE_PRODUCTION, 'tseh')


@pytest.fixture
def seller(active_shop):
    return client_for(active_shop, User.ROLE_SELLER, 'prodavec')


@pytest.fixture
def techadmin(active_shop):
    return client_for(active_shop, User.ROLE_TECH_ADMIN, 'tehnolog')


@pytest.fixture
def cake(active_shop):
    raw = RawIngredient.objects.create(
        shop=active_shop, name='Мука', unit='кг', purchase_volume=50, purchase_price=3000)
    p = FinalProduct.objects.create(shop=active_shop, name='Кекс', markup_percent=50)
    ProductComponent.objects.create(product=p, raw=raw, quantity=200)
    return p


# ── Складовщик / закупщик ─────────────────────────────────

def test_storekeeper_manages_raw(storekeeper, cake):
    assert storekeeper.get(RAW).status_code == 200
    assert storekeeper.post(RAW, {'name': 'Сахар', 'unit': 'кг',
                                  'purchaseVolume': 50, 'purchasePrice': 3400},
                            format='json').status_code == 201


def test_storekeeper_denied_sales_and_finance(storekeeper):
    """Закупщику закрыты продажи, касса и финансы."""
    assert storekeeper.get(INVOICES).status_code == 403
    assert storekeeper.get(PNL).status_code == 403
    assert storekeeper.get(OPS).status_code == 403


def test_storekeeper_denied_production(storekeeper, cake):
    assert storekeeper.post(PRODUCTION, {'product_id': cake.id, 'quantity': 1},
                            format='json').status_code == 403


def test_storekeeper_sees_raw_stock_only(storekeeper, cake):
    body = storekeeper.get(STOCK).json()
    assert len(body['raw']) == 1
    assert body['products'] == []


# ── Производство / цех ────────────────────────────────────

def test_production_can_run(production, cake):
    r = production.post(PRODUCTION, {'product_id': cake.id, 'quantity': 110}, format='json')
    assert r.status_code == 201
    assert r.json()['run']['quantity'] == 110


def test_production_denied_purchases_and_finance(production):
    """Цеху закрыты закуп сырья, финансы и продажи."""
    assert production.post(RAW, {'name': 'X', 'unit': 'кг',
                                 'purchaseVolume': 1, 'purchasePrice': 1},
                           format='json').status_code == 403
    assert production.post(RECEIPTS, {'raw_id': 1, 'quantity': 1},
                           format='json').status_code == 403
    assert production.get(PNL).status_code == 403
    assert production.get(INVOICES).status_code == 403


def test_production_does_not_see_raw_stock(production, cake):
    """
    По ТЗ цех не видит общий остаток сырья. Режем на сервере, а не в UI —
    иначе данные утекали бы в ответе API мимо интерфейса.
    """
    body = production.get(STOCK).json()
    assert body['raw'] == []
    assert len(body['products']) == 1
    assert 'canProduce' not in body['products'][0]


def test_production_reads_products_but_cannot_edit(production, cake):
    assert production.get(PRODUCTS).status_code == 200
    assert production.post(PRODUCTS, {'name': 'Новый', 'markupPercent': 50,
                                      'composition': []},
                           format='json').status_code == 403


# ── Продавец ──────────────────────────────────────────────

def test_seller_can_sell(seller, cake, techadmin):
    techadmin.post(PRODUCTION, {'product_id': cake.id, 'quantity': 10}, format='json')
    r = seller.post(INVOICES, {
        'date': '2026-07-20', 'from_department': 'outlet', 'to_client': 'Глобус',
        'lines': [{'product_id': cake.id, 'quantity': 2, 'sell_price': 30}],
    }, format='json')
    assert r.status_code == 201


def test_seller_denied_raw_and_production(seller, cake):
    """Продавцу закрыты склад сырья, проведение закупок и техкарты."""
    assert seller.get(RAW).status_code == 403
    assert seller.post(RECEIPTS, {'raw_id': 1, 'quantity': 1}, format='json').status_code == 403
    assert seller.post(PRODUCTION, {'product_id': cake.id, 'quantity': 1},
                       format='json').status_code == 403
    assert seller.post(PRODUCTS, {'name': 'X', 'markupPercent': 50, 'composition': []},
                       format='json').status_code == 403


def test_seller_sees_finished_goods_only(seller, cake):
    body = seller.get(STOCK).json()
    assert body['raw'] == []
    assert len(body['products']) == 1


# ── Технолог видит всё ────────────────────────────────────

def test_tech_admin_has_full_access(techadmin, cake):
    for url in (RAW, STOCK, INVOICES, PNL, OPS, DISPOSALS, PRODUCTS):
        assert techadmin.get(url).status_code == 200, url


def test_tech_admin_sees_full_stock(techadmin, cake):
    body = techadmin.get(STOCK).json()
    assert len(body['raw']) == 1
    assert 'canProduce' in body['products'][0]


# ── Посторонние роли ──────────────────────────────────────

def test_cashier_denied_everywhere(auth_api, cake):
    for url in (RAW, STOCK, INVOICES, PNL, PRODUCTS):
        assert auth_api.get(url).status_code == 403, url
