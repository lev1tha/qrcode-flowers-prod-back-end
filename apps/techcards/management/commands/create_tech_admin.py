"""
python manage.py create_tech_admin

Создаёт (или обновляет) администратора производства для раздела техкарт:
  - магазин (по имени, по умолчанию «Balday») с долгой подпиской;
  - пользователя с ролью tech_admin.

Креды берутся из окружения TECH_ADMIN_LOGIN / TECH_ADMIN_PASSWORD
(fallback — значения для локальной разработки, как в seed.py).
Повторный запуск безопасен: пароль и флаг просто обновятся.
"""
from datetime import timedelta

from decouple import config
from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = 'Создаёт администратора производства (доступ к /api/tech-cards/)'

    def add_arguments(self, parser):
        parser.add_argument('--username', default=config('TECH_ADMIN_LOGIN', default='elmamaev'))
        parser.add_argument('--password', default=config('TECH_ADMIN_PASSWORD', default='mfpro2026'))
        parser.add_argument('--shop', default='Balday',
                            help='Имя магазина (создастся, если нет)')

    def handle(self, *args, **opts):
        from apps.accounts.models import Shop, User

        shop, shop_created = Shop.objects.get_or_create(
            name=opts['shop'],
            defaults={
                'owner': opts['username'],
                'active': True,
                # Тех-админ входит через общий LoginView с проверкой подписки —
                # даём заведомо длинную, чтобы вход не отваливался.
                'subscription_end': timezone.now() + timedelta(days=365 * 20),
            },
        )

        user, user_created = User.objects.get_or_create(
            username=opts['username'],
            defaults={'shop': shop, 'role': User.ROLE_TECH_ADMIN},
        )
        user.shop = user.shop or shop
        user.role = User.ROLE_TECH_ADMIN
        user.set_password(opts['password'])
        user.save()  # save() сам выставит is_tech_admin по роли

        self.stdout.write(self.style.SUCCESS(
            f'{"Создан" if user_created else "Обновлён"} тех-админ «{user.username}» '
            f'(роль {user.role}) → магазин «{user.shop.name}»'
            f'{" (новый)" if shop_created else ""}'
        ))
