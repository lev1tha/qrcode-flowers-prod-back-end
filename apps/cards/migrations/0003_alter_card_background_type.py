from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('cards', '0002_alter_card_background_type'),
    ]

    operations = [
        migrations.AlterField(
            model_name='card',
            name='background_type',
            field=models.CharField(choices=[('hearts', 'Сердечки'), ('snow', 'Снегопад'), ('confetti', 'Конфетти'), ('bubbles', 'Пузырьки'), ('stars', 'Звёзды'), ('petals', 'Лепестки'), ('fireworks', 'Салют'), ('balloons', 'Шарики'), ('gold', 'Золото'), ('butterflies', 'Бабочки'), ('lanterns', 'Фонарики'), ('aurora', 'Сияние'), ('autumn', 'Листопад'), ('rain', 'Дождь'), ('bokeh', 'Боке')], default='hearts', max_length=20),
        ),
    ]
