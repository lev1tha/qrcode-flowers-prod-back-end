"""
Техкарты производства: сырьё → полуфабрикаты → готовые десерты.

Все данные привязаны к магазину (shop) — мультитенантность как в cards.
Расчёты себестоимости остаются на фронте (чистые функции costing.js);
бэкенд хранит нормализованные данные рецептур.
"""
from django.db import models


class RawIngredient(models.Model):
    """Базовое сырьё: сахар, молоко, сироп манго…"""
    UNITS = [
        ('кг', 'килограмм'),
        ('л',  'литр'),
        ('гр', 'грамм'),
        ('мл', 'миллилитр'),
        ('шт', 'штука'),
    ]

    shop            = models.ForeignKey('accounts.Shop', on_delete=models.CASCADE,
                                        related_name='raw_ingredients')
    name            = models.CharField(max_length=100)
    unit            = models.CharField(max_length=5, choices=UNITS, default='кг')
    purchase_volume = models.FloatField(help_text='Объём закупа в unit: 50 (кг) = мешок')
    purchase_price  = models.FloatField(help_text='Цена всей партии, сом')
    created_at      = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f'{self.name} ({self.purchase_volume} {self.unit})'


class SemiFinished(models.Model):
    """Полуфабрикат собственного цеха: крем, конфи, бисквит…"""
    shop         = models.ForeignKey('accounts.Shop', on_delete=models.CASCADE,
                                     related_name='semi_finished')
    name         = models.CharField(max_length=100)
    batch_output = models.FloatField(help_text='Выход готового замеса, гр/мл')
    created_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        verbose_name_plural = 'semi finished'

    def __str__(self):
        return self.name


class SemiIngredient(models.Model):
    """Строка рецепта полуфабриката: сырьё + расход в гр/мл/шт."""
    semi       = models.ForeignKey(SemiFinished, on_delete=models.CASCADE,
                                   related_name='ingredients')
    ingredient = models.ForeignKey(RawIngredient, on_delete=models.CASCADE)
    quantity   = models.FloatField(help_text='Расход в базовых единицах (гр/мл/шт)')

    class Meta:
        ordering = ['id']

    def __str__(self):
        return f'{self.semi.name}: {self.ingredient.name} × {self.quantity}'


class FinalProduct(models.Model):
    """Готовый десерт с наценкой и (опционально) ручной ценой."""
    shop           = models.ForeignKey('accounts.Shop', on_delete=models.CASCADE,
                                       related_name='final_products')
    name           = models.CharField(max_length=100)
    markup_percent = models.FloatField(default=50, help_text='Наценка, %')
    # null → розничная цена считается автоматически: себестоимость × (1 + наценка/100)
    retail_price   = models.FloatField(null=True, blank=True,
                                       help_text='Ручная розничная цена, сом (null = авто)')
    created_at     = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return self.name


class ProductComponent(models.Model):
    """
    Строка состава десерта: либо сырьё (raw), либо полуфабрикат (semi).
    Ровно одно из полей raw/semi заполнено — контролируется CheckConstraint.
    """
    product  = models.ForeignKey(FinalProduct, on_delete=models.CASCADE,
                                 related_name='components')
    raw      = models.ForeignKey(RawIngredient, on_delete=models.CASCADE,
                                 null=True, blank=True)
    semi     = models.ForeignKey(SemiFinished, on_delete=models.CASCADE,
                                 null=True, blank=True)
    quantity = models.FloatField(help_text='Гр/мл/шт на 1 десерт')

    class Meta:
        ordering = ['id']
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(raw__isnull=False, semi__isnull=True) |
                    models.Q(raw__isnull=True,  semi__isnull=False)
                ),
                name='component_raw_xor_semi',
            ),
        ]

    def __str__(self):
        item = self.raw or self.semi
        return f'{self.product.name}: {item} × {self.quantity}'
