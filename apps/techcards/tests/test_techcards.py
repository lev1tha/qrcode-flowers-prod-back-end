"""Техкарты: доступ только тех-админу, изоляция магазинов, вложенные рецептуры."""
import pytest
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.techcards.models import RawIngredient, SemiFinished, FinalProduct

pytestmark = pytest.mark.django_db

BASE = '/api/tech-cards/'


@pytest.fixture
def tech_admin(active_shop):
    return User.objects.create_user(
        username='techadmin', password='pass12345',
        shop=active_shop, role='admin', is_tech_admin=True,
    )


@pytest.fixture
def tech_api(tech_admin):
    client = APIClient()
    token = RefreshToken.for_user(tech_admin).access_token
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
    return client


@pytest.fixture
def other_tech_api(other_shop):
    """Тех-админ ЧУЖОГО магазина — для проверки изоляции."""
    user = User.objects.create_user(
        username='othertech', password='pass12345',
        shop=other_shop, role='admin', is_tech_admin=True,
    )
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(user).access_token}')
    return client


def _sugar(shop):
    return RawIngredient.objects.create(
        shop=shop, name='Сахар', unit='кг', purchase_volume=50, purchase_price=3400)


# ── Доступ ────────────────────────────────────────────────

def test_requires_auth(api):
    assert api.get(BASE).status_code == 401


def test_cashier_denied(auth_api):
    """Обычному кассиру раздел закрыт — 403."""
    assert auth_api.get(BASE).status_code == 403
    assert auth_api.post(f'{BASE}raw/', {}, format='json').status_code == 403


def test_tech_admin_allowed(tech_api):
    r = tech_api.get(BASE)
    assert r.status_code == 200
    assert r.json() == {'raw': [], 'semi': [], 'products': []}


# ── Сырьё ─────────────────────────────────────────────────

def test_raw_crud(tech_api, tech_admin):
    r = tech_api.post(f'{BASE}raw/', {
        'name': 'Сахар', 'unit': 'кг', 'purchaseVolume': 50, 'purchasePrice': 3400,
    }, format='json')
    assert r.status_code == 201
    raw_id = r.json()['id']
    assert RawIngredient.objects.get(id=raw_id).shop_id == tech_admin.shop_id

    r = tech_api.put(f'{BASE}raw/{raw_id}/', {
        'name': 'Сахар-песок', 'unit': 'кг', 'purchaseVolume': 25, 'purchasePrice': 1800,
    }, format='json')
    assert r.status_code == 200
    assert r.json()['purchaseVolume'] == 25

    assert tech_api.delete(f'{BASE}raw/{raw_id}/').status_code == 204


def test_raw_isolation(tech_api, other_tech_api, tech_admin):
    _sugar(tech_admin.shop)
    r = other_tech_api.get(f'{BASE}raw/')
    assert r.status_code == 200
    assert r.json() == []


# ── Полуфабрикаты ─────────────────────────────────────────

def test_semi_with_ingredients(tech_api, tech_admin):
    sugar = _sugar(tech_admin.shop)
    r = tech_api.post(f'{BASE}semi/', {
        'name': 'Сироп', 'batchOutput': 500,
        'ingredients': [{'ingredientId': sugar.id, 'quantity': 300}],
    }, format='json')
    assert r.status_code == 201
    body = r.json()
    assert body['ingredients'] == [{'ingredientId': sugar.id, 'quantity': 300}]

    # Обновление пересобирает рецепт целиком
    r = tech_api.put(f'{BASE}semi/{body["id"]}/', {
        'name': 'Сироп', 'batchOutput': 450,
        'ingredients': [{'ingredientId': sugar.id, 'quantity': 250}],
    }, format='json')
    assert r.status_code == 200
    assert r.json()['ingredients'][0]['quantity'] == 250


def test_semi_rejects_foreign_ingredient(tech_api, other_shop):
    foreign = _sugar(other_shop)
    r = tech_api.post(f'{BASE}semi/', {
        'name': 'Сироп', 'batchOutput': 500,
        'ingredients': [{'ingredientId': foreign.id, 'quantity': 300}],
    }, format='json')
    assert r.status_code == 400


def test_semi_requires_ingredients(tech_api):
    r = tech_api.post(f'{BASE}semi/', {
        'name': 'Пустой', 'batchOutput': 100, 'ingredients': [],
    }, format='json')
    assert r.status_code == 400


