from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User, Shop

@admin.register(Shop)
class ShopAdmin(admin.ModelAdmin):
    list_display  = ['name', 'owner', 'city', 'active', 'subscription_end', 'is_master']
    list_filter   = ['active', 'is_master']
    search_fields = ['name', 'owner']

@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """
    Наследуемся от BaseUserAdmin ради корректной работы с паролем:
    форма добавления хеширует его (password1/password2), а форма
    редактирования показывает хеш только для чтения.

    ВАЖНО: fieldsets и add_fieldsets задаём явно и НЕ ставим None.
    BaseUserAdmin.get_fieldsets() при добавлении возвращает add_fieldsets,
    и на None админка падала с TypeError → 500. Одного списка `fields`
    здесь мало: форма добавления его не использует.
    """
    list_display  = ['username', 'shop', 'role', 'is_tech_admin', 'is_active']
    list_filter   = ['role', 'is_tech_admin', 'is_active']
    search_fields = ['username']
    ordering      = ['username']

    fieldsets = (
        (None,             {'fields': ('username', 'password')}),
        ('Магазин и роль', {'fields': ('shop', 'role', 'is_tech_admin')}),
        ('Доступ',         {'fields': ('is_active', 'is_staff', 'is_superuser')}),
    )

    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'password1', 'password2',
                       'shop', 'role', 'is_tech_admin', 'is_active', 'is_staff'),
        }),
    )

    # Роль tech_admin сама включает is_tech_admin (User.save), поэтому руками
    # флаг нужен только чтобы выдать доступ менеджеру, не меняя ему роль.
    filter_horizontal = ()
