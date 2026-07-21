"""
Техкарты производства: сырьё → полуфабрикаты → готовые десерты,
плюс складской учёт цеха: приход → производство → остатки.

Все данные привязаны к магазину (shop) — мультитенантность как в cards.
Рецептуры хранятся нормализованно; расчёты дублируются на фронте
(costing.js) для отображения и на бэке (costing.py) для списаний.
"""
from django.db import models


class SoftDeleteQuerySet(models.QuerySet):
    """
    Позиции справочников не удаляем физически: на них ссылаются документы,
    а история обязана остаться правдивой. Помечаем is_deleted и прячем
    из списков через .live().

    Менеджер по умолчанию отдаёт ВСЁ, включая удалённое: иначе документ
    прошлого года перестал бы находить свой товар и себестоимость поехала.
    """

    def live(self):
        return self.filter(is_deleted=False)

    def soft_delete(self):
        from django.utils import timezone
        return self.update(is_deleted=True, deleted_at=timezone.now())


class SoftDeleteMixin(models.Model):
    """Мягкое удаление для справочников (сырьё, товары)."""
    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    objects = SoftDeleteQuerySet.as_manager()

    class Meta:
        abstract = True

    def soft_delete(self):
        from django.utils import timezone
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.save(update_fields=['is_deleted', 'deleted_at'])

    def restore(self):
        self.is_deleted = False
        self.deleted_at = None
        self.save(update_fields=['is_deleted', 'deleted_at'])


class RawIngredient(SoftDeleteMixin):
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


class FinalProduct(SoftDeleteMixin):
    """Готовый десерт с наценкой и (опционально) ручной ценой."""
    shop           = models.ForeignKey('accounts.Shop', on_delete=models.CASCADE,
                                       related_name='final_products')
    name           = models.CharField(max_length=100)
    category       = models.CharField(max_length=100, blank=True,
                                      help_text='Направление: Торты, Кофе, 3D десерты…')
    markup_percent = models.FloatField(default=50, help_text='Наценка, %')
    # null → розничная цена считается автоматически: себестоимость × (1 + наценка/100)
    retail_price   = models.FloatField(null=True, blank=True,
                                       help_text='Ручная розничная цена, сом (null = авто)')
    # Позиции из старой номенклатуры пришли без рецептуры — у них есть только
    # готовая цифра себестоимости. Считать их по составу нечем, поэтому
    # ручная себестоимость используется, когда состав пуст.
    manual_unit_cost = models.FloatField(null=True, blank=True,
                                         help_text='Ручная себестоимость, сом (для позиций без техкарты)')
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


# ── Складской учёт ────────────────────────────────────────────

class ProductionRun(models.Model):
    """
    Запуск производства: выпуск N штук десерта.

    Сам по себе документ ничего не меняет — все изменения остатков
    лежат строками в StockMovement, чтобы остаток нельзя было
    поправить в обход истории.
    """
    shop       = models.ForeignKey('accounts.Shop', on_delete=models.CASCADE,
                                   related_name='production_runs')
    product    = models.ForeignKey(FinalProduct, on_delete=models.PROTECT,
                                   related_name='production_runs')
    quantity   = models.PositiveIntegerField(help_text='Выпущено штук')
    # Себестоимость замораживаем на момент выпуска: техкарту потом
    # отредактируют, а история производства должна остаться правдивой.
    unit_cost  = models.FloatField(help_text='Себестоимость 1 шт на момент выпуска, сом')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.product.name} × {self.quantity}'

    @property
    def total_cost(self):
        return self.unit_cost * self.quantity


class Department(models.TextChoices):
    """Подразделения — отправитель накладной."""
    WORKSHOP = 'workshop', 'Цех'
    SALES    = 'sales',    'Отдел продаж'
    OUTLET   = 'outlet',   'Точка продаж'


