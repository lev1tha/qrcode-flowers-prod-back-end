"""
API техкарт: /api/tech-cards/

Доступ — только пользователь с ролью tech_admin (администратор
производства); legacy-учётки с флагом is_tech_admin тоже пускаем.
Кассирам и менеджерам магазина раздел закрыт.
Все данные скоупятся по магазину пользователя.
"""
from django.db.models import ProtectedError
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.views import APIView

from apps.accounts.models import User

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


class RoleRequired(BasePermission):
    """
    Ролевой доступ к участку цеха (модель 1С: каждый видит свой участок).

    tech_admin — технолог/финансы — проходит везде: это и есть роль
    «всё вижу». Остальные пускаются только в перечисленные участки,
    поэтому цех не дотянется до финансов даже прямым запросом к API.
    """
    roles = ()
    message = 'Нет доступа: недостаточно прав роли'

    def has_permission(self, request, view):
        u = request.user
        if not (u and u.is_authenticated and u.shop_id):
            return False
        if u.has_tech_access:
            return True
        return u.role in self.roles


class IsTechAdmin(RoleRequired):
    """Только технолог/финансы: техкарты, отчёты, журнал операций, списания."""
    roles = ()
    message = 'Доступ только для администратора производства'


class IsWarehouse(RoleRequired):
    """Складовщик/закупщик: сырьё и приход."""
    roles = (User.ROLE_STOREKEEPER,)


class IsProduction(RoleRequired):
    """Цех: выпуск продукции."""
    roles = (User.ROLE_PRODUCTION,)


class IsSeller(RoleRequired):
    """Продавец: продажи и остатки готовой продукции."""
    roles = (User.ROLE_SELLER,)


class IsWorkshopMember(RoleRequired):
    """Любая роль цеха — для общих справочников (список товаров, склад)."""
    roles = (User.ROLE_STOREKEEPER, User.ROLE_PRODUCTION, User.ROLE_SELLER)


class ShopScopedMixin:
    """Queryset по магазину пользователя + автоподстановка shop при создании."""
    permission_classes = [IsTechAdmin]

    def get_queryset(self):
        qs = self.model.objects.filter(shop=self.request.user.shop)
        # Справочники с мягким удалением: в списках показываем только живые.
        return qs.live() if hasattr(qs, 'live') else qs

    def perform_create(self, serializer):
        serializer.save(shop=self.request.user.shop)


class SoftDeleteMixin:
    """
    DELETE помечает позицию удалённой вместо физического удаления.

    Физическое удаление здесь недопустимо: на справочник ссылаются
    документы (выпуски, накладные, списания) через PROTECT, и запрос
    падал бы 500-й; а движения склада до этой правки уносило CASCADE,
    из-за чего остатки задним числом переставали сходиться.
    """

    def perform_destroy(self, instance):
        try:
            instance.soft_delete()
        except ProtectedError as e:
            # Страховка: если кто-то вернёт физическое удаление, отдаём
            # понятную 400, а не 500 с трейсбеком ORM.
            raise DRFValidationError({'detail':
                'Позицию нельзя удалить: на неё ссылаются документы. '
                f'({e.__class__.__name__})'})


class TechCardOverview(APIView):
    """
    GET /api/tech-cards/ — срез данных для стартовой загрузки страницы.

    Открыт всем ролям цеха, но состав ответа зависит от роли: рецептуры
    и сырьё видит только технолог, остальным приходит лишь список товаров.
    Иначе цех получил бы полный справочник сырья в первом же запросе.
    """
    permission_classes = [IsWorkshopMember]

    def get(self, request):
        shop = request.user.shop
        ctx  = {'request': request}
        if not request.user.has_tech_access:
            products = FinalProduct.objects.filter(shop=shop).live().prefetch_related('components')
            return Response({
                'raw': [], 'semi': [],
                'products': FinalProductSerializer(products, many=True, context=ctx).data,
            })
        return Response({
            'raw':      RawIngredientSerializer(
                            RawIngredient.objects.filter(shop=shop).live(), many=True, context=ctx).data,
            'semi':     SemiFinishedSerializer(
                            SemiFinished.objects.filter(shop=shop)
                            .prefetch_related('ingredients'), many=True, context=ctx).data,
            'products': FinalProductSerializer(
                            FinalProduct.objects.filter(shop=shop).live()
                            .prefetch_related('components'), many=True, context=ctx).data,
        })


