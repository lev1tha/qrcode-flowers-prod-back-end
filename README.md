# QR Открытка — Django Backend

## Быстрый старт

```bash
# 1. Установить зависимости
pip install -r requirements.txt

# 2. Создать .env файл
cp .env.example .env
# отредактировать .env — поменять SECRET_KEY и пароли

# 3. Миграции
python manage.py migrate

# 4. Начальные данные (мастер-магазин + демо кассир)
python manage.py seed

# 5. Запуск
python manage.py runserver
```

Бэкенд будет доступен на `http://localhost:8000`

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

## Аккаунты по умолчанию (после seed)

| Роль | Логин | Пароль |
|------|-------|--------|
| Кассир мастер-магазина | `master` | `master123` |
| Кассир демо-магазина | `cashier1` | `cashier123` |
| Суперадмин панель | `admin` | `qrcard2025` |

---

## Подключение фронтенда

В `qr-card-v5/.env.local`:
```
VITE_API_URL=http://localhost:8000
```

В `src/api/client.js`:
```js
const USE_MOCK = false  // было true
```

---

## Деплой на Railway / Render

```bash
# Переменные окружения на сервере:
SECRET_KEY=длинная-случайная-строка
DEBUG=False
ALLOWED_HOSTS=your-app.railway.app
CORS_ALLOWED_ORIGINS=https://qr-card-snowy.vercel.app
SUPERADMIN_LOGIN=admin
SUPERADMIN_PASSWORD=надёжный-пароль
SUPERADMIN_TOKEN=случайный-токен-32-символа

# Cloudinary — ОБЯЗАТЕЛЬНО для загруженных видео в проде.
# Диск на Railway/Render эфемерный: без Cloudinary файлы исчезнут при редеплое.
# Данные из дашборда Cloudinary → Settings → API Keys.
CLOUDINARY_CLOUD_NAME=твой-cloud-name
CLOUDINARY_API_KEY=твой-api-key
CLOUDINARY_API_SECRET=твой-api-secret
```

> Загруженные видео уходят в Cloudinary (постоянное хранилище + CDN с поддержкой
> Range для iOS). Если переменные не заданы — файлы сохраняются на локальный диск
> (нормально для разработки, но не для прода). YouTube-ссылки работают всегда.
