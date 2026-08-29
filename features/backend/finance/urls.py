# Sintergica CE extension: finance URL routes. Mounted under /api/ from
# /code/plane/urls.py. (AGPL-3.0-only)

from django.urls import path

from plane.finance.views import (
    ContractDetailEndpoint,
    ContractsEndpoint,
    FinanceAccessDetailEndpoint,
    FinanceAccessEndpoint,
    FinanceDashboardEndpoint,
    FinanceMeEndpoint,
    InvoiceDetailEndpoint,
    InvoicesEndpoint,
    PaymentDetailEndpoint,
    PaymentsEndpoint,
    ProjectFinanceProfileEndpoint,
    ProjectFinanceSummaryEndpoint,
)

urlpatterns = [
    path("workspaces/<str:slug>/finance/me/", FinanceMeEndpoint.as_view(), name="finance-me"),
    path(
        "workspaces/<str:slug>/finance/dashboard/",
        FinanceDashboardEndpoint.as_view(),
        name="finance-dashboard",
    ),
    path(
        "workspaces/<str:slug>/finance/access/",
        FinanceAccessEndpoint.as_view(),
        name="finance-access",
    ),
    path(
        "workspaces/<str:slug>/finance/access/<uuid:pk>/",
        FinanceAccessDetailEndpoint.as_view(),
        name="finance-access-detail",
    ),
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/finance/profile/",
        ProjectFinanceProfileEndpoint.as_view(),
        name="finance-profile",
    ),
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/finance/summary/",
        ProjectFinanceSummaryEndpoint.as_view(),
        name="finance-summary",
    ),
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/finance/contracts/",
        ContractsEndpoint.as_view(),
        name="finance-contracts",
    ),
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/finance/contracts/<uuid:pk>/",
        ContractDetailEndpoint.as_view(),
        name="finance-contract-detail",
    ),
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/finance/invoices/",
        InvoicesEndpoint.as_view(),
        name="finance-invoices",
    ),
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/finance/invoices/<uuid:pk>/",
        InvoiceDetailEndpoint.as_view(),
        name="finance-invoice-detail",
    ),
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/finance/payments/",
        PaymentsEndpoint.as_view(),
        name="finance-payments",
    ),
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/finance/payments/<uuid:pk>/",
        PaymentDetailEndpoint.as_view(),
        name="finance-payment-detail",
    ),
]
