from django.urls import path

from .views import (
    TechCardOverview,
    RawListCreateView, RawDetailView,
    SemiListCreateView, SemiDetailView,
    ProductListCreateView, ProductDetailView,
    StockView, ReceiptView, RunProductionView, ProductionHistoryView,
    InvoiceListCreateView, InvoiceDetailView, DisposalListCreateView,
    PnLView, CashFlowView, DashboardView, DrilldownView, DailySalesView,
    OperationTypeListView, OperationListCreateView, OperationDetailView,
)

urlpatterns = [
    path('',                    TechCardOverview.as_view()),
    path('raw/',                RawListCreateView.as_view()),
    path('raw/<int:pk>/',       RawDetailView.as_view()),
    path('semi/',               SemiListCreateView.as_view()),
    path('semi/<int:pk>/',      SemiDetailView.as_view()),
    path('products/',           ProductListCreateView.as_view()),
    path('products/<int:pk>/',  ProductDetailView.as_view()),
    # ── склад и производство ──
    path('stock/',                  StockView.as_view()),
    path('receipts/',               ReceiptView.as_view()),
    path('production/',             RunProductionView.as_view()),
    path('production/history/',     ProductionHistoryView.as_view()),
    # ── накладные и списания ──
    path('invoices/',               InvoiceListCreateView.as_view()),
    path('invoices/<int:pk>/',      InvoiceDetailView.as_view()),
    path('disposals/',              DisposalListCreateView.as_view()),
    # ── финансовая отчётность ──
    path('reports/pnl/',            PnLView.as_view()),
    path('reports/cashflow/',       CashFlowView.as_view()),
    path('reports/dashboard/',      DashboardView.as_view()),
    path('reports/drilldown/',      DrilldownView.as_view()),
    path('reports/daily/',          DailySalesView.as_view()),
    path('operation-types/',        OperationTypeListView.as_view()),
    path('operations/',             OperationListCreateView.as_view()),
    path('operations/<int:pk>/',    OperationDetailView.as_view()),
]
