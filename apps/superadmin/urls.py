from django.urls import path
from .views import (
    SuperAdminLoginView,
    ShopListCreateView, ShopDetailView,
    ShopUsersView, UserDetailView,
)

urlpatterns = [
    path('login/',                  SuperAdminLoginView.as_view()),
    path('shops/',                  ShopListCreateView.as_view()),
    path('shops/<int:pk>/',         ShopDetailView.as_view()),
    path('shops/<int:pk>/users/',   ShopUsersView.as_view()),
    path('users/<int:pk>/',         UserDetailView.as_view()),
]
