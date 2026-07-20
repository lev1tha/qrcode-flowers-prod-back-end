"""
API техкарт: /api/tech-cards/

Доступ — только пользователь с ролью tech_admin (администратор
производства); legacy-учётки с флагом is_tech_admin тоже пускаем.
Кассирам и менеджерам магазина раздел закрыт.
Все данные скоупятся по магазину пользователя.
"""
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from . import reports, services
from .models import (
    RawIngredient, SemiFinished, FinalProduct, ProductionRun,
    Invoice, Disposal, Operation, OperationType,
)
from .serializers import (
    RawIngredientSerializer, SemiFinishedSerializer, FinalProductSerializer,
    ProductionRunSerializer, ReceiptSerializer, RunProductionSerializer,
    InvoiceSerializer, InvoiceCreateSerializer,
    DisposalSerializer, DisposalCreateSerializer,
    OperationSerializer, OperationCreateSerializer, OperationTypeSerializer,
)


class IsTechAdmin(BasePermission):
    """Только администратор производства, привязанный к магазину."""
    message = 'Доступ только для администратора производства'

    def has_permission(self, request, view):
        u = request.user
        return bool(u and u.is_authenticated and u.has_tech_access and u.shop_id)


class ShopScopedMixin:
    """Queryset по магазину пользователя + автоподстановка shop при создании."""
    permission_classes = [IsTechAdmin]

    def get_queryset(self):
        return self.model.objects.filter(shop=self.request.user.shop)

    def perform_create(self, serializer):
        serializer.save(shop=self.request.user.shop)


class TechCardOverview(APIView):
    """GET /api/tech-cards/ — весь срез данных одной загрузкой страницы."""
    permission_classes = [IsTechAdmin]

    def get(self, request):
        shop = request.user.shop
        ctx  = {'request': request}
        return Response({
            'raw':      RawIngredientSerializer(
                            RawIngredient.objects.filter(shop=shop), many=True, context=ctx).data,
            'semi':     SemiFinishedSerializer(
                            SemiFinished.objects.filter(shop=shop)
                            .prefetch_related('ingredients'), many=True, context=ctx).data,
            'products': FinalProductSerializer(
                            FinalProduct.objects.filter(shop=shop)
                            .prefetch_related('components'), many=True, context=ctx).data,
        })


# ── Сырьё ─────────────────────────────────────────────────

class RawListCreateView(ShopScopedMixin, generics.ListCreateAPIView):
    model            = RawIngredient
    serializer_class = RawIngredientSerializer


class RawDetailView(ShopScopedMixin, generics.RetrieveUpdateDestroyAPIView):
    model            = RawIngredient
    serializer_class = RawIngredientSerializer


# ── Полуфабрикаты ─────────────────────────────────────────

class SemiListCreateView(ShopScopedMixin, generics.ListCreateAPIView):
    model            = SemiFinished
    serializer_class = SemiFinishedSerializer

    def get_queryset(self):
        return super().get_queryset().prefetch_related('ingredients')


class SemiDetailView(ShopScopedMixin, generics.RetrieveUpdateDestroyAPIView):
    model            = SemiFinished
    serializer_class = SemiFinishedSerializer

    def get_queryset(self):
        return super().get_queryset().prefetch_related('ingredients')


# ── Готовые десерты ───────────────────────────────────────

class ProductListCreateView(ShopScopedMixin, generics.ListCreateAPIView):
    model            = FinalProduct
    serializer_class = FinalProductSerializer

    def get_queryset(self):
        return super().get_queryset().prefetch_related('components')


class ProductDetailView(ShopScopedMixin, generics.RetrieveUpdateDestroyAPIView):
    model            = FinalProduct
    serializer_class = FinalProductSerializer

    def get_queryset(self):
        return super().get_queryset().prefetch_related('components')


# ── Склад и производство ──────────────────────────────────

class StockView(APIView):
    """GET /api/tech-cards/stock/ — остатки сырья, продукции и суточный потенциал."""
    permission_classes = [IsTechAdmin]

    def get(self, request):
        return Response(services.stock_snapshot(request.user.shop))


