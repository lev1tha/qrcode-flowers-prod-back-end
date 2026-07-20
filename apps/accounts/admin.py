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
    list_display   = ['username', 'shop', 'role', 'is_tech_admin', 'is_active']
    list_filter    = ['role', 'is_tech_admin', 'is_active']
    search_fields  = ['username']
    fieldsets      = None
    add_fieldsets  = None
    fields         = ['username', 'password', 'shop', 'role',
                      'is_tech_admin', 'is_active', 'is_staff']
    # Роль tech_admin сама включает is_tech_admin (User.save), поэтому руками
    # флаг нужен только чтобы выдать доступ менеджеру, не меняя ему роль.
