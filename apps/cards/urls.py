from django.urls import path
from .views import CardListCreateView, CardDetailView, QRCodeView

urlpatterns = [
    path('',                    CardListCreateView.as_view()),
    path('<uuid:uuid>/',        CardDetailView.as_view()),
    path('<uuid:uuid>/qr/',     QRCodeView.as_view()),
]
