## serializers.py
from rest_framework import serializers
from .models import Card


class CardSerializer(serializers.ModelSerializer):
    card_url = serializers.ReadOnlyField()

    class Meta:
        model  = Card
        fields = [
            'id', 'uuid', 'text', 'footer_text',
            'background_type', 'video_url', 'video_start', 'video_end',
            'card_url', 'created_at',
        ]
        read_only_fields = ['id', 'uuid', 'created_at']
