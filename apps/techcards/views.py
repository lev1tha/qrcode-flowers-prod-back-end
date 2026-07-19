"""
API техкарт: /api/tech-cards/

Доступ — только пользователь с is_tech_admin=True (администратор
производства). Кассирам и менеджерам магазина раздел закрыт.
Все данные скоупятся по магазину пользователя.
"""
from rest_framework import generics
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import RawIngredient, SemiFinished, FinalProduct
from .serializers import (
    RawIngredientSerializer, SemiFinishedSerializer, FinalProductSerializer,
)


class IsTechAdmin(BasePermission):
    """Только администратор производства, привязанный к магазину."""
    message = 'Доступ только для администратора производства'

    def has_permission(self, request, view):
        u = request.user
        return bool(u and u.is_authenticated and u.is_tech_admin and u.shop_id)


class ShopScopedMixin:
    """Queryset по магазину пользователя + автоподстановка shop при создании."""
    permission_classes = [IsTechAdmin]

    def get_queryset(self):
        return self.model.objects.filter(shop=self.request.user.shop)

    def perform_create(self, serializer):
        serializer.save(shop=self.request.user.shop)


class TechCardOverview(APIView):
    """GET /api/tech-cards/ — весь срез данных одной загрузкой страницы."""
    permission_classes = [IsTechAdmin]

    def get(self, request):
        shop = request.user.shop
        ctx  = {'request': request}
        return Response({
            'raw':      RawIngredientSerializer(
                            RawIngredient.objects.filter(shop=shop), many=True, context=ctx).data,
            'semi':     SemiFinishedSerializer(
                            SemiFinished.objects.filter(shop=shop)
                            .prefetch_related('ingredients'), many=True, context=ctx).data,
            'products': FinalProductSerializer(
                            FinalProduct.objects.filter(shop=shop)
                            .prefetch_related('components'), many=True, context=ctx).data,
        })


# ── Сырьё ─────────────────────────────────────────────────

class RawListCreateView(ShopScopedMixin, generics.ListCreateAPIView):
    model            = RawIngredient
    serializer_class = RawIngredientSerializer


class RawDetailView(ShopScopedMixin, generics.RetrieveUpdateDestroyAPIView):
    model            = RawIngredient
    serializer_class = RawIngredientSerializer


# ── Полуфабрикаты ─────────────────────────────────────────

class SemiListCreateView(ShopScopedMixin, generics.ListCreateAPIView):
    model            = SemiFinished
    serializer_class = SemiFinishedSerializer

    def get_queryset(self):
        return super().get_queryset().prefetch_related('ingredients')


class SemiDetailView(ShopScopedMixin, generics.RetrieveUpdateDestroyAPIView):
    model            = SemiFinished
    serializer_class = SemiFinishedSerializer

    def get_queryset(self):
        return super().get_queryset().prefetch_related('ingredients')


# ── Готовые десерты ───────────────────────────────────────

class ProductListCreateView(ShopScopedMixin, generics.ListCreateAPIView):
    model            = FinalProduct
    serializer_class = FinalProductSerializer

    def get_queryset(self):
        return super().get_queryset().prefetch_related('components')


class ProductDetailView(ShopScopedMixin, generics.RetrieveUpdateDestroyAPIView):
    model            = FinalProduct
    serializer_class = FinalProductSerializer

    def get_queryset(self):
        return super().get_queryset().prefetch_related('components')
