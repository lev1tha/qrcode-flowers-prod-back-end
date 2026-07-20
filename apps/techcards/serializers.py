"""
Сериализаторы техкарт. Поля в camelCase — 1:1 со схемой фронта
(src/utils/costing.js работает с purchasePrice / batchOutput / markupPercent).

Вложенные рецептуры (ingredients / composition) пишутся стратегией
«удалить и пересоздать» — рецепт правится целиком одной формой.
"""
from django.db import transaction
from rest_framework import serializers

from .models import (
    RawIngredient, SemiFinished, SemiIngredient, FinalProduct,
    ProductComponent, ProductionRun, Invoice, InvoiceLine, Disposal, Department,
    Operation, OperationType,
)


class RawIngredientSerializer(serializers.ModelSerializer):
    purchaseVolume = serializers.FloatField(source='purchase_volume', min_value=0)
    purchasePrice  = serializers.FloatField(source='purchase_price',  min_value=0)

    class Meta:
        model  = RawIngredient
        fields = ['id', 'name', 'unit', 'purchaseVolume', 'purchasePrice']


# ── Полуфабрикаты ─────────────────────────────────────────

class SemiIngredientSerializer(serializers.Serializer):
    ingredientId = serializers.IntegerField()
    quantity     = serializers.FloatField(min_value=0)


class SemiFinishedSerializer(serializers.ModelSerializer):
    batchOutput = serializers.FloatField(source='batch_output', min_value=0)
    # write_only: на чтение список собирается вручную в to_representation
    ingredients = SemiIngredientSerializer(many=True, write_only=True)

    class Meta:
        model  = SemiFinished
        fields = ['id', 'name', 'batchOutput', 'ingredients']

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data['ingredients'] = [
            {'ingredientId': row.ingredient_id, 'quantity': row.quantity}
            for row in instance.ingredients.all()
        ]
        return data

    def validate_ingredients(self, items):
        if not items:
            raise serializers.ValidationError('Укажите хотя бы один ингредиент')
        shop = self.context['request'].user.shop
        ids  = [i['ingredientId'] for i in items]
        found = set(RawIngredient.objects.filter(shop=shop, id__in=ids)
                    .values_list('id', flat=True))
        missing = [i for i in ids if i not in found]
        if missing:
            raise serializers.ValidationError(f'Сырьё не найдено: {missing}')
        return items

    def _write_rows(self, semi, items):
        semi.ingredients.all().delete()
        SemiIngredient.objects.bulk_create([
            SemiIngredient(semi=semi, ingredient_id=i['ingredientId'], quantity=i['quantity'])
            for i in items
        ])

    @transaction.atomic
    def create(self, validated):
        items = validated.pop('ingredients')
        semi  = SemiFinished.objects.create(**validated)
        self._write_rows(semi, items)
        return semi

    @transaction.atomic
    def update(self, instance, validated):
        items = validated.pop('ingredients', None)
        for k, v in validated.items():
            setattr(instance, k, v)
        instance.save()
        if items is not None:
            self._write_rows(instance, items)
        return instance


# ── Готовые десерты ───────────────────────────────────────

class ProductComponentSerializer(serializers.Serializer):
    type     = serializers.ChoiceField(choices=['raw', 'semi'])
    id       = serializers.IntegerField()
    quantity = serializers.FloatField(min_value=0)


