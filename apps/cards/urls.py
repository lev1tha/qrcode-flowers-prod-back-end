from django.urls import path
from .views import CardListCreateView, CardDetailView, QRCodeView, VideoUploadView

urlpatterns = [
    path('',                    CardListCreateView.as_view()),
    path('<uuid:uuid>/',        CardDetailView.as_view()),
    path('<uuid:uuid>/qr/',     QRCodeView.as_view()),
    path('../videos/upload/',   VideoUploadView.as_view()),
]
