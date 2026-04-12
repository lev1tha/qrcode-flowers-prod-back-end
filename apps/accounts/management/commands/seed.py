"""
python manage.py seed

Создаёт:
  - Мастер-магазин (is_master=True, подписка вечная)
  - Суперадмин юзер для входа в Django admin
  - Демо-магазин с кассиром для тестирования
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta


class Command(BaseCommand):
    help = 'Создаёт начальные данные'

    def handle(self, *args, **kwargs):
        from apps.accounts.models import Shop, User

        # ── Мастер-магазин (твой, всегда активен) ─────────
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

            # Кассир для мастер-магазина
            if not User.objects.filter(username='master').exists():
                User.objects.create_user(
                    username='master',
                    password='master123',
                    shop=master,
                    role='admin',
                    is_staff=True,
                    is_superuser=True,
                )
                self.stdout.write(self.style.SUCCESS('✓ Мастер-пользователь: master / master123'))
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

            # Кассир для демо-магазина
            if not User.objects.filter(username='cashier1').exists():
                User.objects.create_user(
                    username='cashier1',
                    password='cashier123',
                    shop=demo,
                    role='cashier',
                )
                self.stdout.write(self.style.SUCCESS('✓ Демо-кассир: cashier1 / cashier123'))
        else:
            self.stdout.write('· Демо-магазин уже существует')

        self.stdout.write('')
        self.stdout.write(self.style.WARNING('Данные для входа:'))
        self.stdout.write('  Кассир мастер-магазина: master / master123')
        self.stdout.write('  Кассир демо-магазина:   cashier1 / cashier123')
        self.stdout.write('  Суперадмин панель:      admin / qrcard2025  (из .env)')
