"""Склад цеха: приход сырья, суточный потенциал, запуск производства."""
import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import User
from apps.techcards import costing, services
from apps.techcards.models import (
    FinalProduct, ProductComponent, RawIngredient, SemiFinished, SemiIngredient,
    StockMovement,
)

pytestmark = pytest.mark.django_db

STOCK      = '/api/tech-cards/stock/'
RECEIPTS   = '/api/tech-cards/receipts/'
PRODUCTION = '/api/tech-cards/production/'


@pytest.fixture
def tech_admin(active_shop):
    return User.objects.create_user(
        username='stocktech', password='pass12345',
        shop=active_shop, role=User.ROLE_TECH_ADMIN,
    )


@pytest.fixture
def tech_api(tech_admin):
    client = APIClient()
    client.credentials(
        HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(tech_admin).access_token}')
    return client


@pytest.fixture
def flour(active_shop):
    """Мешок муки 50 кг за 3000 сом → 0.06 сом/гр."""
    return RawIngredient.objects.create(
        shop=active_shop, name='Мука', unit='кг',
        purchase_volume=50, purchase_price=3000)


@pytest.fixture
def cake(active_shop, flour):
    """Кекс: 200 гр муки на штуку → себестоимость 12 сом."""
    product = FinalProduct.objects.create(
        shop=active_shop, name='Кекс', markup_percent=50)
    ProductComponent.objects.create(product=product, raw=flour, quantity=200)
    return product


# ── Остатки и приход ──────────────────────────────────────

def test_stock_starts_empty(tech_api, flour, cake):
    r = tech_api.get(STOCK)
    assert r.status_code == 200
    body = r.json()
    assert body['raw'][0]['balance'] == 0
    assert body['products'][0]['balance'] == 0
    assert body['products'][0]['canProduce'] == 0


def test_receipt_converts_to_base_units(tech_api, flour):
    """Приход 100 кг должен лечь на склад как 100 000 гр — рецепты считаются в граммах."""
    r = tech_api.post(RECEIPTS, {'raw_id': flour.id, 'quantity': 100}, format='json')
    assert r.status_code == 201
    assert r.json()['raw'][0]['balance'] == pytest.approx(100_000)


def test_receipt_in_explicit_unit(tech_api, flour):
    """Приход можно указать в граммах, не только в закупочных килограммах."""
    tech_api.post(RECEIPTS, {'raw_id': flour.id, 'quantity': 500, 'unit': 'гр'}, format='json')
    r = tech_api.get(STOCK)
    assert r.json()['raw'][0]['balance'] == pytest.approx(500)


def test_receipts_accumulate(tech_api, flour):
    for _ in range(3):
        tech_api.post(RECEIPTS, {'raw_id': flour.id, 'quantity': 10}, format='json')
    r = tech_api.get(STOCK)
    assert r.json()['raw'][0]['balance'] == pytest.approx(30_000)


def test_receipt_rejects_zero(tech_api, flour):
    r = tech_api.post(RECEIPTS, {'raw_id': flour.id, 'quantity': 0}, format='json')
    assert r.status_code == 400


def test_receipt_rejects_foreign_raw(tech_api, other_shop):
    """Сырьё чужого магазина недоступно — мультитенантность."""
    foreign = RawIngredient.objects.create(
        shop=other_shop, name='Чужая мука', unit='кг',
        purchase_volume=10, purchase_price=100)
    r = tech_api.post(RECEIPTS, {'raw_id': foreign.id, 'quantity': 5}, format='json')
    assert r.status_code == 404


# ── Суточный потенциал ────────────────────────────────────

def test_can_produce_from_balance(tech_api, flour, cake):
    """10 кг муки при расходе 200 гр/шт → 50 кексов."""
    tech_api.post(RECEIPTS, {'raw_id': flour.id, 'quantity': 10}, format='json')
    r = tech_api.get(STOCK)
    assert r.json()['products'][0]['canProduce'] == 50


def test_can_produce_rounds_down(tech_api, flour, cake):
    """2500 гр / 200 = 12.5 → 12 штук, полуфабрикатов не бывает."""
    tech_api.post(RECEIPTS, {'raw_id': flour.id, 'quantity': 2500, 'unit': 'гр'}, format='json')
    r = tech_api.get(STOCK)
    assert r.json()['products'][0]['canProduce'] == 12


def test_empty_recipe_produces_nothing(tech_api, active_shop, flour):
    """Десерт без состава нельзя выпускать — иначе штуки берутся из воздуха."""
    FinalProduct.objects.create(shop=active_shop, name='Пустой', markup_percent=50)
    tech_api.post(RECEIPTS, {'raw_id': flour.id, 'quantity': 100}, format='json')
    r = tech_api.get(STOCK)
    empty = next(p for p in r.json()['products'] if p['name'] == 'Пустой')
    assert empty['canProduce'] == 0


# ── Запуск производства ───────────────────────────────────

def test_production_moves_stock(tech_api, flour, cake):
    """Выпуск 10 кексов: −2000 гр муки, +10 шт продукции."""
    tech_api.post(RECEIPTS, {'raw_id': flour.id, 'quantity': 10}, format='json')
    r = tech_api.post(PRODUCTION, {'product_id': cake.id, 'quantity': 10}, format='json')
    assert r.status_code == 201

    stock = r.json()['stock']
    assert stock['raw'][0]['balance'] == pytest.approx(10_000 - 2_000)
    assert stock['products'][0]['balance'] == 10