class Invoice(models.Model):
    """
    Накладная реализации: отгрузка готовой продукции покупателю.

    Итоги (себестоимость/выручка/маржа) НЕ хранятся полями — они
    выводятся из строк, где цена и себестоимость уже заморожены.
    Так документ не может разойтись сам с собой.
    """
    shop            = models.ForeignKey('accounts.Shop', on_delete=models.CASCADE,
                                        related_name='invoices')
    number          = models.CharField(max_length=20, help_text='Номер вида 2026-0001')
    date            = models.DateField(help_text='Дата документа')
    from_department = models.CharField(max_length=20, choices=Department.choices,
                                       default=Department.WORKSHOP)
    to_client       = models.CharField(max_length=200, help_text='Покупатель')
    # Импорт исторических продаж из Excel: документ участвует в ОПиУ/ОДДС,
    # но склад не трогает — в тот период складского учёта ещё не было,
    # и списание увело бы остатки в глубокий минус.
    is_imported     = models.BooleanField(default=False)
    created_at      = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date', '-id']
        constraints = [
            models.UniqueConstraint(fields=['shop', 'number'], name='invoice_number_per_shop'),
        ]

    def __str__(self):
        return f'{self.number} → {self.to_client}'

    @property
    def cost_total(self):
        return sum(l.cost_total for l in self.lines.all())

    @property
    def revenue_total(self):
        return sum(l.line_total for l in self.lines.all())

    @property
    def margin_total(self):
        return self.revenue_total - self.cost_total


class InvoiceLine(models.Model):
    """
    Строка накладной. unit_cost и sell_price замораживаются при проведении:
    техкарту потом отредактируют, а проведённый документ обязан остаться прежним.
    """
    invoice    = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='lines')
    product    = models.ForeignKey(FinalProduct, on_delete=models.PROTECT,
                                   related_name='invoice_lines')
    quantity   = models.FloatField()
    unit_cost  = models.FloatField(help_text='Себестоимость 1 шт на момент отгрузки, сом')
    sell_price = models.FloatField(help_text='Цена продажи 1 шт, сом')

    class Meta:
        ordering = ['id']

    def __str__(self):
        return f'{self.product.name} × {self.quantity}'

    @property
    def cost_total(self):
        return self.unit_cost * self.quantity

    @property
    def line_total(self):
        return self.sell_price * self.quantity

    @property
    def margin(self):
        return self.line_total - self.cost_total


class Disposal(models.Model):
    """Списание брака/просрочки со склада — сырья либо готовой продукции."""
    REASON_DEFECT  = 'defect'
    REASON_EXPIRED = 'expired'
    REASON_TASTING = 'tasting'
    REASONS = [
        (REASON_DEFECT,  'Брак'),
        (REASON_EXPIRED, 'Просрочка'),
        (REASON_TASTING, 'Тест / дегустация'),
    ]

    shop       = models.ForeignKey('accounts.Shop', on_delete=models.CASCADE,
                                   related_name='disposals')
    raw        = models.ForeignKey(RawIngredient, on_delete=models.PROTECT,
                                   null=True, blank=True, related_name='disposals')
    product    = models.ForeignKey(FinalProduct, on_delete=models.PROTECT,
                                   null=True, blank=True, related_name='disposals')
    quantity   = models.FloatField()
    unit_cost  = models.FloatField(help_text='Себестоимость единицы на момент списания, сом')
    reason     = models.CharField(max_length=20, choices=REASONS)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(raw__isnull=False, product__isnull=True) |
                    models.Q(raw__isnull=True,  product__isnull=False)
                ),
                name='disposal_raw_xor_product',
            ),
        ]

    def __str__(self):
        return f'{self.raw or self.product} × {self.quantity} ({self.get_reason_display()})'

    @property
    def loss_amount(self):
        return self.unit_cost * self.quantity