class ReceiptView(APIView):
    """POST /api/tech-cards/receipts/ — приход сырья на склад."""
    permission_classes = [IsTechAdmin]

    def post(self, request):
        ser = ReceiptSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        shop = request.user.shop
        raw = get_object_or_404(
            RawIngredient, pk=ser.validated_data['raw_id'], shop=shop)

        services.receive_raw(
            shop=shop,
            raw=raw,
            quantity=ser.validated_data['quantity'],
            unit=ser.validated_data.get('unit'),
            note=ser.validated_data.get('note', ''),
        )
        return Response(services.stock_snapshot(shop), status=201)


class RunProductionView(APIView):
    """POST /api/tech-cards/production/ — выпуск партии десерта."""
    permission_classes = [IsTechAdmin]

    def post(self, request):
        ser = RunProductionSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        shop = request.user.shop
        product = get_object_or_404(
            FinalProduct, pk=ser.validated_data['product_id'], shop=shop)

        run = services.run_production(
            shop=shop, product=product, quantity=ser.validated_data['quantity'])

        return Response({
            'run':   ProductionRunSerializer(run).data,
            'stock': services.stock_snapshot(shop),
        }, status=201)


class ProductionHistoryView(generics.ListAPIView):
    """GET /api/tech-cards/production/history/ — журнал выпусков."""
    permission_classes = [IsTechAdmin]
    serializer_class   = ProductionRunSerializer

    def get_queryset(self):
        return (ProductionRun.objects
                .filter(shop=self.request.user.shop)
                .select_related('product'))


# ── Накладные ─────────────────────────────────────────────

class InvoiceListCreateView(APIView):
    """GET / POST /api/tech-cards/invoices/ — архив продаж и проведение."""
    permission_classes = [IsTechAdmin]

    def get(self, request):
        invoices = (Invoice.objects
                    .filter(shop=request.user.shop)
                    .prefetch_related('lines__product'))
        return Response(InvoiceSerializer(invoices, many=True).data)

    def post(self, request):
        ser = InvoiceCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        invoice = services.post_invoice(
            shop=request.user.shop,
            date=data['date'],
            from_department=data['from_department'],
            to_client=data['to_client'],
            lines=data['lines'],
        )
        return Response({
            'invoice': InvoiceSerializer(invoice).data,
            'stock':   services.stock_snapshot(request.user.shop),
        }, status=201)


class InvoiceDetailView(APIView):
    """GET /api/tech-cards/invoices/{id}/ — состав накладной."""
    permission_classes = [IsTechAdmin]

    def get(self, request, pk):
        invoice = get_object_or_404(Invoice, pk=pk, shop=request.user.shop)
        return Response(InvoiceSerializer(invoice).data)


# ── Списание ──────────────────────────────────────────────

class DisposalListCreateView(APIView):
    """GET / POST /api/tech-cards/disposals/ — журнал списаний и списание."""
    permission_classes = [IsTechAdmin]

    def get(self, request):
        qs = (Disposal.objects
              .filter(shop=request.user.shop)
              .select_related('raw', 'product'))
        return Response({
            'disposals': DisposalSerializer(qs, many=True).data,
            'lossTotal': services.disposal_total(request.user.shop),
        })

    def post(self, request):
        ser = DisposalCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        shop = request.user.shop

        kwargs = {}
        if data['item_type'] == 'raw':
            kwargs['raw'] = get_object_or_404(
                RawIngredient, pk=data['item_id'], shop=shop)
        else:
            kwargs['product'] = get_object_or_404(
                FinalProduct, pk=data['item_id'], shop=shop)

        disposal = services.dispose(
            shop=shop, reason=data['reason'], quantity=data['quantity'], **kwargs)

        return Response({
            'disposal': DisposalSerializer(disposal).data,
            'stock':    services.stock_snapshot(shop),
        }, status=201)


# ── Финансовая отчётность ─────────────────────────────────

