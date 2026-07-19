from django.contrib import admin

from .models import RawIngredient, SemiFinished, SemiIngredient, FinalProduct, ProductComponent


class SemiIngredientInline(admin.TabularInline):
    model = SemiIngredient
    extra = 0


class ProductComponentInline(admin.TabularInline):
    model = ProductComponent
    extra = 0


@admin.register(RawIngredient)
class RawIngredientAdmin(admin.ModelAdmin):
    list_display = ['name', 'shop', 'unit', 'purchase_volume', 'purchase_price']
    list_filter  = ['shop', 'unit']


@admin.register(SemiFinished)
class SemiFinishedAdmin(admin.ModelAdmin):
    list_display = ['name', 'shop', 'batch_output']
    list_filter  = ['shop']
    inlines      = [SemiIngredientInline]


@admin.register(FinalProduct)
class FinalProductAdmin(admin.ModelAdmin):
    list_display = ['name', 'shop', 'markup_percent', 'retail_price']
    list_filter  = ['shop']
    inlines      = [ProductComponentInline]
