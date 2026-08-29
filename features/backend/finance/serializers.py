# Sintergica CE extension: finance serializers. (AGPL-3.0-only)

from decimal import Decimal

from rest_framework import serializers

from plane.finance.models import CashSnapshot, Contract, ExpenseEntry, FinanceAccess, FinanceProfile, Invoice, Payment
from plane.finance.services import invoice_effective_status


class FinanceProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = FinanceProfile
        fields = [
            "id", "project", "workspace", "default_currency", "billing_day", "notes",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "project", "workspace", "created_at", "updated_at"]


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
            "id", "workspace", "member",
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


class CashSnapshotSerializer(serializers.ModelSerializer):
    class Meta:
        model = CashSnapshot
        fields = ["id", "workspace", "as_of", "amount", "currency", "notes", "created_at"]
        read_only_fields = ["id", "workspace", "created_at"]
