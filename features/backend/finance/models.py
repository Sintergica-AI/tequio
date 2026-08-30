# Sintergica CE extension: finance models. Each Plane project is treated as a
# client; these tables hold its contracts (retainers and one-offs), expected
# charges (invoices), recorded payments, and the workspace-level allowlist of
# users with finance access. Derived from Plane CE patterns (AGPL-3.0-only).

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from plane.db.models.base import BaseModel
from plane.db.models.project import ProjectBaseModel

CURRENCY_CHOICES = (
    ("MXN", "MXN"),
    ("USD", "USD"),
)


# Distinct, readable colors assigned to clients (auto-picked, user-editable).
CLIENT_COLOR_PALETTE = (
    "#3f76ff", "#f59e0b", "#16a34a", "#dc2626", "#8b5cf6", "#0891b2",
    "#db2777", "#65a30d", "#ea580c", "#6366f1", "#0d9488", "#b91c1c",
)


class FinanceProfile(ProjectBaseModel):
    """The existence of this row marks a project as a client."""

    default_currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES, default="MXN")
    billing_day = models.PositiveSmallIntegerField(
        default=1, validators=[MinValueValidator(1), MaxValueValidator(28)]
    )
    notes = models.TextField(blank=True, default="")
    # fiscal identity (Mexican invoicing data)
    legal_name = models.CharField(max_length=255, blank=True, default="")
    rfc = models.CharField(max_length=13, blank=True, default="")
    tax_regime = models.CharField(max_length=100, blank=True, default="")
    tax_zip = models.CharField(max_length=5, blank=True, default="")
    billing_email = models.CharField(max_length=255, blank=True, default="")
    # display color used to attribute revenue to this client in charts
    color = models.CharField(max_length=7, blank=True, default="")
    # Constancia de Situación Fiscal (PDF stored through FileAsset/MinIO)
    csf_asset = models.ForeignKey(
        "db.FileAsset", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        verbose_name = "Finance Profile"
        verbose_name_plural = "Finance Profiles"
        db_table = "finance_profiles"
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=["project"],
                condition=models.Q(deleted_at__isnull=True),
                name="finance_profile_unique_project",
            )
        ]

    def __str__(self):
        return f"FinanceProfile<{self.project_id}>"


class Contract(ProjectBaseModel):
    """A single engagement with the client: a recurring retainer or a one-off."""

    KIND_CHOICES = (("retainer", "Retainer"), ("one_off", "One-off"))
    CYCLE_CHOICES = (
        ("monthly", "Monthly"),
        ("quarterly", "Quarterly"),
        ("yearly", "Yearly"),
        ("none", "None"),
    )
    STATUS_CHOICES = (
        ("active", "Active"),
        ("completed", "Completed"),
        ("cancelled", "Cancelled"),
    )

    name = models.CharField(max_length=255)
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    # per-period amount for retainers, total for one-offs
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    billing_cycle = models.CharField(max_length=20, choices=CYCLE_CHOICES, default="monthly")
    payment_terms_days = models.PositiveSmallIntegerField(default=15)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")
    description = models.TextField(blank=True, default="")

    class Meta:
        verbose_name = "Contract"
        verbose_name_plural = "Contracts"
        db_table = "finance_contracts"
        ordering = ("-start_date",)

    def __str__(self):
        return f"{self.name} ({self.kind})"


class Invoice(ProjectBaseModel):
    """An expected charge ("cobro"). Auto-generated retainer invoices carry a
    period_key ("YYYY-MM"); manual invoices leave it NULL."""

    STATUS_CHOICES = (
        ("pending", "Pending"),
        ("paid", "Paid"),
        ("cancelled", "Cancelled"),
    )

    contract = models.ForeignKey(
        Contract, on_delete=models.SET_NULL, null=True, blank=True, related_name="invoices"
    )
    concept = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES)
    issue_date = models.DateField()
    due_date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    period_key = models.CharField(max_length=7, null=True, blank=True, db_index=True)

    class Meta:
        verbose_name = "Invoice"
        verbose_name_plural = "Invoices"
        db_table = "finance_invoices"
        ordering = ("-due_date",)
        constraints = [
            models.UniqueConstraint(
                fields=["contract", "period_key"],
                condition=models.Q(period_key__isnull=False, deleted_at__isnull=True),
                name="finance_invoice_unique_contract_period",
            )
        ]

    def __str__(self):
        return f"{self.concept} {self.amount} {self.currency}"


