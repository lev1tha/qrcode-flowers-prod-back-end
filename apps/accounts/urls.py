from django.urls import path
from .views import LoginView, MeView, RefreshView

urlpatterns = [
    path('login/',   LoginView.as_view()),
    path('me/',      MeView.as_view()),
    path('refresh/', RefreshView.as_view()),
]
