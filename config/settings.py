from pathlib import Path
from datetime import timedelta
from decouple import config, Csv

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = config('SECRET_KEY', default='django-insecure-change-me')
DEBUG      = config('DEBUG', default=False, cast=bool)
ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='*', cast=Csv())

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'rest_framework_simplejwt',
    'corsheaders',
    'apps.accounts',
    'apps.cards',
    'apps.superadmin',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [{'BACKEND':'django.template.backends.django.DjangoTemplates','DIRS':[],'APP_DIRS':True,'OPTIONS':{'context_processors':['django.template.context_processors.debug','django.template.context_processors.request','django.contrib.auth.context_processors.auth','django.contrib.messages.context_processors.messages']}}]

WSGI_APPLICATION = 'config.wsgi.application'

# ── PostgreSQL ────────────────────────────────────────────
# HOST=db в docker-compose; для локального запуска — localhost.
DATABASES = {
    'default': {
        'ENGINE':   'django.db.backends.postgresql',
        'NAME':     config('POSTGRES_DB',       default='qrcard'),
        'USER':     config('POSTGRES_USER',     default='qrcard'),
        'PASSWORD': config('POSTGRES_PASSWORD', default=''),
        'HOST':     config('POSTGRES_HOST',     default='db'),
        'PORT':     config('POSTGRES_PORT',     default='5432'),
        'CONN_MAX_AGE': config('DB_CONN_MAX_AGE', default=60, cast=int),
    }
}

AUTH_USER_MODEL = 'accounts.User'
LANGUAGE_CODE = 'ru-ru'
TIME_ZONE     = 'Asia/Bishkek'
USE_I18N = True
USE_TZ   = True

STATIC_URL  = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
MEDIA_URL  = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Django 5.1+/6.0: STATICFILES_STORAGE/DEFAULT_FILE_STORAGE удалены — только STORAGES.
STORAGES = {
    'default':     {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage'},
}

CORS_ALLOWED_ORIGINS = config('CORS_ALLOWED_ORIGINS', default='http://localhost:5173', cast=Csv())
CORS_ALLOW_CREDENTIALS = True
# Кастомный заголовок суперадмина должен быть разрешён для cross-origin (при api-поддомене).
# При single-domain (/api same-origin) CORS не задействуется вовсе.
from corsheaders.defaults import default_headers
CORS_ALLOW_HEADERS = (*default_headers, 'x-sa-token')

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': ('rest_framework_simplejwt.authentication.JWTAuthentication',),
    'DEFAULT_PERMISSION_CLASSES':     ('rest_framework.permissions.IsAuthenticated',),
}

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME':  timedelta(hours=8),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=30),
    'ROTATE_REFRESH_TOKENS':  True,
}

SUPERADMIN_LOGIN    = config('SUPERADMIN_LOGIN',    default='admin')
SUPERADMIN_PASSWORD = config('SUPERADMIN_PASSWORD', default='qrcard2025')
SUPERADMIN_TOKEN    = config('SUPERADMIN_TOKEN',    default='sa-secret-token')

# ── За обратным прокси (nginx терминирует TLS) ────────────
# nginx передаёт X-Forwarded-Proto=https → Django считает запрос защищённым.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
USE_X_FORWARDED_HOST = True
# Домены, которым доверяем для CSRF (Django admin по HTTPS). Пример: https://example.com
CSRF_TRUSTED_ORIGINS = config('CSRF_TRUSTED_ORIGINS', default='', cast=Csv())
# В проде (DEBUG=False) cookies только по HTTPS.
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE    = not DEBUG

# Редирект на HTTPS делает nginx; дублируем на уровне Django для прода (без петли —
# доверяем X-Forwarded-Proto через SECURE_PROXY_SSL_HEADER выше).
SECURE_SSL_REDIRECT = config('SECURE_SSL_REDIRECT', default=not DEBUG, cast=bool)
# HSTS — включать осознанно (сначала убедиться, что весь сайт только по HTTPS).
SECURE_HSTS_SECONDS            = config('SECURE_HSTS_SECONDS', default=0, cast=int)
SECURE_HSTS_INCLUDE_SUBDOMAINS = config('SECURE_HSTS_INCLUDE_SUBDOMAINS', default=False, cast=bool)
SECURE_HSTS_PRELOAD            = config('SECURE_HSTS_PRELOAD', default=False, cast=bool)
