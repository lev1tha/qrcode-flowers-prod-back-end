from rest_framework import serializers
from .models import User, Shop


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)


class UserSerializer(serializers.ModelSerializer):
    # in_workshop: пускать ли в раздел цеха вообще (роль решает, какие вкладки).
    in_workshop = serializers.BooleanField(read_only=True)
    shop_name   = serializers.CharField(source='shop.name',   read_only=True)
    shop_active = serializers.SerializerMethodField()

    class Meta:
        model  = User
        fields = ['id', 'username', 'role', 'shop', 'shop_name', 'shop_active',
                  'is_tech_admin', 'in_workshop']

    def get_shop_active(self, obj):
        if not obj.shop:
            return False
        return obj.shop.is_subscription_active


class ShopSerializer(serializers.ModelSerializer):
    cards_created = serializers.IntegerField(read_only=True)
    is_subscription_active = serializers.BooleanField(read_only=True)

    class Meta:
        model  = Shop
        fields = [
            'id', 'uuid', 'name', 'owner', 'phone', 'city',
            'active', 'subscription_end', 'plan', 'is_master',
            'is_subscription_active', 'cards_created', 'created_at',
        ]
        read_only_fields = ['id', 'uuid', 'created_at', 'is_master']
