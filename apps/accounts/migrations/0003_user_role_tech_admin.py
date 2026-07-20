"""
Регистрируем роль tech_admin и переводим на неё существующих
тех-админов, которых заводили по старой схеме (role=admin + is_tech_admin=True).
"""
from django.db import migrations, models


def promote_tech_admins(apps, schema_editor):
    User = apps.get_model('accounts', 'User')
    User.objects.filter(is_tech_admin=True).exclude(role='tech_admin').update(role='tech_admin')


def demote_tech_admins(apps, schema_editor):
    # Откат: возвращаем в менеджеры. Флаг is_tech_admin не трогаем —
    # на старой схеме именно он давал доступ, и он остаётся верным.
    User = apps.get_model('accounts', 'User')
    User.objects.filter(role='tech_admin').update(role='admin')


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0002_user_is_tech_admin'),
    ]

    operations = [
        migrations.AlterField(
            model_name='user',
            name='role',
            field=models.CharField(
                choices=[
                    ('cashier', 'Кассир'),
                    ('admin', 'Менеджер'),
                    ('tech_admin', 'Тех. админ'),
                ],
                default='cashier',
                max_length=20,
            ),
        ),
        migrations.RunPython(promote_tech_admins, demote_tech_admins),
    ]
