from django.urls import path

from .views import (
    TechCardOverview,
    RawListCreateView, RawDetailView,
    SemiListCreateView, SemiDetailView,
    ProductListCreateView, ProductDetailView,
)

urlpatterns = [
    path('',                    TechCardOverview.as_view()),
    path('raw/',                RawListCreateView.as_view()),
    path('raw/<int:pk>/',       RawDetailView.as_view()),
    path('semi/',               SemiListCreateView.as_view()),
    path('semi/<int:pk>/',      SemiDetailView.as_view()),
    path('products/',           ProductListCreateView.as_view()),
    path('products/<int:pk>/',  ProductDetailView.as_view()),
]
