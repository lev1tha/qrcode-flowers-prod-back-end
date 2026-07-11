# QR Открытка — Django Backend

Стек: **Django 6.0 + DRF + PostgreSQL**, поднимается в **Docker**.

## Быстрый старт (Docker)

```bash
cp .env.example .env      # заполнить SECRET_KEY, POSTGRES_PASSWORD, SUPERADMIN_*, RUN_SEED=1
docker compose up -d --build
# db (postgres:16) + web (gunicorn на 127.0.0.1:8000):
#   entrypoint сам применит миграции, collectstatic и seed (если RUN_SEED=1)
docker compose exec web python manage.py createsuperuser   # для /django-admin/
```

Полный деплой на VPS (nginx + TLS + frontend) — см. **[DEPLOY.md](DEPLOY.md)**.

## Локально без Docker

```bash
python3.13 -m venv .venv && ./.venv/bin/pip install -r requirements-dev.txt
cp .env.example .env       # POSTGRES_HOST=localhost, указать свою локальную БД
./.venv/bin/python manage.py migrate
./.venv/bin/python manage.py seed
./.venv/bin/python manage.py runserver
```

## Тесты

```bash
docker compose run --rm --entrypoint sh web -c "pip install -q pytest pytest-django && pytest"
```

Бэкенд доступен на `http://localhost:8000`

---

## Структура проекта

```
qr-card-backend/
├── config/
│   ├── settings.py     ← настройки
│   └── urls.py         ← роуты
├── apps/
│   ├── accounts/       ← пользователи, магазины, подписки
│   ├── cards/          ← открытки, QR-коды, видео
│   └── superadmin/     ← управление магазинами
└── manage.py
```

---

## API эндпоинты

### Авторизация кассира

| Метод | URL | Описание |
|-------|-----|----------|
| POST | `/api/auth/login/` | Войти (username + password) |
| GET  | `/api/auth/me/`    | Текущий пользователь |
| POST | `/api/auth/refresh/` | Обновить токен |

**POST /api/auth/login/**
```json
{ "username": "cashier1", "password": "cashier123" }
```
Ответ:
```json
{
  "access": "eyJ...",
  "refresh": "eyJ...",
  "user": {
    "id": 1,
    "username": "cashier1",
    "role": "cashier",
    "shop": 2,
    "shop_name": "Цветочный рай",
    "shop_active": true
  }
}
```
Если подписка истекла — 403 с `detail: "Подписка магазина истекла"`

---

### Открытки (требуют Bearer токен)

| Метод | URL | Описание |
|-------|-----|----------|
| GET  | `/api/cards/` | Список открыток своего магазина |
| POST | `/api/cards/` | Создать открытку |
| GET  | `/api/cards/{uuid}/` | Открытка по UUID (публичный) |
| DELETE | `/api/cards/{uuid}/` | Удалить |
| GET  | `/api/cards/{uuid}/qr/` | QR-код в base64 (публичный) |
| POST | `/api/videos/upload/` | Загрузить видео |

**POST /api/cards/**
```json
{
  "text": "С днём рождения! ❤️",
  "footer_text": "сделано с любовью 💕",
  "background_type": "hearts",
  "video_url": "https://cdn.example.com/video.mp4",
  "video_start": 10.0,
  "video_end": 25.0
}
```

**GET /api/cards/{uuid}/qr/**
```json
{
  "qr_base64": "data:image/png;base64,iVBOR...",
  "url": "https://qr-card-snowy.vercel.app/card/uuid-здесь"
}
```

---

### Суперадмин (требуют заголовок X-SA-Token)

| Метод | URL | Описание |
|-------|-----|----------|
| POST | `/api/superadmin/login/` | Войти как суперадмин |
| GET  | `/api/superadmin/shops/` | Список магазинов + статистика |
| POST | `/api/superadmin/shops/` | Создать магазин |
| GET/PATCH/DELETE | `/api/superadmin/shops/{id}/` | Магазин |
| GET/POST | `/api/superadmin/shops/{id}/users/` | Кассиры магазина |
| PATCH/DELETE | `/api/superadmin/users/{id}/` | Кассир |

**POST /api/superadmin/login/**
```json
{ "login": "admin", "password": "qrcard2025" }
```
Ответ: `{ "token": "sa-secret-token", "login": "admin" }`

Все остальные запросы суперадмина: заголовок `X-SA-Token: sa-secret-token`

---

## Аккаунты после seed

Логины кассиров создаёт `seed`, пароли задаются через env (`MASTER_PASSWORD`,
`DEMO_PASSWORD`; дефолты для локалки — `master123` / `cashier123`):

| Роль | Логин | Пароль |
|------|-------|--------|
| Кассир мастер-магазина | `master` | `$MASTER_PASSWORD` |
| Кассир демо-магазина | `cashier1` | `$DEMO_PASSWORD` |
| Панель суперадмина | `$SUPERADMIN_LOGIN` | `$SUPERADMIN_PASSWORD` |

> Django-суперпользователь (`/django-admin/`) намеренно **не** создаётся seed'ом —
> заведите его отдельно: `python manage.py createsuperuser`.

---

## Подключение фронтенда

В `.env.local` фронтенда: `VITE_API_URL` = адрес бэкенда (локально `http://localhost:8000`,
в проде — тот же домен, что и фронт: same-origin `/api`).

---

## Деплой

Видео хранится на **локальном диске** (`/media`, том Docker) и раздаётся nginx с
поддержкой Range для iOS. Cloudinary больше не используется.

Полная инструкция по VPS (Docker backend + Vite frontend + nginx + certbot) —
**[DEPLOY.md](DEPLOY.md)**. Ключевые env: `SECRET_KEY`, `DEBUG=False`,
`ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, `POSTGRES_*`, `SUPERADMIN_*`.
