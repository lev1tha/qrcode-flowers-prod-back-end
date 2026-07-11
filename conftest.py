"""Общие фикстуры для pytest-django."""
from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import Shop, User


@pytest.fixture
def api():
    return APIClient()


@pytest.fixture
def active_shop(db):
    return Shop.objects.create(
        name='Активный магазин', owner='Овнер', active=True,
        subscription_end=timezone.now() + timedelta(days=30),
    )


@pytest.fixture
def other_shop(db):
    return Shop.objects.create(
        name='Другой магазин', owner='Овнер2', active=True,
        subscription_end=timezone.now() + timedelta(days=30),
    )


@pytest.fixture
def expired_shop(db):
    return Shop.objects.create(
        name='Истёкший магазин', owner='Овнер', active=True,
        subscription_end=timezone.now() - timedelta(days=1),
    )


@pytest.fixture
def master_shop(db):
    return Shop.objects.create(name='Мастер-магазин', is_master=True, active=True)


def _make_cashier(shop, username='cash', password='pass12345'):
    return User.objects.create_user(username=username, password=password,
                                    shop=shop, role='cashier')


@pytest.fixture
def cashier(active_shop):
    return _make_cashier(active_shop)


@pytest.fixture
def auth_api(api, cashier):
    """APIClient с валидным Bearer-токеном кассира активного магазина."""
    token = RefreshToken.for_user(cashier).access_token
    api.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
    return api


@pytest.fixture
def sa(settings):
    """Фиксируем креды суперадмина и возвращаем валидный X-SA-Token."""
    settings.SUPERADMIN_LOGIN = 'admin'
    settings.SUPERADMIN_PASSWORD = 'admin-pass'
    settings.SUPERADMIN_TOKEN = 'test-sa-token'
    return {'HTTP_X_SA_TOKEN': 'test-sa-token'}