def test_production_freezes_unit_cost(tech_api, flour, cake):
    """Себестоимость выпуска фиксируется: правка техкарты не переписывает историю."""
    tech_api.post(RECEIPTS, {'raw_id': flour.id, 'quantity': 10}, format='json')
    r = tech_api.post(PRODUCTION, {'product_id': cake.id, 'quantity': 5}, format='json')
    assert r.json()['run']['unitCost'] == pytest.approx(12.0)  # 200 гр × 0.06

    flour.purchase_price = 6000  # мука подорожала вдвое
    flour.save()
    hist = tech_api.get('/api/tech-cards/production/history/').json()
    assert hist[0]['unitCost'] == pytest.approx(12.0)


def test_production_allows_negative_stock(tech_api, flour, cake):
    """
    Нехватка сырья не блокирует выпуск (как «списание при отсутствии
    остатков» в 1С): цех не должен стоять из-за непроведённого прихода.
    """
    tech_api.post(RECEIPTS, {'raw_id': flour.id, 'quantity': 1}, format='json')  # 1000 гр
    r = tech_api.post(PRODUCTION, {'product_id': cake.id, 'quantity': 10}, format='json')
    assert r.status_code == 201
    # 10 × 200 = 2000 гр при остатке 1000 → минус 1000
    assert r.json()['stock']['raw'][0]['balance'] == pytest.approx(-1_000)
    assert r.json()['stock']['products'][0]['balance'] == 10


def test_production_reports_negatives(tech_api, flour, cake):
    """Минус не блокирует, но возвращается списком — цех видит его после проведения."""
    tech_api.post(RECEIPTS, {'raw_id': flour.id, 'quantity': 1}, format='json')
    neg = tech_api.post(PRODUCTION, {'product_id': cake.id, 'quantity': 10},
                        format='json').json()['negatives']
    assert len(neg) == 1
    assert neg[0]['name'] == 'Мука'
    assert neg[0]['required'] == pytest.approx(2_000)
    assert neg[0]['was'] == pytest.approx(1_000)
    assert neg[0]['rest'] == pytest.approx(-1_000)


def test_production_without_any_stock(tech_api, flour, cake):
    """Выпуск с нулевого склада проходит — себестоимость всё равно по техкарте."""
    r = tech_api.post(PRODUCTION, {'product_id': cake.id, 'quantity': 110}, format='json')
    assert r.status_code == 201
    assert r.json()['run']['unitCost'] == pytest.approx(12.0)
    assert r.json()['stock']['raw'][0]['balance'] == pytest.approx(-22_000)


def test_production_exact_stock_leaves_no_negatives(tech_api, flour, cake):
    """Ровно на границе остатка минуса нет."""
    tech_api.post(RECEIPTS, {'raw_id': flour.id, 'quantity': 2, 'unit': 'кг'}, format='json')
    r = tech_api.post(PRODUCTION, {'product_id': cake.id, 'quantity': 10}, format='json')
    assert r.status_code == 201
    assert r.json()['negatives'] == []
    assert tech_api.get(STOCK).json()['raw'][0]['balance'] == pytest.approx(0)


def test_production_rejects_zero_quantity(tech_api, flour, cake):
    r = tech_api.post(PRODUCTION, {'product_id': cake.id, 'quantity': 0}, format='json')
    assert r.status_code == 400


# ── Расход через полуфабрикат ─────────────────────────────

def test_semi_finished_consumes_raw(tech_api, active_shop, flour):
    """
    Сырьё, попадающее в десерт только через замес, тоже обязано списываться.
    Бисквит: 1000 гр муки → выход 2000 гр. Торт: 500 гр бисквита.
    Значит на 1 торт уходит 500 × (1000/2000) = 250 гр муки.
    """
    biscuit = SemiFinished.objects.create(
        shop=active_shop, name='Бисквит', batch_output=2000)
    SemiIngredient.objects.create(semi=biscuit, ingredient=flour, quantity=1000)

    torte = FinalProduct.objects.create(
        shop=active_shop, name='Торт', markup_percent=50)
    ProductComponent.objects.create(product=torte, semi=biscuit, quantity=500)

    usage = costing.raw_usage_per_product(torte)
    assert usage[flour.id] == pytest.approx(250)

    tech_api.post(RECEIPTS, {'raw_id': flour.id, 'quantity': 1}, format='json')  # 1000 гр
    r = tech_api.get(STOCK)
    torte_row = next(p for p in r.json()['products'] if p['name'] == 'Торт')
    assert torte_row['canProduce'] == 4  # 1000 / 250

    tech_api.post(PRODUCTION, {'product_id': torte.id, 'quantity': 4}, format='json')
    assert tech_api.get(STOCK).json()['raw'][0]['balance'] == pytest.approx(0)


# ── Изоляция и доступ ─────────────────────────────────────

def test_stock_requires_tech_admin(auth_api):
    assert auth_api.get(STOCK).status_code == 403
    assert auth_api.post(PRODUCTION, {}, format='json').status_code == 403


def test_stock_isolated_between_shops(tech_api, flour, other_shop):
    """Приход в одном магазине не виден в другом."""
    tech_api.post(RECEIPTS, {'raw_id': flour.id, 'quantity': 10}, format='json')
    other_user = User.objects.create_user(
        username='othertech2', password='pass12345',
        shop=other_shop, role=User.ROLE_TECH_ADMIN)
    other = APIClient()
    other.credentials(
        HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(other_user).access_token}')
    assert other.get(STOCK).json()['raw'] == []


def test_service_layer_matches_api(active_shop, flour, cake):
    """Сервис и API дают один результат — логика не расходится между слоями."""
    services.receive_raw(active_shop, flour, 5)
    services.run_production(active_shop, cake, 3)   # → (run, negatives)
    snap = services.stock_snapshot(active_shop)
    assert snap['raw'][0]['balance'] == pytest.approx(5_000 - 600)
    assert snap['products'][0]['balance'] == 3
