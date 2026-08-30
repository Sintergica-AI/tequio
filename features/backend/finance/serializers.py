# Sintergica CE extension: finance serializers. (AGPL-3.0-only)

from decimal import Decimal

from rest_framework import serializers

import re as _re

from plane.finance.models import (
    CashSnapshot,
    Contract,
    ExpenseEntry,
    FinanceAccess,
    FinanceAnalysis,
    FinanceProfile,
    Invoice,
    Payment,
)
from plane.finance.services import invoice_effective_status

RFC_RE = _re.compile(r"^[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}$")
COLOR_RE = _re.compile(r"^#[0-9a-fA-F]{6}$")


class FinanceProfileSerializer(serializers.ModelSerializer):
    csf_name = serializers.SerializerMethodField()

    class Meta:
        model = FinanceProfile
        fields = [
            "id", "project", "workspace", "default_currency", "billing_day", "notes",
            "legal_name", "rfc", "tax_regime", "tax_zip", "billing_email", "color",
            "csf_asset", "csf_name",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "project", "workspace", "csf_asset", "csf_name", "created_at", "updated_at"]

    def get_csf_name(self, obj):
        if obj.csf_asset_id and obj.csf_asset and obj.csf_asset.is_uploaded:
            return (obj.csf_asset.attributes or {}).get("name", "CSF.pdf")
        return None

    def validate_rfc(self, value):
        value = (value or "").strip().upper()
        if value and not RFC_RE.fullmatch(value):
            raise serializers.ValidationError("El RFC no tiene un formato válido.")
        return value

    def validate_color(self, value):
        value = (value or "").strip()
        if value and not COLOR_RE.fullmatch(value):
            raise serializers.ValidationError("El color debe ser hexadecimal (#RRGGBB).")
        return value

    def validate_tax_zip(self, value):
        value = (value or "").strip()
        if value and not _re.fullmatch(r"\d{5}", value):
            raise serializers.ValidationError("El código postal debe tener 5 dígitos.")
        return value

    def validate_billing_email(self, value):
        value = (value or "").strip()
        if value:
            from django.core.validators import validate_email
            from django.core.exceptions import ValidationError as DjangoValidationError

            try:
                validate_email(value)
            except DjangoValidationError:
                raise serializers.ValidationError("El correo de facturación no es válido.")
        return value


class ContractSerializer(serializers.ModelSerializer):
    class Meta:
        model = Contract
        fields = [
            "id", "project", "workspace", "name", "kind", "amount", "currency",
            "start_date", "end_date", "billing_cycle", "payment_terms_days",
            "status", "description", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "project", "workspace", "created_at", "updated_at"]

    def validate(self, data):
        kind = data.get("kind", getattr(self.instance, "kind", None))
        if kind == "one_off":
            data["billing_cycle"] = "none"
        elif kind == "retainer":
            cycle = data.get("billing_cycle", getattr(self.instance, "billing_cycle", "monthly"))
            if cycle == "none":
                raise serializers.ValidationError({"billing_cycle": "A retainer needs a billing cycle."})
        start = data.get("start_date", getattr(self.instance, "start_date", None))
        end = data.get("end_date", getattr(self.instance, "end_date", None))
        if start and end and end < start:
            raise serializers.ValidationError({"end_date": "End date cannot be before the start date."})
        amount = data.get("amount", getattr(self.instance, "amount", None))
        if amount is not None and amount <= 0:
            raise serializers.ValidationError({"amount": "Amount must be positive."})
        return data


class InvoiceSerializer(serializers.ModelSerializer):
    paid_amount = serializers.SerializerMethodField()
    effective_status = serializers.SerializerMethodField()

    class Meta:
        model = Invoice
        fields = [
            "id", "project", "workspace", "contract", "concept", "amount", "currency",
            "issue_date", "due_date", "status", "period_key",
            "paid_amount", "effective_status", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "project", "workspace", "period_key", "created_at", "updated_at"]

    def _paid(self, obj):
        # populated by the view via annotation or prefetch map; fall back to a query
        paid = getattr(obj, "_paid_amount", None)
        if paid is None:
            paid = sum((p.amount for p in obj.payments.all()), Decimal("0"))
        return paid

    def get_paid_amount(self, obj):
        return float(self._paid(obj))

    def get_effective_status(self, obj):
        return invoice_effective_status(obj, self._paid(obj))

    def validate(self, data):
        amount = data.get("amount", getattr(self.instance, "amount", None))
        if amount is not None and amount <= 0:
            raise serializers.ValidationError({"amount": "Amount must be positive."})
        issue = data.get("issue_date", getattr(self.instance, "issue_date", None))
        due = data.get("due_date", getattr(self.instance, "due_date", None))
        if issue and due and due < issue:
            raise serializers.ValidationError({"due_date": "Due date cannot be before the issue date."})
        return data

    def validate_contract(self, value):
        if value is not None:
            project_id = self.context.get("project_id")
            if project_id and str(value.project_id) != str(project_id):
                raise serializers.ValidationError("The contract does not belong to this project.")
        return value


class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = [
            "id", "project", "workspace", "invoice", "amount", "currency",
            "paid_at", "method", "reference", "notes", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "project", "workspace", "created_at", "updated_at"]

    def validate(self, data):
        amount = data.get("amount", getattr(self.instance, "amount", None))
        if amount is not None and amount <= 0:
            raise serializers.ValidationError({"amount": "Amount must be positive."})
        invoice = data.get("invoice", getattr(self.instance, "invoice", None))
        currency = data.get("currency", getattr(self.instance, "currency", None))
        if invoice is not None:
            if currency and invoice.currency != currency:
                raise serializers.ValidationError(
                    {"currency": "Payment currency must match the invoice currency."}
                )
            project_id = self.context.get("project_id")
            if project_id and str(invoice.project_id) != str(project_id):
                raise serializers.ValidationError(
                    {"invoice": "The invoice does not belong to this project."}
                )
        return data


class FinanceAccessSerializer(serializers.ModelSerializer):
    member_display_name = serializers.CharField(source="member.display_name", read_only=True)
    member_email = serializers.CharField(source="member.email", read_only=True)
    member_avatar_url = serializers.CharField(source="member.avatar_url", read_only=True, default="")

    class Meta:
        model = FinanceAccess
        fields = [
            "id", "workspace", "member", "role",
            "member_display_name", "member_email", "member_avatar_url",
            "created_at",
        ]
        read_only_fields = ["id", "workspace", "created_at"]


class ExpenseEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = ExpenseEntry
        fields = [
            "id", "workspace", "month", "category", "concept", "amount", "currency",
            "notes", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "workspace", "created_at", "updated_at"]

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError("Amount must be positive.")
        return value

    def validate_month(self, value):
        import re

        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", value or ""):
            raise serializers.ValidationError("Month must be in YYYY-MM format.")
        return value


class FinanceAnalysisSerializer(serializers.ModelSerializer):
    created_by_display_name = serializers.CharField(
        source="created_by.display_name", read_only=True, default=""
    )

    class Meta:
        model = FinanceAnalysis
        fields = [
            "id", "workspace", "content", "period_from", "period_to",
            "created_by", "created_by_display_name", "created_at",
        ]
        read_only_fields = fields


class CashSnapshotSerializer(serializers.ModelSerializer):
    class Meta:
        model = CashSnapshot
        fields = ["id", "workspace", "as_of", "amount", "currency", "notes", "created_at"]
        read_only_fields = ["id", "workspace", "created_at"]