class Payment(ProjectBaseModel):
    """A recorded payment. invoice=NULL means an unapplied advance ("anticipo")
    which still counts toward revenue."""

    METHOD_CHOICES = (
        ("transfer", "Transfer"),
        ("cash", "Cash"),
        ("card", "Card"),
        ("other", "Other"),
    )

    invoice = models.ForeignKey(
        Invoice, on_delete=models.SET_NULL, null=True, blank=True, related_name="payments"
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES)
    paid_at = models.DateField()
    method = models.CharField(max_length=20, choices=METHOD_CHOICES, default="transfer")
    reference = models.CharField(max_length=255, blank=True, default="")
    notes = models.TextField(blank=True, default="")

    class Meta:
        verbose_name = "Payment"
        verbose_name_plural = "Payments"
        db_table = "finance_payments"
        ordering = ("-paid_at",)

    def __str__(self):
        return f"{self.amount} {self.currency} @ {self.paid_at}"


class ExpenseEntry(BaseModel):
    """A monthly expense line ("estado financiero" input). Workspace-level:
    company costs are not tied to a client project."""

    CATEGORY_CHOICES = (
        ("payroll", "Payroll"),
        ("infrastructure", "Infrastructure"),
        ("marketing", "Marketing"),
        ("admin", "Administration"),
        ("taxes", "Taxes"),
        ("other", "Other"),
    )

    workspace = models.ForeignKey(
        "db.Workspace", on_delete=models.CASCADE, related_name="finance_expenses"
    )
    month = models.CharField(max_length=7, db_index=True)  # "YYYY-MM"
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default="other")
    concept = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES, default="MXN")
    notes = models.TextField(blank=True, default="")

    class Meta:
        verbose_name = "Expense Entry"
        verbose_name_plural = "Expense Entries"
        db_table = "finance_expenses"
        ordering = ("-month", "-created_at")

    def __str__(self):
        return f"{self.month} {self.concept} {self.amount} {self.currency}"


class CashSnapshot(BaseModel):
    """Cash balance at a point in time, per currency. The latest snapshot is
    the anchor for runway and cash projections."""

    workspace = models.ForeignKey(
        "db.Workspace", on_delete=models.CASCADE, related_name="finance_cash_snapshots"
    )
    as_of = models.DateField()
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES, default="MXN")
    notes = models.TextField(blank=True, default="")

    class Meta:
        verbose_name = "Cash Snapshot"
        verbose_name_plural = "Cash Snapshots"
        db_table = "finance_cash_snapshots"
        ordering = ("-as_of", "-created_at")

    def __str__(self):
        return f"{self.as_of} {self.amount} {self.currency}"


class FinanceAnalysis(BaseModel):
    """A saved CFO AI analysis. Content is the generated text; the period
    records the date filter active when it was generated (both optional)."""

    workspace = models.ForeignKey(
        "db.Workspace", on_delete=models.CASCADE, related_name="finance_analyses"
    )
    content = models.TextField()
    period_from = models.DateField(null=True, blank=True)
    period_to = models.DateField(null=True, blank=True)

    class Meta:
        verbose_name = "Finance Analysis"
        verbose_name_plural = "Finance Analyses"
        db_table = "finance_analyses"
        ordering = ("-created_at",)

    def __str__(self):
        return f"FinanceAnalysis<{self.workspace_id}, {self.created_at}>"


class FinanceAccess(BaseModel):
    """Workspace-level allowlist: members with a finance role. Workspace admins
    have implicit full access and are not required to be listed.

    Roles: "finance" sees and manages everything; "collections" (cobranza) only
    sees pending charges and records payments against them."""

    ROLE_CHOICES = (("finance", "Finance"), ("collections", "Collections"))

    workspace = models.ForeignKey(
        "db.Workspace", on_delete=models.CASCADE, related_name="finance_access"
    )
    member = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="finance_access"
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default="finance")

    class Meta:
        verbose_name = "Finance Access"
        verbose_name_plural = "Finance Access"
        db_table = "finance_access"
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "member"],
                condition=models.Q(deleted_at__isnull=True),
                name="finance_access_unique_member",
            )
        ]

    def __str__(self):
        return f"FinanceAccess<{self.workspace_id}, {self.member_id}>"
