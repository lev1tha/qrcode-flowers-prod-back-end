from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
import uuid


class UserManager(BaseUserManager):
    def create_user(self, username, password=None, **extra):
        if not username:
            raise ValueError('Username обязателен')
        user = self.model(username=username, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, username, password=None, **extra):
        extra.setdefault('is_staff', True)
        extra.setdefault('is_superuser', True)
        return self.create_user(username, password, **extra)


class Shop(models.Model):
    """Цветочный магазин — клиент SaaS"""
    id         = models.AutoField(primary_key=True)
    uuid       = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    name       = models.CharField(max_length=200)
    owner      = models.CharField(max_length=200, blank=True)
    phone      = models.CharField(max_length=50,  blank=True)
    city       = models.CharField(max_length=100, blank=True)
    active     = models.BooleanField(default=True)
    subscription_end = models.DateTimeField(null=True, blank=True)
    plan       = models.CharField(max_length=50, default='standard')
    created_at = models.DateTimeField(auto_now_add=True)

    # Суперадмин (ты) — всегда активен, не зависит от подписки
    is_master  = models.BooleanField(default=False)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.name

    @property
    def is_subscription_active(self):
        """Суперадмин всегда активен. Остальные — проверяем дату."""
        if self.is_master:
            return True
        if not self.active:
            return False
        if not self.subscription_end:
            return False
        from django.utils import timezone
        return self.subscription_end > timezone.now()

    @property
    def cards_created(self):
        return self.cards.count()


class User(AbstractBaseUser, PermissionsMixin):
    """Кассир / сотрудник магазина"""
    ROLE_CASHIER = 'cashier'
    ROLE_ADMIN   = 'admin'     # менеджер магазина
    ROLES = [(ROLE_CASHIER, 'Кассир'), (ROLE_ADMIN, 'Менеджер')]

    username   = models.CharField(max_length=150, unique=True)
    shop       = models.ForeignKey(Shop, on_delete=models.CASCADE,
                                   related_name='users', null=True, blank=True)
    role       = models.CharField(max_length=20, choices=ROLES, default=ROLE_CASHIER)
    # Доступ к техкартам и финансам производства (/api/tech-cards/)
    is_tech_admin = models.BooleanField(default=False)
    is_active  = models.BooleanField(default=True)
    is_staff   = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = UserManager()

    USERNAME_FIELD  = 'username'
    REQUIRED_FIELDS = []

    class Meta:
        ordering = ['username']

    def __str__(self):
        return f'{self.username} ({self.shop})'