class FinalProductSerializer(serializers.ModelSerializer):
    markupPercent = serializers.FloatField(source='markup_percent', min_value=0)
    retailPrice   = serializers.FloatField(source='retail_price', min_value=0,
                                           allow_null=True, required=False)
    # write_only: на чтение список собирается вручную в to_representation
    composition   = ProductComponentSerializer(many=True, write_only=True)

    class Meta:
        model  = FinalProduct
        fields = ['id', 'name', 'markupPercent', 'retailPrice', 'composition']

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data['composition'] = [
            {
                'type': 'raw' if row.raw_id else 'semi',
                'id':   row.raw_id or row.semi_id,
                'quantity': row.quantity,
            }
            for row in instance.components.all()
        ]
        return data

    def validate_composition(self, items):
        if not items:
            raise serializers.ValidationError('Укажите хотя бы один компонент')
        shop = self.context['request'].user.shop
        raw_ids  = [i['id'] for i in items if i['type'] == 'raw']
        semi_ids = [i['id'] for i in items if i['type'] == 'semi']
        raw_found  = set(RawIngredient.objects.filter(shop=shop, id__in=raw_ids)
                         .values_list('id', flat=True))
        semi_found = set(SemiFinished.objects.filter(shop=shop, id__in=semi_ids)
                         .values_list('id', flat=True))
        missing = ([i for i in raw_ids if i not in raw_found] +
                   [i for i in semi_ids if i not in semi_found])
        if missing:
            raise serializers.ValidationError(f'Компоненты не найдены: {missing}')
        return items

    def _write_rows(self, product, items):
        product.components.all().delete()
        ProductComponent.objects.bulk_create([
            ProductComponent(
                product=product,
                raw_id=i['id']  if i['type'] == 'raw'  else None,
                semi_id=i['id'] if i['type'] == 'semi' else None,
                quantity=i['quantity'],
            )
            for i in items
        ])

    @transaction.atomic
    def create(self, validated):
        items   = validated.pop('composition')
        product = FinalProduct.objects.create(**validated)
        self._write_rows(product, items)
        return product

    @transaction.atomic
    def update(self, instance, validated):
        items = validated.pop('composition', None)
        for k, v in validated.items():
            setattr(instance, k, v)
        instance.save()
        if items is not None:
            self._write_rows(instance, items)
        return instance


# ── Склад и производство ──────────────────────────────────

class ProductionRunSerializer(serializers.ModelSerializer):
    productId   = serializers.IntegerField(source='product_id', read_only=True)
    productName = serializers.CharField(source='product.name',  read_only=True)
    unitCost    = serializers.FloatField(source='unit_cost',    read_only=True)
    totalCost   = serializers.FloatField(source='total_cost',   read_only=True)
    createdAt   = serializers.DateTimeField(source='created_at', read_only=True)

    class Meta:
        model  = ProductionRun
        fields = ['id', 'productId', 'productName', 'quantity',
                  'unitCost', 'totalCost', 'createdAt']


class ReceiptSerializer(serializers.Serializer):
    """Приход сырья. unit не обязателен — по умолчанию закупочная единица позиции."""
    raw_id   = serializers.IntegerField()
    quantity = serializers.FloatField(min_value=0)
    unit     = serializers.ChoiceField(
        choices=[u[0] for u in RawIngredient.UNITS], required=False, allow_null=True)
    note     = serializers.CharField(max_length=200, required=False, allow_blank=True)


class RunProductionSerializer(serializers.Serializer):
    product_id = serializers.IntegerField()
    quantity   = serializers.IntegerField(min_value=1)


# ── Накладные ─────────────────────────────────────────────

class InvoiceLineSerializer(serializers.ModelSerializer):
    productId   = serializers.IntegerField(source='product_id', read_only=True)
    productName = serializers.CharField(source='product.name',  read_only=True)
    unitCost    = serializers.FloatField(source='unit_cost',    read_only=True)
    sellPrice   = serializers.FloatField(source='sell_price',   read_only=True)
    costTotal   = serializers.FloatField(source='cost_total',   read_only=True)
    lineTotal   = serializers.FloatField(source='line_total',   read_only=True)
    margin      = serializers.FloatField(read_only=True)

    class Meta:
        model  = InvoiceLine
        fields = ['id', 'productId', 'productName', 'quantity',
                  'unitCost', 'sellPrice', 'costTotal', 'lineTotal', 'margin']


class InvoiceSerializer(serializers.ModelSerializer):
    """Проведённая накладная. Итоги считаются из строк, а не хранятся."""
    fromDepartment      = serializers.CharField(source='from_department', read_only=True)
    fromDepartmentLabel = serializers.CharField(source='get_from_department_display', read_only=True)
    toClient            = serializers.CharField(source='to_client',     read_only=True)
    costTotal           = serializers.FloatField(source='cost_total',   read_only=True)
    revenueTotal        = serializers.FloatField(source='revenue_total', read_only=True)
    marginTotal         = serializers.FloatField(source='margin_total', read_only=True)
    lines               = InvoiceLineSerializer(many=True, read_only=True)

    class Meta:
        model  = Invoice
        fields = ['id', 'number', 'date', 'fromDepartment', 'fromDepartmentLabel',
                  'toClient', 'costTotal', 'revenueTotal', 'marginTotal', 'lines']


