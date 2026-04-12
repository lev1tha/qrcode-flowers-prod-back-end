from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import authenticate
from .serializers import LoginSerializer, UserSerializer
from .models import User


class LoginView(APIView):
    """POST /api/auth/login/ — авторизация кассира"""
    permission_classes = [AllowAny]

    def post(self, request):
        ser = LoginSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        user = authenticate(
            username=ser.validated_data['username'],
            password=ser.validated_data['password'],
        )

        if not user:
            return Response(
                {'detail': 'Неверный логин или пароль'},
                status=status.HTTP_401_UNAUTHORIZED
            )

        if not user.is_active:
            return Response(
                {'detail': 'Аккаунт отключён'},
                status=status.HTTP_403_FORBIDDEN
            )

        # Проверяем подписку магазина
        if user.shop and not user.shop.is_subscription_active:
            return Response(
                {'detail': 'Подписка магазина истекла. Обратитесь к администратору.'},
                status=status.HTTP_403_FORBIDDEN
            )

        refresh = RefreshToken.for_user(user)

        return Response({
            'access':  str(refresh.access_token),
            'refresh': str(refresh),
            'user':    UserSerializer(user).data,
        })


class MeView(APIView):
    """GET /api/auth/me/ — текущий пользователь"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(UserSerializer(request.user).data)


class RefreshView(APIView):
    """POST /api/auth/refresh/ — обновить токен"""
    permission_classes = [AllowAny]

    def post(self, request):
        try:
            refresh = RefreshToken(request.data.get('refresh'))
            return Response({'access': str(refresh.access_token)})
        except Exception:
            return Response(
                {'detail': 'Недействительный токен'},
                status=status.HTTP_401_UNAUTHORIZED
            )
