"""Авторизация кассира: /api/auth/login|me|refresh."""
import pytest

from apps.accounts.models import User

pytestmark = pytest.mark.django_db

LOGIN   = '/api/auth/login/'
ME      = '/api/auth/me/'
REFRESH = '/api/auth/refresh/'


def test_login_success(api, cashier):
    r = api.post(LOGIN, {'username': 'cash', 'password': 'pass12345'}, format='json')
    assert r.status_code == 200
    body = r.json()
    assert body['access'] and body['refresh']
    assert body['user']['username'] == 'cash'
    assert body['user']['shop_active'] is True


def test_login_wrong_password(api, cashier):
    r = api.post(LOGIN, {'username': 'cash', 'password': 'nope'}, format='json')
    assert r.status_code == 401


def test_login_inactive_user(api, active_shop):
    User.objects.create_user(username='off', password='pass12345',
                             shop=active_shop, role='cashier', is_active=False)
    r = api.post(LOGIN, {'username': 'off', 'password': 'pass12345'}, format='json')
    # authenticate() отсеивает неактивных → неверные креды
    assert r.status_code in (401, 403)


def test_login_expired_subscription_blocked(api, expired_shop):
    User.objects.create_user(username='exp', password='pass12345',
                             shop=expired_shop, role='cashier')
    r = api.post(LOGIN, {'username': 'exp', 'password': 'pass12345'}, format='json')
    assert r.status_code == 403
    assert 'подписк' in r.json()['detail'].lower()


def test_me_requires_auth(api):
    assert api.get(ME).status_code == 401


def test_me_returns_current_user(auth_api):
    r = auth_api.get(ME)
    assert r.status_code == 200
    assert r.json()['username'] == 'cash'


def test_refresh_returns_new_access(api, cashier):
    login = api.post(LOGIN, {'username': 'cash', 'password': 'pass12345'}, format='json').json()
    r = api.post(REFRESH, {'refresh': login['refresh']}, format='json')
    assert r.status_code == 200
    assert r.json()['access']


def test_refresh_rejects_garbage(api):
    assert api.post(REFRESH, {'refresh': 'not-a-token'}, format='json').status_code == 401
