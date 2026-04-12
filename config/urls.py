from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('django-admin/', admin.site.urls),
    path('api/auth/',       include('apps.accounts.urls')),
    path('api/cards/',      include('apps.cards.urls')),
    path('api/superadmin/', include('apps.superadmin.urls')),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
