from django.contrib import admin
from .models import Card

@admin.register(Card)
class CardAdmin(admin.ModelAdmin):
    list_display  = ['id', 'shop', 'text', 'background_type', 'created_at']
    list_filter   = ['background_type', 'shop']
    search_fields = ['text']
    readonly_fields = ['uuid', 'created_at']
