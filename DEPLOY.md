# Деплой на чистый VPS (Docker backend + Vite frontend + nginx + TLS)

Один домен: фронт на `/`, API на `/api` (same-origin). Обе A-записи (`@` и `www`)
ведут на сервер; `www` редиректится на корень. На VPS может быть второй проект —
трогаем только **свой** `server`-блок nginx.

```
Интернет ──443──> nginx (host) ──┬─ /            → 127.0.0.1:5173  (Vite dev, systemd)
                                 ├─ /api,/django-admin → 127.0.0.1:8000 (Docker web)
                                 ├─ /static/     → /srv/qrcard/backend/staticfiles/
                                 └─ /media/      → /srv/qrcard/backend/media/
Docker: web (gunicorn) + db (postgres:16, том pgdata)
www.example.com ─301─> example.com
```

Все команды — на сервере (по SSH), от root или через `sudo`.
**Замени `example.com` на свой домен.** Проще всего задать переменную:

```bash
DOMAIN=balday.net
LE_EMAIL=azatbeks0304@gmail.com
```

## 0. Предпосылки
- ОС: Ubuntu 22.04/24.04 или Debian 12.
- DNS: A-записи `@` и `www` → IP сервера (готово).
- Оба репозитория запушены на GitHub.

## 1. Зависимости (Docker, Node, nginx, certbot)
```bash
git clone https://github.com/lev1tha/qrcode-flowers-prod-back-end.git /srv/qrcard/backend
sudo bash /srv/qrcard/backend/deploy/bootstrap.sh
```

## 2. Код фронтенда
```bash
git clone https://github.com/lev1tha/qrcode-flowers-prod.git /srv/qrcard/frontend
```

## 3. Backend (Docker + Postgres)
```bash
cd /srv/qrcard/backend
cp .env.example .env
# отредактируй .env:
#   SECRET_KEY   — python3 -c "import secrets;print(secrets.token_urlsafe(50))"
#   DEBUG=False
#   ALLOWED_HOSTS=$DOMAIN,www.$DOMAIN
#   CSRF_TRUSTED_ORIGINS=https://$DOMAIN,https://www.$DOMAIN
#   CORS_ALLOWED_ORIGINS=https://$DOMAIN,https://www.$DOMAIN
#   POSTGRES_PASSWORD=<надёжный>
#   SUPERADMIN_PASSWORD / SUPERADMIN_TOKEN=<новые, не из репозитория!>
#   RUN_SEED=1   (только на первый запуск)
docker compose up -d --build          # db + web; миграции/collectstatic/seed сами
docker compose exec web python manage.py createsuperuser   # для /django-admin/
# после первого запуска верни RUN_SEED=0 в .env
```

## 4. Frontend (Vite dev через systemd)
```bash
cd /srv/qrcard/frontend
cat > .env.local <<EOF
VITE_API_URL=https://$DOMAIN
VITE_PUBLIC_HOST=$DOMAIN
EOF
npm install                            # нужны devDependencies (Vite)

sudo cp /srv/qrcard/backend/deploy/systemd/qrcard-frontend.service /etc/systemd/system/
# в юните проверь User=, WorkingDirectory=/srv/qrcard/frontend, путь к npm (which npm)
sudo systemctl daemon-reload
sudo systemctl enable --now qrcard-frontend
systemctl status qrcard-frontend       # active; слушает 127.0.0.1:5173
```

## 5. nginx (свой блок, сосед не затрагивается)
```bash
sudo cp /srv/qrcard/backend/deploy/nginx/qrcard.conf /etc/nginx/sites-available/qrcard.conf
sudo sed -i "s/example\.com/$DOMAIN/g" /etc/nginx/sites-available/qrcard.conf
sudo ln -s /etc/nginx/sites-available/qrcard.conf /etc/nginx/sites-enabled/
sudo nginx -t                          # НЕ должен ломать конфиг соседа
sudo systemctl reload nginx
```

## 6. TLS на оба хоста (Let's Encrypt)
```bash
sudo certbot --nginx -d $DOMAIN -d www.$DOMAIN -m $LE_EMAIL --agree-tos --redirect -n
# добавит 443-блоки и редиректы 80→443; www продолжит вести на корень
```

## 7. Проверка
- `curl -I https://$DOMAIN` → 200 (SPA); `curl -I https://www.$DOMAIN` → 301 на корень.
- В браузере: `/login` кассир → создать открытку → скан QR → `/card/<uuid>`.
- `/superadmin/login`; `/django-admin/` (по HTTPS).
- Сосед по VPS работает как раньше (`nginx -t` ок, его блок не тронут).

## Обновление
```bash
cd /srv/qrcard/backend  && git pull && docker compose up -d --build
cd /srv/qrcard/frontend && git pull && npm install && sudo systemctl restart qrcard-frontend
```

> **`npm install` и рестарт пропускать нельзя — сбой будет тихим.**
> Если `git pull` меняет `vite.config.js` (например, добавился плагин), Vite пытается
> перезапуститься сам. При отсутствующей зависимости он пишет в журнал
> `Cannot find package … / server restart failed` и **оставляет работать старый
> процесс со старым конфигом**. Сайт не падает — он отдаёт новые исходники, собранные
> по прежнему конфигу. Так в июле 2026 отвалились Tailwind-стили: страница техкарт
> рендерилась голым HTML, остальные страницы (инлайн-стили) выглядели нормально.
> Проверка после деплоя:
> ```bash
> systemctl status qrcard-frontend                     # время старта = момент деплоя
> journalctl -u qrcard-frontend -n 30 | grep -i "restart failed\|Cannot find"
> ```

## Бэкап БД
```bash
cd /srv/qrcard/backend
docker compose exec db pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" > backup_$(date +%F).sql
```

## Примечания
- Порт 8000 слушает только `127.0.0.1` — наружу закрыт, ходит только nginx.
- Vite dev в проде не оптимизирован (без минификации, отдаёт исходники). Быстрый
  переход на прод-сборку позже: `npm run build` + отдавать `dist/` через nginx
  (`root /srv/qrcard/frontend/dist; try_files $uri /index.html;`) вместо прокси на 5173.
- Секреты из старой истории git считать скомпрометированными — в проде только новые значения.
