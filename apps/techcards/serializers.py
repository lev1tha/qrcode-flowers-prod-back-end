"""
Сериализаторы техкарт. Поля в camelCase — 1:1 со схемой фронта
(src/utils/costing.js работает с purchasePrice / batchOutput / markupPercent).

Вложенные рецептуры (ingredients / composition) пишутся стратегией
«удалить и пересоздать» — рецепт правится целиком одной формой.
"""
from django.db import transaction
from rest_framework import serializers

from .models import RawIngredient, SemiFinished, SemiIngredient, FinalProduct, ProductComponent


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