class StockMovement(models.Model):
    """
    Реестр движений склада. Остаток = сумма quantity по позиции.

    Хранить остаток отдельным полем не стали: счётчик со временем
    разъезжается с историей, а здесь любой остаток восстанавливается
    из документов. quantity знаковое: приход +, расход −.

    Сырьё считается в БАЗОВЫХ единицах (гр/мл/шт), продукция — в штуках.
    """
    KIND_RECEIPT        = 'receipt'          # приход сырья на склад
    KIND_PRODUCTION_OUT = 'production_out'   # сырьё ушло в производство
    KIND_PRODUCTION_IN  = 'production_in'    # готовая продукция оприходована
    KIND_SALE           = 'sale'             # отгрузка по накладной
    KIND_DISPOSAL       = 'disposal'         # списание брака/просрочки
    KINDS = [
        (KIND_RECEIPT,        'Приход сырья'),
        (KIND_PRODUCTION_OUT, 'Расход в производство'),
        (KIND_PRODUCTION_IN,  'Выпуск продукции'),
        (KIND_SALE,           'Отгрузка по накладной'),
        (KIND_DISPOSAL,       'Списание'),
    ]

    shop       = models.ForeignKey('accounts.Shop', on_delete=models.CASCADE,
                                   related_name='stock_movements')
    kind       = models.CharField(max_length=20, choices=KINDS)
    # PROTECT, а не CASCADE: движение склада — первичный документ.
    # При CASCADE удаление позиции справочника тихо стирало бы остатки
    # задним числом, и баланс переставал сходиться с историей.
    raw        = models.ForeignKey(RawIngredient, on_delete=models.PROTECT,
                                   null=True, blank=True, related_name='movements')
    product    = models.ForeignKey(FinalProduct, on_delete=models.PROTECT,
                                   null=True, blank=True, related_name='movements')
    quantity   = models.FloatField(help_text='Знаковое: приход +, расход −')
    unit_cost  = models.FloatField(default=0, help_text='Себестоимость единицы на момент движения, сом')
    run        = models.ForeignKey(ProductionRun, on_delete=models.CASCADE,
                                   null=True, blank=True, related_name='movements')
    invoice    = models.ForeignKey(Invoice, on_delete=models.CASCADE,
                                   null=True, blank=True, related_name='movements')
    disposal   = models.ForeignKey(Disposal, on_delete=models.CASCADE,
                                   null=True, blank=True, related_name='movements')
    note       = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [
            models.Index(fields=['shop', 'created_at']),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(raw__isnull=False, product__isnull=True) |
                    models.Q(raw__isnull=True,  product__isnull=False)
                ),
                name='movement_raw_xor_product',
            ),
        ]

    def __str__(self):
        item = self.raw or self.product
        return f'{self.get_kind_display()}: {item} {self.quantity:+.2f}'


# ── Управленческий учёт: ОПиУ и ОДДС ──────────────────────────

class OperationType(models.Model):
    """
    Справочник видов операций (перенесён из Excel «4. Справочники»).

    Ядро всей отчётности: каждый вид операции заранее знает, в какую
    статью ОПиУ и в какую статью ОДДС он попадает. Поэтому одна введённая
    операция автоматически ложится в оба отчёта — и, что важнее, вид
    «Закуп сырья» осознанно НЕ влияет на ОПиУ (иначе себестоимость
    посчиталась бы дважды: при закупе и при продаже).
    """
    FLOW_IN  = 'in'
    FLOW_OUT = 'out'
    FLOWS = [(FLOW_IN, 'Поступление'), (FLOW_OUT, 'Расход')]

    NO_PNL = 'Не влияет на ОПиУ'
    NO_CF  = 'Не влияет на ОДДС'

    shop        = models.ForeignKey('accounts.Shop', on_delete=models.CASCADE,
                                    related_name='operation_types')
    name        = models.CharField(max_length=100)
    flow        = models.CharField(max_length=3, choices=FLOWS)
    pnl_article = models.CharField(max_length=100, help_text='Статья ОПиУ или «Не влияет на ОПиУ»')
    cf_article  = models.CharField(max_length=100, help_text='Статья ОДДС или «Не влияет на ОДДС»')
    cf_section  = models.CharField(max_length=100, blank=True, help_text='Раздел ОДДС')
    sort_order  = models.PositiveIntegerField(default=0)
    # Виды, которыми заведена ТОЛЬКО историческая выручка из Excel
    # (janvar–апрель продажи вели одной суммой, без разбивки по позициям).
    # В отчётах они участвуют, но из формы новой операции скрыты: сегодня
    # выручку даёт накладная, и ручная строка создала бы двойной учёт.
    is_legacy   = models.BooleanField(
        default=False, help_text='Только для импорта истории, недоступен для ручного ввода')

    class Meta:
        ordering = ['sort_order', 'id']
        constraints = [
            models.UniqueConstraint(fields=['shop', 'name'], name='optype_name_per_shop'),
        ]

    def __str__(self):
        return self.name

    @property
    def affects_pnl(self):
        return self.pnl_article != self.NO_PNL

    @property
    def affects_cash(self):
        return self.cf_article != self.NO_CF


