from django.db import models
import uuid


class Card(models.Model):
    """QR-открытка"""
    BACKGROUNDS = [
        ('hearts',    'Сердечки'),
        ('snow',      'Снегопад'),
        ('confetti',  'Конфетти'),
        ('bubbles',   'Пузырьки'),
        ('stars',     'Звёзды'),
        ('petals',    'Лепестки'),
        ('fireworks', 'Салют'),
        ('balloons',  'Шарики'),
        ('gold',      'Золото'),
    ]

    id              = models.AutoField(primary_key=True)
    uuid            = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    shop            = models.ForeignKey(
                          'accounts.Shop',
                          on_delete=models.CASCADE,
                          related_name='cards',
                          null=True, blank=True,
                      )
    created_by      = models.ForeignKey(
                          'accounts.User',
                          on_delete=models.SET_NULL,
                          null=True, blank=True,
                          related_name='created_cards',
                      )
    text            = models.TextField(max_length=250)
    footer_text     = models.CharField(max_length=80, blank=True, default='')
    background_type = models.CharField(max_length=20, choices=BACKGROUNDS, default='hearts')
    video_url       = models.URLField(blank=True, null=True)
    video_start     = models.FloatField(default=0)
    video_end       = models.FloatField(null=True, blank=True)
    created_at      = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'Открытка #{self.id} — {self.text[:40]}'

    @property
    def card_url(self):
        return f'/card/{self.uuid}'
