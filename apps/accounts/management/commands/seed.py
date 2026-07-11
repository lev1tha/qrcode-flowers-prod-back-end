"""
python manage.py seed

Создаёт стартовые данные приложения:
  - Мастер-магазин (is_master=True, подписка «вечная»)
  - Мастер-кассир для входа в приложение (роль admin)
  - Демо-магазин с кассиром для тестирования

Пароли берутся из окружения (fallback — старые значения для локальной разработки).
Django-суперпользователь (для /django-admin/) НЕ создаётся здесь во избежание
хардкод-кредов в проде — заведите его отдельно: `python manage.py createsuperuser`.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from decouple import config


class Command(BaseCommand):
    help = 'Создаёт начальные данные'

    def handle(self, *args, **kwargs):
        from apps.accounts.models import Shop, User

        master_password = config('MASTER_PASSWORD', default='master123')
        demo_password   = config('DEMO_PASSWORD',   default='cashier123')

        # ── Мастер-магазин (всегда активен) ───────────────
        master, created = Shop.objects.get_or_create(
            is_master=True,
            defaults={
                'name':             'Мой магазин (мастер)',
                'owner':            'Владелец',
                'active':           True,
                'subscription_end': timezone.now() + timedelta(days=36500),  # 100 лет
            }
        )
        if created:
            self.stdout.write(self.style.SUCCESS(f'✓ Мастер-магазин создан: {master.name}'))

            # Кассир мастер-магазина (обычный пользователь приложения, без прав Django admin)
            if not User.objects.filter(username='master').exists():
                User.objects.create_user(
                    username='master',
                    password=master_password,
                    shop=master,
                    role='admin',
                )
                self.stdout.write(self.style.SUCCESS('✓ Мастер-пользователь: master'))
        else:
            self.stdout.write('· Мастер-магазин уже существует')

        # ── Демо-магазин для тестов ────────────────────────
        demo, created = Shop.objects.get_or_create(
            name='Цветочный рай (демо)',
            defaults={
                'owner':            'Айгуль Бекова',
                'phone':            '+996 700 111 222',
                'city':             'Бишкек',
                'active':           True,
                'subscription_end': timezone.now() + timedelta(days=30),
            }
        )
        if created:
            self.stdout.write(self.style.SUCCESS(f'✓ Демо-магазин создан: {demo.name}'))

            if not User.objects.filter(username='cashier1').exists():
                User.objects.create_user(
                    username='cashier1',
                    password=demo_password,
                    shop=demo,
                    role='cashier',
                )
                self.stdout.write(self.style.SUCCESS('✓ Демо-кассир: cashier1'))
        else:
            self.stdout.write('· Демо-магазин уже существует')

        self.stdout.write('')
        self.stdout.write(self.style.WARNING('Готово. Пароли заданы через MASTER_PASSWORD / DEMO_PASSWORD.'))
        self.stdout.write('Для входа в /django-admin/ создайте суперпользователя: python manage.py createsuperuser')
