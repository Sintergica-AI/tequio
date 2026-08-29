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


class FinanceProfile(ProjectBaseModel):
    """The existence of this row marks a project as a client."""

    default_currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES, default="MXN")
    billing_day = models.PositiveSmallIntegerField(
        default=1, validators=[MinValueValidator(1), MaxValueValidator(28)]
    )
    notes = models.TextField(blank=True, default="")

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


class FinanceAccess(BaseModel):
    """Workspace-level allowlist: members allowed to view/manage finance data.
    Workspace admins have implicit access and are not required to be listed."""

    workspace = models.ForeignKey(
        "db.Workspace", on_delete=models.CASCADE, related_name="finance_access"
    )
    member = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="finance_access"
    )

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