class InvoiceLineInputSerializer(serializers.Serializer):
    """Строка на входе. Себестоимость НЕ принимаем — её ставит сервер."""
    product_id = serializers.IntegerField()
    quantity   = serializers.FloatField(min_value=0)
    sell_price = serializers.FloatField(min_value=0)


class InvoiceCreateSerializer(serializers.Serializer):
    date            = serializers.DateField()
    from_department = serializers.ChoiceField(choices=Department.choices)
    to_client       = serializers.CharField(max_length=200)
    lines           = InvoiceLineInputSerializer(many=True, allow_empty=False)


# ── Списание ──────────────────────────────────────────────

class DisposalSerializer(serializers.ModelSerializer):
    itemName    = serializers.SerializerMethodField()
    itemType    = serializers.SerializerMethodField()
    unitLabel   = serializers.SerializerMethodField()
    unitCost    = serializers.FloatField(source='unit_cost',   read_only=True)
    lossAmount  = serializers.FloatField(source='loss_amount', read_only=True)
    reasonLabel = serializers.CharField(source='get_reason_display', read_only=True)
    createdAt   = serializers.DateTimeField(source='created_at', read_only=True)

    class Meta:
        model  = Disposal
        fields = ['id', 'itemType', 'itemName', 'quantity', 'unitLabel',
                  'unitCost', 'lossAmount', 'reason', 'reasonLabel', 'createdAt']

    def get_itemName(self, obj):
        return (obj.raw or obj.product).name

    def get_itemType(self, obj):
        return 'raw' if obj.raw_id else 'product'

    def get_unitLabel(self, obj):
        from . import costing
        return costing.BASE_UNITS.get(obj.raw.unit, '') if obj.raw_id else 'шт'


class DisposalCreateSerializer(serializers.Serializer):
    item_type = serializers.ChoiceField(choices=['raw', 'product'])
    item_id   = serializers.IntegerField()
    quantity  = serializers.FloatField(min_value=0)
    reason    = serializers.ChoiceField(choices=[r[0] for r in Disposal.REASONS])


# ── Финансовая отчётность ─────────────────────────────────

class OperationTypeSerializer(serializers.ModelSerializer):
    pnlArticle  = serializers.CharField(source='pnl_article', read_only=True)
    cfArticle   = serializers.CharField(source='cf_article',  read_only=True)
    cfSection   = serializers.CharField(source='cf_section',  read_only=True)
    affectsPnl  = serializers.BooleanField(source='affects_pnl',  read_only=True)
    affectsCash = serializers.BooleanField(source='affects_cash', read_only=True)

    class Meta:
        model  = OperationType
        fields = ['id', 'name', 'flow', 'pnlArticle', 'cfArticle',
                  'cfSection', 'affectsPnl', 'affectsCash', 'is_legacy']


class OperationSerializer(serializers.ModelSerializer):
    typeId     = serializers.IntegerField(source='op_type_id',   read_only=True)
    typeName   = serializers.CharField(source='op_type.name',    read_only=True)
    pnlArticle = serializers.CharField(source='op_type.pnl_article', read_only=True)
    cfArticle  = serializers.CharField(source='op_type.cf_article',  read_only=True)
    flow       = serializers.CharField(source='op_type.flow',    read_only=True)
    receivable = serializers.FloatField(read_only=True)

    class Meta:
        model  = Operation
        fields = ['id', 'date', 'typeId', 'typeName', 'flow', 'pnlArticle',
                  'cfArticle', 'counterparty', 'description',
                  'accrual', 'cash', 'receivable', 'method']


class OperationCreateSerializer(serializers.Serializer):
    date         = serializers.DateField()
    op_type_id   = serializers.IntegerField()
    counterparty = serializers.CharField(max_length=200, required=False, allow_blank=True)
    description  = serializers.CharField(max_length=300, required=False, allow_blank=True)
    accrual      = serializers.FloatField()
    cash         = serializers.FloatField()
    method       = serializers.CharField(max_length=50, required=False, allow_blank=True)