# ── Сырьё ─────────────────────────────────────────────────

class RawListCreateView(ShopScopedMixin, generics.ListCreateAPIView):
    """Закуп сырья — складовщик."""
    permission_classes = [IsWarehouse]
    model            = RawIngredient
    serializer_class = RawIngredientSerializer


class RawDetailView(SoftDeleteMixin, ShopScopedMixin, generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsWarehouse]
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
    """
    Список товаров читают все роли цеха: цеху он нужен для формы выпуска,
    продавцу — для накладной. Создавать и править техкарты может только
    технолог, поэтому право зависит от метода.
    """
    model            = FinalProduct
    serializer_class = FinalProductSerializer

    def get_permissions(self):
        cls = IsWorkshopMember if self.request.method in ('GET', 'HEAD') else IsTechAdmin
        return [cls()]

    def get_queryset(self):
        return super().get_queryset().prefetch_related('components')


class ProductDetailView(SoftDeleteMixin, ShopScopedMixin, generics.RetrieveUpdateDestroyAPIView):
    model            = FinalProduct
    serializer_class = FinalProductSerializer

    def get_queryset(self):
        return super().get_queryset().prefetch_related('components')


# ── Склад и производство ──────────────────────────────────

class StockView(APIView):
    """
    GET /api/tech-cards/stock/ — срез склада, урезанный под роль.

    Цех не должен видеть общий остаток сырья (по ТЗ), продавец — тем более.
    Поэтому фильтруем не на фронте, а здесь: иначе данные утекали бы
    в ответе API независимо от того, что рисует интерфейс.
    """
    permission_classes = [IsWorkshopMember]

    def get(self, request):
        u = request.user
        snap = services.stock_snapshot(u.shop)
        if u.has_tech_access:
            return Response(snap)
        if u.role == User.ROLE_STOREKEEPER:
            return Response({'raw': snap['raw'], 'products': []})
        # Цех и продавец: только готовая продукция, без остатков сырья.
        products = [{k: v for k, v in p.items() if k not in ('canProduce', 'bottleneckId')}
                    for p in snap['products']]
        return Response({'raw': [], 'products': products})


class ReceiptView(APIView):
    """POST /api/tech-cards/receipts/ — приход сырья на склад (складовщик)."""
    permission_classes = [IsWarehouse]

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
    """POST /api/tech-cards/production/ — проведение выпуска продукции (цех)."""
    permission_classes = [IsProduction]

    def post(self, request):
        ser = RunProductionSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        shop = request.user.shop
        product = get_object_or_404(
            FinalProduct, pk=ser.validated_data['product_id'], shop=shop)

        run, negatives = services.run_production(
            shop=shop, product=product, quantity=ser.validated_data['quantity'])

        return Response({
            'run':   ProductionRunSerializer(run).data,
            'stock': services.stock_snapshot(shop),
            # Позиции, ушедшие в минус: проведение не блокируем,
            # но цех должен увидеть, чего фактически не хватило.
            'negatives': negatives,
        }, status=201)


class ProductionHistoryView(generics.ListAPIView):
    """GET /api/tech-cards/production/history/ — журнал выпусков (цех)."""
    permission_classes = [IsProduction]
    serializer_class   = ProductionRunSerializer

    def get_queryset(self):
        return (ProductionRun.objects
                .filter(shop=self.request.user.shop)
                .select_related('product'))


# ── Накладные ─────────────────────────────────────────────

class InvoiceListCreateView(APIView):
    """GET / POST /api/tech-cards/invoices/ — архив продаж и проведение (продавец)."""
    permission_classes = [IsSeller]

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
    """GET /api/tech-cards/invoices/{id}/ — состав накладной (продавец)."""
    permission_classes = [IsSeller]

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
