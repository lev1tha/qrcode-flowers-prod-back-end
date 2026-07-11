"""Панель суперадмина: токен-доступ, CRUD магазинов/кассиров, защита мастера."""
import pytest

from apps.accounts.models import User

pytestmark = pytest.mark.django_db

LOGIN = '/api/superadmin/login/'
SHOPS = '/api/superadmin/shops/'


def test_shops_require_sa_token(api):
    # без X-SA-Token доступа нет
    assert api.get(SHOPS).status_code == 401


def test_shops_reject_wrong_token(api, sa):
    assert api.get(SHOPS, HTTP_X_SA_TOKEN='wrong').status_code == 401


def test_sa_login_success(api, sa):
    r = api.post(LOGIN, {'login': 'admin', 'password': 'admin-pass'}, format='json')
    assert r.status_code == 200
    assert r.json()['token'] == 'test-sa-token'


def test_sa_login_wrong(api, sa):
    assert api.post(LOGIN, {'login': 'admin', 'password': 'bad'}, format='json').status_code == 401


def test_list_shops_returns_shops_and_stats(api, sa, active_shop):
    r = api.get(SHOPS, **sa)
    assert r.status_code == 200
    body = r.json()
    assert 'shops' in body and 'stats' in body
    assert body['stats']['total'] >= 1


def test_create_shop(api, sa):
    r = api.post(SHOPS, {'name': 'Новый магазин', 'owner': 'Кто-то'}, format='json', **sa)
    assert r.status_code == 201
    assert r.json()['name'] == 'Новый магазин'


def test_create_cashier_for_shop(api, sa, active_shop):
    url = f'{SHOPS}{active_shop.id}/users/'
    r = api.post(url, {'username': 'newcashier', 'password': 'pass12345'}, format='json', **sa)
    assert r.status_code == 201
    assert User.objects.filter(username='newcashier', shop=active_shop).exists()


def test_create_cashier_rejects_duplicate(api, sa, active_shop, cashier):
    url = f'{SHOPS}{active_shop.id}/users/'
    r = api.post(url, {'username': 'cash', 'password': 'pass12345'}, format='json', **sa)
    assert r.status_code == 400


def test_master_shop_cannot_be_deleted(api, sa, master_shop):
    assert api.delete(f'{SHOPS}{master_shop.id}/', **sa).status_code == 400


def test_master_shop_cannot_be_disabled(api, sa, master_shop):
    r = api.patch(f'{SHOPS}{master_shop.id}/', {'active': False}, format='json', **sa)
    assert r.status_code == 400
