from django.contrib import admin
from django.urls import path, re_path, include
from apps.cards.views import VideoUploadView, serve_media

urlpatterns = [
    path('django-admin/', admin.site.urls),
    path('api/auth/',       include('apps.accounts.urls')),
    path('api/cards/',      include('apps.cards.urls')),
    path('api/tech-cards/', include('apps.techcards.urls')),
    path('api/videos/upload/', VideoUploadView.as_view()),
    # Медиа с поддержкой Range (iOS Safari), работает и при DEBUG=False
    re_path(r'^media/(?P<path>.*)$', serve_media),
]
