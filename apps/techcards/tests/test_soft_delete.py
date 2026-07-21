"""Мягкое удаление справочников и защита истории склада."""
import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import User
from apps.techcards import services
from apps.techcards.models import (
    FinalProduct, ProductComponent, RawIngredient, StockMovement,
)

pytestmark = pytest.mark.django_db

RAW      = '/api/tech-cards/raw/'
PRODUCTS = '/api/tech-cards/products/'
STOCK    = '/api/tech-cards/stock/'


@pytest.fixture
def api(active_shop):
    u = User.objects.create_user(username='soft', password='pass12345',
                                 shop=active_shop, role=User.ROLE_TECH_ADMIN)
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(u).access_token}')
    return c


@pytest.fixture
def flour(active_shop):
    return RawIngredient.objects.create(
        shop=active_shop, name='Мука', unit='кг',
        purchase_volume=50, purchase_price=3000)


@pytest.fixture
def cake(active_shop, flour):
    p = FinalProduct.objects.create(shop=active_shop, name='Кекс', markup_percent=50)
    ProductComponent.objects.create(product=p, raw=flour, quantity=200)
    return p


# ── Мягкое удаление ───────────────────────────────────────

def test_delete_product_is_soft(api, cake):
    """DELETE помечает, а не стирает: строка остаётся в БД."""
    assert api.delete(f'{PRODUCTS}{cake.id}/').status_code == 204
    cake.refresh_from_db()
    assert cake.is_deleted is True
    assert cake.deleted_at is not None
    assert FinalProduct.objects.filter(pk=cake.pk).exists()


def test_deleted_product_hidden_from_lists(api, cake):
    api.delete(f'{PRODUCTS}{cake.id}/')
    assert api.get(PRODUCTS).json() == []
    assert api.get(STOCK).json()['products'] == []


def test_deleted_raw_hidden_but_recipe_survives(api, flour, cake):
    """Сырьё скрыто из справочника, но техкарта продолжает считаться."""
    api.delete(f'{RAW}{flour.id}/')
    assert api.get(RAW).json() == []
    cake.refresh_from_db()
    assert cake.components.count() == 1
    from apps.techcards import costing
    assert costing.product_cost(cake) == pytest.approx(12.0)


def test_live_manager_filters(active_shop, cake):
    cake.soft_delete()
    assert FinalProduct.objects.filter(shop=active_shop).count() == 1      # всё
    assert FinalProduct.objects.filter(shop=active_shop).live().count() == 0


def test_restore(cake):
    cake.soft_delete()
    cake.restore()
    cake.refresh_from_db()
    assert cake.is_deleted is False and cake.deleted_at is None


# ── История склада защищена ───────────────────────────────

def test_delete_does_not_touch_stock_history(api, active_shop, flour, cake):
    """
    Главное: удаление позиции не стирает движения склада.
    До правки StockMovement был на CASCADE и остатки менялись задним числом.
    """
    services.receive_raw(active_shop, flour, 10)
    services.run_production(active_shop, cake, 5)
    before = StockMovement.objects.filter(shop=active_shop).count()

    api.delete(f'{PRODUCTS}{cake.id}/')
    api.delete(f'{RAW}{flour.id}/')

    assert StockMovement.objects.filter(shop=active_shop).count() == before
    # баланс по истории не поехал
    assert services.raw_balances(active_shop)[flour.id] == pytest.approx(10_000 - 1_000)
    assert services.product_balances(active_shop)[cake.id] == 5


def test_delete_with_documents_returns_204_not_500(api, active_shop, flour, cake):
    """Раньше это падало 500 из-за ProtectedError на ProductionRun."""
    services.receive_raw(active_shop, flour, 10)
    services.run_production(active_shop, cake, 1)
    assert api.delete(f'{PRODUCTS}{cake.id}/').status_code == 204


def test_physical_delete_still_protected(active_shop, flour, cake):
    """ORM по-прежнему не даёт снести позицию с документами физически."""
    from django.db.models import ProtectedError
    services.receive_raw(active_shop, flour, 10)
    services.run_production(active_shop, cake, 1)
    with pytest.raises(ProtectedError):
        cake.delete()


def test_reports_still_see_deleted_product(api, active_shop, flour, cake):
    """
    Менеджер по умолчанию отдаёт всё: документ прошлого периода обязан
    находить свой товар, иначе себестоимость в отчёте поехала бы.
    """
    services.receive_raw(active_shop, flour, 10)
    services.run_production(active_shop, cake, 2)
    cake.soft_delete()
    hist = api.get('/api/tech-cards/production/history/').json()
    assert hist[0]['productName'] == 'Кекс'