class Operation(models.Model):
    """
    Журнал операций — всё, чего нет в складском контуре: аренда, ФОТ,
    налоги, займы, взносы собственника.

    Выручка и себестоимость сюда НЕ вводятся: они приходят из накладных,
    а брак — из списаний. Иначе получился бы двойной учёт.

    Начисление и факт денег разделены намеренно: ОПиУ считается по
    accrual, ОДДС — по cash. Аренда, начисленная в июне и оплаченная
    в июле, попадёт в разные месяцы разных отчётов — это и есть смысл
    двух отчётов вместо одного.
    """
    shop         = models.ForeignKey('accounts.Shop', on_delete=models.CASCADE,
                                     related_name='operations')
    date         = models.DateField()
    op_type      = models.ForeignKey(OperationType, on_delete=models.PROTECT,
                                     related_name='operations')
    counterparty = models.CharField(max_length=200, blank=True)
    description  = models.CharField(max_length=300, blank=True)
    accrual      = models.FloatField(default=0, help_text='Сумма начисления для ОПиУ, сом')
    cash         = models.FloatField(default=0, help_text='Фактическое движение денег для ОДДС, сом')
    method       = models.CharField(max_length=50, blank=True, help_text='Метод оплаты')
    # Импортированные из Excel строки помечаем, чтобы повторный запуск
    # import_balday пересоздавал только их и не сносил то, что завели руками.
    is_imported  = models.BooleanField(default=False)
    created_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date', '-id']
        indexes = [models.Index(fields=['shop', 'date'])]

    def __str__(self):
        return f'{self.date} {self.op_type.name}: {self.accrual:.2f}'

    @property
    def receivable(self):
        """Дебиторка/кредиторка: начислено, но не прошло деньгами."""
        return self.accrual - self.cash


class FinanceSettings(models.Model):
    """Параметры финмодели цеха (лист «2. Настройки»)."""
    shop          = models.OneToOneField('accounts.Shop', on_delete=models.CASCADE,
                                         related_name='finance_settings')
    tax_rate      = models.FloatField(default=0.04, help_text='Ставка налога/резерва, доля (0.04 = 4 %)')
    opening_cash  = models.FloatField(default=0, help_text='Остаток денег на начало года, сом')
    target_profit = models.FloatField(default=0, help_text='Целевая чистая прибыль в месяц, сом')

    class Meta:
        verbose_name_plural = 'finance settings'

    def __str__(self):
        return f'Финнастройки {self.shop.name}'


class FixedCost(models.Model):
    """Статья постоянных расходов в месяц — для плана и точки безубыточности."""
    shop    = models.ForeignKey('accounts.Shop', on_delete=models.CASCADE,
                                related_name='fixed_costs')
    name    = models.CharField(max_length=100)
    amount  = models.FloatField(default=0, help_text='Сумма в месяц, сом')
    active  = models.BooleanField(default=True)

    class Meta:
        ordering = ['id']

    def __str__(self):
        return f'{self.name}: {self.amount:.2f}'