# ── Десерты ───────────────────────────────────────────────

def test_product_composition_and_manual_price(tech_api, tech_admin):
    sugar = _sugar(tech_admin.shop)
    semi = SemiFinished.objects.create(shop=tech_admin.shop, name='Крем', batch_output=1000)

    r = tech_api.post(f'{BASE}products/', {
        'name': 'Десерт', 'markupPercent': 50, 'retailPrice': None,
        'composition': [
            {'type': 'semi', 'id': semi.id, 'quantity': 120},
            {'type': 'raw',  'id': sugar.id, 'quantity': 15},
        ],
    }, format='json')
    assert r.status_code == 201
    body = r.json()
    assert body['retailPrice'] is None
    assert {c['type'] for c in body['composition']} == {'raw', 'semi'}

    # Ручная цена сохраняется
    r = tech_api.put(f'{BASE}products/{body["id"]}/', {
        'name': 'Десерт', 'markupPercent': 60, 'retailPrice': 120,
        'composition': [{'type': 'raw', 'id': sugar.id, 'quantity': 15}],
    }, format='json')
    assert r.status_code == 200
    assert r.json()['retailPrice'] == 120


def test_product_rejects_unknown_component(tech_api):
    r = tech_api.post(f'{BASE}products/', {
        'name': 'Десерт', 'markupPercent': 50,
        'composition': [{'type': 'raw', 'id': 99999, 'quantity': 10}],
    }, format='json')
    assert r.status_code == 400


def test_overview_returns_all_sections(tech_api, tech_admin):
    sugar = _sugar(tech_admin.shop)
    semi = SemiFinished.objects.create(shop=tech_admin.shop, name='Крем', batch_output=1000)
    product = FinalProduct.objects.create(shop=tech_admin.shop, name='Десерт', markup_percent=50)

    r = tech_api.get(BASE)
    assert r.status_code == 200
    body = r.json()
    assert [x['name'] for x in body['raw']] == ['Сахар']
    assert [x['name'] for x in body['semi']] == ['Крем']
    assert [x['name'] for x in body['products']] == ['Десерт']


def test_cascade_raw_delete_cleans_recipes(tech_api, tech_admin):
    """Удаление сырья вычищает его из рецептов (CASCADE), сами рецепты живы."""
    sugar = _sugar(tech_admin.shop)
    r = tech_api.post(f'{BASE}semi/', {
        'name': 'Сироп', 'batchOutput': 500,
        'ingredients': [{'ingredientId': sugar.id, 'quantity': 300}],
    }, format='json')
    semi_id = r.json()['id']

    assert tech_api.delete(f'{BASE}raw/{sugar.id}/').status_code == 204
    r = tech_api.get(f'{BASE}semi/{semi_id}/')
    assert r.status_code == 200
    assert r.json()['ingredients'] == []


# ── Роль tech_admin ───────────────────────────────────────

@pytest.fixture
def role_tech_api(active_shop):
    """Тех-админ по РОЛИ, без ручной установки is_tech_admin."""
    user = User.objects.create_user(
        username='roletech', password='pass12345',
        shop=active_shop, role=User.ROLE_TECH_ADMIN,
    )
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(user).access_token}')
    return client


def test_role_tech_admin_allowed(role_tech_api):
    """Роли tech_admin достаточно для доступа — флаг руками не нужен."""
    assert role_tech_api.get(BASE).status_code == 200


def test_role_tech_admin_syncs_flag(active_shop):
    """save() выставляет is_tech_admin по роли — фронт читает его из логина."""
    user = User.objects.create_user(
        username='syncme', password='pass12345',
        shop=active_shop, role=User.ROLE_TECH_ADMIN,
    )
    user.refresh_from_db()
    assert user.is_tech_admin is True
    assert user.has_tech_access is True


def test_legacy_flag_still_grants_access(tech_admin):
    """Старая схема (role=admin + флаг) продолжает работать."""
    assert tech_admin.role == 'admin'
    assert tech_admin.has_tech_access is True


def test_tech_admin_without_shop_denied(active_shop):
    """Роль без магазина доступа не даёт — данные скоупятся по shop."""
    user = User.objects.create_user(
        username='noshop', password='pass12345', role=User.ROLE_TECH_ADMIN)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(user).access_token}')
    assert client.get(BASE).status_code == 403
