from django.db import migrations, models


def mark_existing_as_imported(apps, schema_editor):
    """
    Все операции, существовавшие до появления флага, пришли из import_balday —
    ручного ввода тогда ещё не было. Без этого бэкфилла повторный импорт
    посчитал бы их ручными, не удалил и создал бы дубли.
    """
    Operation = apps.get_model('techcards', 'Operation')
    Operation.objects.update(is_imported=True)


class Migration(migrations.Migration):

    dependencies = [
        ('techcards', '0005_operationtype_is_legacy'),
    ]

    operations = [
        migrations.AddField(
            model_name='operation',
            name='is_imported',
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(mark_existing_as_imported, migrations.RunPython.noop),
    ]
