# Sintergica CE extension: finance URL routes. Mounted under /api/ from
# /code/plane/urls.py. (AGPL-3.0-only)

from django.urls import path

from plane.finance.views import (
    CashSnapshotDetailEndpoint,
    CashSnapshotsEndpoint,
    ContractDetailEndpoint,
    ExpenseDetailEndpoint,
    ExpensesEndpoint,
    FinanceForecastEndpoint,
    FinanceImportCommitEndpoint,
    FinanceImportParseEndpoint,
    FinanceAnalyzeEndpoint,
    FinanceCollectionsEndpoint,
    FinanceCollectionsPaymentEndpoint,
    FinanceAnalysesEndpoint,
    FinanceAnalysisDetailEndpoint,
    ProjectFinanceCsfEndpoint,
    FinanceInsightsEndpoint,
    FinancePnlEndpoint,
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
    path("workspaces/<str:slug>/finance/expenses/", ExpensesEndpoint.as_view(), name="finance-expenses"),
    path(
        "workspaces/<str:slug>/finance/expenses/<uuid:pk>/",
        ExpenseDetailEndpoint.as_view(),
        name="finance-expense-detail",
    ),
    path("workspaces/<str:slug>/finance/cash/", CashSnapshotsEndpoint.as_view(), name="finance-cash"),
    path(
        "workspaces/<str:slug>/finance/cash/<uuid:pk>/",
        CashSnapshotDetailEndpoint.as_view(),
        name="finance-cash-detail",
    ),
    path("workspaces/<str:slug>/finance/pnl/", FinancePnlEndpoint.as_view(), name="finance-pnl"),
    path("workspaces/<str:slug>/finance/forecast/", FinanceForecastEndpoint.as_view(), name="finance-forecast"),
    path("workspaces/<str:slug>/finance/insights/", FinanceInsightsEndpoint.as_view(), name="finance-insights"),
    path(
        "workspaces/<str:slug>/finance/import/parse/",
        FinanceImportParseEndpoint.as_view(),
        name="finance-import-parse",
    ),
    path(
        "workspaces/<str:slug>/finance/import/commit/",
        FinanceImportCommitEndpoint.as_view(),
        name="finance-import-commit",
    ),
    path("workspaces/<str:slug>/finance/analyze/", FinanceAnalyzeEndpoint.as_view(), name="finance-analyze"),
    path(
        "workspaces/<str:slug>/finance/collections/",
        FinanceCollectionsEndpoint.as_view(),
        name="finance-collections",
    ),
    path(
        "workspaces/<str:slug>/finance/collections/<uuid:invoice_id>/payments/",
        FinanceCollectionsPaymentEndpoint.as_view(),
        name="finance-collections-payment",
    ),
    path("workspaces/<str:slug>/finance/analyses/", FinanceAnalysesEndpoint.as_view(), name="finance-analyses"),
    path(
        "workspaces/<str:slug>/finance/analyses/<uuid:pk>/",
        FinanceAnalysisDetailEndpoint.as_view(),
        name="finance-analysis-detail",
    ),
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
        "workspaces/<str:slug>/projects/<uuid:project_id>/finance/profile/csf/",
        ProjectFinanceCsfEndpoint.as_view(),
        name="finance-profile-csf",
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
