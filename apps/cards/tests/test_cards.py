"""Открытки: изоляция магазинов, публичный доступ, гейт подписки, загрузка видео."""
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import User
from apps.cards.models import Card

pytestmark = pytest.mark.django_db

CARDS  = '/api/cards/'
UPLOAD = '/api/videos/upload/'


def test_create_requires_auth(api):
    assert api.post(CARDS, {'text': 'hi'}, format='json').status_code == 401


def test_create_card_binds_shop_and_author(auth_api, cashier):
    r = auth_api.post(CARDS, {'text': 'С праздником!', 'background_type': 'stars'}, format='json')
    assert r.status_code == 201
    card = Card.objects.get(uuid=r.json()['uuid'])
    assert card.shop_id == cashier.shop_id
    assert card.created_by_id == cashier.id


def test_list_is_scoped_to_own_shop(auth_api, cashier, other_shop):
    Card.objects.create(text='моя', shop=cashier.shop)
    Card.objects.create(text='чужая', shop=other_shop)
    r = auth_api.get(CARDS)
    assert r.status_code == 200
    texts = [c['text'] for c in r.json()]
    assert 'моя' in texts and 'чужая' not in texts


def test_public_get_by_uuid(api, active_shop):
    card = Card.objects.create(text='публичная', shop=active_shop)
    r = api.get(f'{CARDS}{card.uuid}/')
    assert r.status_code == 200
    assert r.json()['text'] == 'публичная'


def test_delete_only_own_shop(auth_api, cashier, other_shop):
    mine = Card.objects.create(text='моя', shop=cashier.shop)
    theirs = Card.objects.create(text='чужая', shop=other_shop)
    assert auth_api.delete(f'{CARDS}{mine.uuid}/').status_code == 204
    # чужая не видна для удаления → 404
    assert auth_api.delete(f'{CARDS}{theirs.uuid}/').status_code == 404
    assert Card.objects.filter(uuid=theirs.uuid).exists()


def test_create_blocked_when_subscription_expired(api, expired_shop):
    user = User.objects.create_user(username='exp', password='x', shop=expired_shop, role='cashier')
    token = RefreshToken.for_user(user).access_token
    api.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
    r = api.post(CARDS, {'text': 'нельзя'}, format='json')
    assert r.status_code == 403
    assert not Card.objects.exists()


# ── Загрузка видео ────────────────────────────────────────

def test_upload_requires_auth(api):
    assert api.post(UPLOAD, {}, format='multipart').status_code == 401


def test_upload_rejects_bad_extension(auth_api):
    f = SimpleUploadedFile('bad.txt', b'data', content_type='text/plain')
    r = auth_api.post(UPLOAD, {'file': f}, format='multipart')
    assert r.status_code == 400


def test_upload_rejects_too_large(auth_api, monkeypatch):
    monkeypatch.setattr('apps.cards.views.MAX_VIDEO_MB', 0.00001)  # ~10 байт лимит
    f = SimpleUploadedFile('big.mp4', b'x' * 500, content_type='video/mp4')
    r = auth_api.post(UPLOAD, {'file': f}, format='multipart')
    assert r.status_code == 413


def test_upload_ok(auth_api, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    f = SimpleUploadedFile('clip.mp4', b'\x00\x01\x02video', content_type='video/mp4')
    r = auth_api.post(UPLOAD, {'file': f}, format='multipart')
    assert r.status_code == 201
    assert r.json()['video_url'].endswith('.mp4')