class PnLView(APIView):
    """GET /api/tech-cards/reports/pnl/?year=2026 — ОПиУ по начислению."""
    permission_classes = [IsTechAdmin]

    def get(self, request):
        year = int(request.query_params.get('year') or timezone.now().year)
        return Response(reports.pnl(request.user.shop, year))


class CashFlowView(APIView):
    """GET /api/tech-cards/reports/cashflow/?year=2026 — ОДДС по факту денег."""
    permission_classes = [IsTechAdmin]

    def get(self, request):
        year = int(request.query_params.get('year') or timezone.now().year)
        return Response(reports.cash_flow(request.user.shop, year))


class DashboardView(APIView):
    """GET /api/tech-cards/reports/dashboard/?year=&month= — сводка и динамика."""
    permission_classes = [IsTechAdmin]

    def get(self, request):
        now = timezone.now()
        year = int(request.query_params.get('year') or now.year)
        month = request.query_params.get('month')
        return Response(reports.dashboard(
            request.user.shop, year, int(month) if month else now.month))


class OperationTypeListView(generics.ListAPIView):
    """GET /api/tech-cards/operation-types/ — справочник для формы операции."""
    permission_classes = [IsTechAdmin]
    serializer_class   = OperationTypeSerializer

    def get_queryset(self):
        # legacy-виды скрыты: ими заведена только история из Excel.
        return OperationType.objects.filter(
            shop=self.request.user.shop, is_legacy=False)


class OperationListCreateView(APIView):
    """GET / POST /api/tech-cards/operations/ — журнал операций."""
    permission_classes = [IsTechAdmin]

    def get(self, request):
        qs = (Operation.objects.filter(shop=request.user.shop)
              .select_related('op_type'))
        year = request.query_params.get('year')
        if year:
            qs = qs.filter(date__year=int(year))
        return Response(OperationSerializer(qs, many=True).data)

    def post(self, request):
        ser = OperationCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        op_type = get_object_or_404(
            OperationType, pk=data['op_type_id'], shop=request.user.shop)

        op = Operation.objects.create(
            shop=request.user.shop, date=data['date'], op_type=op_type,
            counterparty=data.get('counterparty', ''),
            description=data.get('description', ''),
            accrual=data['accrual'], cash=data['cash'],
            method=data.get('method', ''))
        return Response(OperationSerializer(op).data, status=201)


class OperationDetailView(APIView):
    """DELETE /api/tech-cards/operations/{id}/ — удалить строку журнала."""
    permission_classes = [IsTechAdmin]

    def delete(self, request, pk):
        op = get_object_or_404(Operation, pk=pk, shop=request.user.shop)
        op.delete()
        return Response(status=204)


class DrilldownView(APIView):
    """GET /api/tech-cards/reports/drilldown/ — расшифровка ячейки отчёта."""
    permission_classes = [IsTechAdmin]

    def get(self, request):
        q = request.query_params
        try:
            year, month = int(q['year']), int(q['month'])
        except (KeyError, ValueError):
            return Response({'detail': 'Нужны параметры year и month'}, status=400)
        article = q.get('article', '')
        if not article:
            return Response({'detail': 'Нужен параметр article'}, status=400)
        if not 1 <= month <= 12:
            return Response({'detail': 'month должен быть 1–12'}, status=400)

        return Response(reports.drilldown(
            request.user.shop, year, month, article,
            report=q.get('report', 'pnl')))


class DailySalesView(APIView):
    """GET /api/tech-cards/reports/daily/?year=&month= — реализация по суткам."""
    permission_classes = [IsTechAdmin]

    def get(self, request):
        now = timezone.localdate()
        year  = int(request.query_params.get('year')  or now.year)
        month = int(request.query_params.get('month') or now.month)
        if not 1 <= month <= 12:
            return Response({'detail': 'month должен быть 1–12'}, status=400)

        return Response({
            'daily': reports.daily_sales(request.user.shop, year, month),
            'today': reports.today_sales(request.user.shop, now),
        })
