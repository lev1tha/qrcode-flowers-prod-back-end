from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny, BasePermission
from rest_framework_simplejwt.tokens import RefreshToken
from django.conf import settings
from django.utils import timezone
from datetime import timedelta
from apps.accounts.models import Shop, User
from apps.accounts.serializers import ShopSerializer, UserSerializer


# ── Superadmin permission ─────────────────────────────────

class IsSuperAdmin(BasePermission):
    """Проверяем специальный заголовок X-SA-Token"""
    def has_permission(self, request, view):
        token = request.META.get('HTTP_X_SA_TOKEN', '')
        return token == getattr(settings, 'SUPERADMIN_TOKEN', 'sa-secret-token')


# ── Auth ──────────────────────────────────────────────────

class SuperAdminLoginView(APIView):
    """POST /api/superadmin/login/"""
    permission_classes = [AllowAny]

    def post(self, request):
        login    = request.data.get('login', '')
        password = request.data.get('password', '')

        if (login    == settings.SUPERADMIN_LOGIN and
                password == settings.SUPERADMIN_PASSWORD):
            # Возвращаем простой токен (хранится в localStorage фронта)
            token = getattr(settings, 'SUPERADMIN_TOKEN', 'sa-secret-token')
            return Response({'token': token, 'login': login})

        return Response(
            {'detail': 'Неверный логин или пароль'},
            status=status.HTTP_401_UNAUTHORIZED
        )


# ── Shops ─────────────────────────────────────────────────

class ShopListCreateView(APIView):
    """GET / POST /api/superadmin/shops/"""
    permission_classes = [IsSuperAdmin]

    def get(self, request):
        shops = Shop.objects.all()
        # Поиск
        q = request.query_params.get('q')
        if q:
            shops = shops.filter(name__icontains=q) | shops.filter(owner__icontains=q)
        # Фильтр по статусу
        f = request.query_params.get('filter')
        now = timezone.now()
        if f == 'active':
            shops = shops.filter(active=True, subscription_end__gt=now)
        elif f == 'expired':
            shops = shops.filter(active=False) | shops.filter(subscription_end__lt=now)
        elif f == 'soon':
            shops = shops.filter(
                active=True,
                subscription_end__gt=now,
                subscription_end__lt=now + timedelta(days=7)
            )

        ser = ShopSerializer(shops, many=True)
        stats = {
            'total':    Shop.objects.count(),
            'active':   Shop.objects.filter(active=True, subscription_end__gt=now).count(),
            'expired':  Shop.objects.filter(active=False).count(),
            'soon':     Shop.objects.filter(active=True, subscription_end__gt=now, subscription_end__lt=now+timedelta(days=7)).count(),
            'total_cards': sum(s.cards_created for s in Shop.objects.all()),
        }
        return Response({'shops': ser.data, 'stats': stats})

    def post(self, request):
        ser = ShopSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        shop = ser.save()
        return Response(ShopSerializer(shop).data, status=201)


class ShopDetailView(APIView):
    """GET / PATCH / DELETE /api/superadmin/shops/{id}/"""
    permission_classes = [IsSuperAdmin]

    def get_shop(self, pk):
        try:
            return Shop.objects.get(pk=pk)
        except Shop.DoesNotExist:
            return None

    def get(self, request, pk):
        shop = self.get_shop(pk)
        if not shop:
            return Response({'detail': 'Не найдено'}, status=404)
        return Response(ShopSerializer(shop).data)

    def patch(self, request, pk):
        shop = self.get_shop(pk)
        if not shop:
            return Response({'detail': 'Не найдено'}, status=404)
        if shop.is_master and 'active' in request.data:
            return Response({'detail': 'Мастер-аккаунт нельзя отключить'}, status=400)
        ser = ShopSerializer(shop, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        ser.save()
        return Response(ser.data)

    def delete(self, request, pk):
        shop = self.get_shop(pk)
        if not shop:
            return Response({'detail': 'Не найдено'}, status=404)
        if shop.is_master:
            return Response({'detail': 'Мастер-аккаунт нельзя удалить'}, status=400)
        shop.delete()
        return Response(status=204)


# ── Users (кассиры) ───────────────────────────────────────

class ShopUsersView(APIView):
    """GET / POST /api/superadmin/shops/{id}/users/"""
    permission_classes = [IsSuperAdmin]

    def get(self, request, pk):
        users = User.objects.filter(shop_id=pk)
        return Response(UserSerializer(users, many=True).data)

    def post(self, request, pk):
        try:
            shop = Shop.objects.get(pk=pk)
        except Shop.DoesNotExist:
            return Response({'detail': 'Магазин не найден'}, status=404)

        username = request.data.get('username')
        password = request.data.get('password')
        role     = request.data.get('role', User.ROLE_CASHIER)

        if not username or not password:
            return Response({'detail': 'username и password обязательны'}, status=400)

        if User.objects.filter(username=username).exists():
            return Response({'detail': 'Пользователь уже существует'}, status=400)

        user = User.objects.create_user(
            username=username,
            password=password,
            shop=shop,
            role=role,
        )
        return Response(UserSerializer(user).data, status=201)


class UserDetailView(APIView):
    """PATCH / DELETE /api/superadmin/users/{id}/"""
    permission_classes = [IsSuperAdmin]

    def patch(self, request, pk):
        try:
            user = User.objects.get(pk=pk)
        except User.DoesNotExist:
            return Response({'detail': 'Не найдено'}, status=404)
        if 'password' in request.data:
            user.set_password(request.data['password'])
        if 'is_active' in request.data:
            user.is_active = request.data['is_active']
        if 'role' in request.data:
            user.role = request.data['role']
        user.save()
        return Response(UserSerializer(user).data)

    def delete(self, request, pk):
        try:
            user = User.objects.get(pk=pk)
        except User.DoesNotExist:
            return Response({'detail': 'Не найдено'}, status=404)
        user.delete()
        return Response(status=204)
