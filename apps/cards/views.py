from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.parsers import MultiPartParser
from django.http import FileResponse, StreamingHttpResponse, HttpResponse, Http404
from django.conf import settings
from .models import Card
from .serializers import CardSerializer
import qrcode
import io
import base64
import os
import re
import mimetypes

MAX_VIDEO_MB = 50


class ShopSubscriptionMixin:
    """Проверяем что подписка магазина активна перед записью"""
    def check_subscription(self, request):
        user = request.user
        if not user.shop:
            self.permission_denied(request, message='Магазин не назначен')
        if not user.shop.is_subscription_active:
            self.permission_denied(request, message='Подписка истекла')


class CardListCreateView(ShopSubscriptionMixin, generics.ListCreateAPIView):
    """
    GET  /api/cards/        — список открыток магазина
    POST /api/cards/        — создать открытку
    """
    serializer_class   = CardSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if self.request.user.shop:
            return Card.objects.filter(shop=self.request.user.shop)
        return Card.objects.none()

    def perform_create(self, serializer):
        self.check_subscription(self.request)
        serializer.save(
            shop=self.request.user.shop,
            created_by=self.request.user,
        )


class CardDetailView(generics.RetrieveDestroyAPIView):
    """
    GET    /api/cards/{uuid}/   — открытка по uuid (публичный доступ — для QR)
    DELETE /api/cards/{uuid}/   — удалить (только свой магазин)
    """
    serializer_class   = CardSerializer
    lookup_field       = 'uuid'

    def get_permissions(self):
        if self.request.method == 'GET':
            return [AllowAny()]
        return [IsAuthenticated()]

    def get_queryset(self):
        if self.request.method == 'GET':
            return Card.objects.all()
        if self.request.user.is_authenticated and self.request.user.shop:
            return Card.objects.filter(shop=self.request.user.shop)
        return Card.objects.none()


class QRCodeView(APIView):
    """GET /api/cards/{uuid}/qr/ — QR-код в base64"""
    permission_classes = [AllowAny]

    def get(self, request, uuid):
        try:
            card = Card.objects.get(uuid=uuid)
        except Card.DoesNotExist:
            return Response({'detail': 'Не найдено'}, status=404)

        frontend_url = request.build_absolute_uri(f'/card/{uuid}')

        qr = qrcode.QRCode(version=1, box_size=10, border=4)
        qr.add_data(frontend_url)
        qr.make(fit=True)
        img = qr.make_image(fill_color='black', back_color='white')

        buf = io.BytesIO()
        img.save(buf, format='PNG')
        b64 = base64.b64encode(buf.getvalue()).decode()

        return Response({
            'qr_base64': f'data:image/png;base64,{b64}',
            'url':        frontend_url,
        })


class VideoUploadView(APIView):
    """POST /api/videos/upload/ — загрузить видео"""
    permission_classes = [IsAuthenticated]
    parser_classes     = [MultiPartParser]

    def post(self, request):
        file = request.FILES.get('file')
        if not file:
            return Response({'detail': 'Файл не передан'}, status=400)

        # Сохраняем в media/videos/
        from django.core.files.storage import default_storage

        ext      = os.path.splitext(file.name)[1].lower()
        allowed  = {'.mp4', '.mov', '.webm', '.avi'}
        if ext not in allowed:
            return Response({'detail': f'Формат не поддерживается. Разрешены: {", ".join(allowed)}'}, status=400)

        if file.size > MAX_VIDEO_MB * 1024 * 1024:
            return Response(
                {'detail': f'Файл слишком большой ({file.size / 1048576:.1f} МБ). Максимум {MAX_VIDEO_MB} МБ'},
                status=413,
            )

        # Локальный диск VPS (постоянный). В проде /media/ раздаёт nginx с Range;
        # serve_media остаётся fallback для локальной разработки.
        path = default_storage.save(f'videos/{file.name}', file)
        url  = request.build_absolute_uri(f'{settings.MEDIA_URL}{path}')

        return Response({'video_url': url}, status=201)


# ── Раздача медиа с поддержкой HTTP Range ─────────────────
# iOS Safari не проигрывает <video> без byte-range (206 Partial Content),
# а Django static() отдаёт media только при DEBUG=True. Эта вьюха закрывает оба.
def _range_iter(path, start, length, chunk=8192):
    with open(path, 'rb') as f:
        f.seek(start)
        remaining = length
        while remaining > 0:
            data = f.read(min(chunk, remaining))
            if not data:
                break
            remaining -= len(data)
            yield data


def serve_media(request, path):
    media_root = os.path.realpath(str(settings.MEDIA_ROOT))
    full = os.path.realpath(os.path.join(media_root, path))
    # защита от path traversal (../)
    if not full.startswith(media_root + os.sep) or not os.path.isfile(full):
        raise Http404('Не найдено')

    size = os.path.getsize(full)
    content_type = mimetypes.guess_type(full)[0] or 'application/octet-stream'
    range_header = request.META.get('HTTP_RANGE', '').strip()
    m = re.match(r'bytes=(\d+)-(\d*)', range_header) if range_header else None

    if m:
        start = int(m.group(1))
        end = int(m.group(2)) if m.group(2) else size - 1
        end = min(end, size - 1)
        if start > end or start >= size:
            resp = HttpResponse(status=416)
            resp['Content-Range'] = f'bytes */{size}'
            return resp
        length = end - start + 1
        resp = StreamingHttpResponse(_range_iter(full, start, length), status=206, content_type=content_type)
        resp['Content-Range'] = f'bytes {start}-{end}/{size}'
        resp['Content-Length'] = str(length)
    else:
        resp = FileResponse(open(full, 'rb'), content_type=content_type)
        resp['Content-Length'] = str(size)

    resp['Accept-Ranges'] = 'bytes'
    resp['Cache-Control'] = 'public, max-age=86400'
    return resp
