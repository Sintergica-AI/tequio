# Sintergica CE extension: finance endpoints (session-authenticated app API).
# (AGPL-3.0-only)


from rest_framework import status
from rest_framework.response import Response

from plane.app.views.base import BaseAPIView
from plane.db.models import Project, Workspace, WorkspaceMember
from plane.finance.models import Contract, FinanceAccess, FinanceProfile, Invoice, Payment
from plane.finance.permissions import (
    allow_finance_access,
    allow_finance_admin,
    has_finance_access,
    is_workspace_admin,
)
from plane.finance.serializers import (
    ContractSerializer,
    FinanceAccessSerializer,
    FinanceProfileSerializer,
    InvoiceSerializer,
    PaymentSerializer,
)
from plane.finance.services import (
    _paid_map,
    build_dashboard,
    materialize_retainer_invoices,
    project_financials,
)


def _get_project(slug, project_id):
    return Project.objects.get(pk=project_id, workspace__slug=slug)


def _ensure_profile(project):
    """Registrar datos financieros convierte al proyecto en cliente de forma
    implícita: sin esto, el dashboard (que parte de FinanceProfile) queda vacío
    aunque existan contratos o pagos."""
    FinanceProfile.objects.get_or_create(
        project=project, defaults={"workspace_id": project.workspace_id}
    )


class FinanceMeEndpoint(BaseAPIView):
    def get(self, request, slug):
        if not WorkspaceMember.objects.filter(
            member=request.user, workspace__slug=slug, is_active=True
        ).exists():
            return Response(
                {"error": "You don't have the required permissions."},
                status=status.HTTP_403_FORBIDDEN,
            )
        return Response(
            {
                "has_access": has_finance_access(request.user, slug),
                "is_admin": is_workspace_admin(request.user, slug),
            },
            status=status.HTTP_200_OK,
        )


class FinanceDashboardEndpoint(BaseAPIView):
    @allow_finance_access
    def get(self, request, slug):
        workspace = Workspace.objects.get(slug=slug)
        return Response(build_dashboard(workspace), status=status.HTTP_200_OK)


class FinanceAccessEndpoint(BaseAPIView):
    @allow_finance_admin
    def get(self, request, slug):
        rows = FinanceAccess.objects.filter(workspace__slug=slug).select_related("member")
        return Response(FinanceAccessSerializer(rows, many=True).data, status=status.HTTP_200_OK)

    @allow_finance_admin
    def post(self, request, slug):
        workspace = Workspace.objects.get(slug=slug)
        member_ids = request.data.get("member_ids") or []
        if not isinstance(member_ids, list) or not member_ids:
            return Response({"error": "member_ids is required."}, status=status.HTTP_400_BAD_REQUEST)

        valid_member_ids = set(
            str(m)
            for m in WorkspaceMember.objects.filter(
                workspace=workspace, member_id__in=member_ids, is_active=True
            ).values_list("member_id", flat=True)
        )
        invalid = [m for m in member_ids if str(m) not in valid_member_ids]
        if invalid:
            return Response(
                {"error": "Some users are not active members of this workspace."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        created = []
        for member_id in member_ids:
            row, _ = FinanceAccess.objects.get_or_create(workspace=workspace, member_id=member_id)
            created.append(row)
        return Response(
            FinanceAccessSerializer(created, many=True).data, status=status.HTTP_201_CREATED
        )


class FinanceAccessDetailEndpoint(BaseAPIView):
    @allow_finance_admin
    def delete(self, request, slug, pk):
        row = FinanceAccess.objects.get(pk=pk, workspace__slug=slug)
        row.delete(soft=False)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ProjectFinanceProfileEndpoint(BaseAPIView):
    @allow_finance_access
    def get(self, request, slug, project_id):
        profile = FinanceProfile.objects.filter(
            project_id=project_id, workspace__slug=slug
        ).first()
        if profile is None:
            return Response(None, status=status.HTTP_200_OK)
        return Response(FinanceProfileSerializer(profile).data, status=status.HTTP_200_OK)

    @allow_finance_access
    def post(self, request, slug, project_id):
        project = _get_project(slug, project_id)
        if FinanceProfile.objects.filter(project=project).exists():
            return Response(
                {"error": "This project is already a client."}, status=status.HTTP_400_BAD_REQUEST
            )
        serializer = FinanceProfileSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(project=project, workspace_id=project.workspace_id)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @allow_finance_access
    def patch(self, request, slug, project_id):
        profile = FinanceProfile.objects.get(project_id=project_id, workspace__slug=slug)
        serializer = FinanceProfileSerializer(profile, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ProjectFinanceSummaryEndpoint(BaseAPIView):
    @allow_finance_access
    def get(self, request, slug, project_id):
        project = _get_project(slug, project_id)
        fin = project_financials(project)
        fin.pop("_open_invoices", None)
        fin["is_client"] = FinanceProfile.objects.filter(project=project).exists()
        return Response(fin, status=status.HTTP_200_OK)


class ContractsEndpoint(BaseAPIView):
    @allow_finance_access
    def get(self, request, slug, project_id):
        rows = Contract.objects.filter(project_id=project_id, workspace__slug=slug)
        return Response(ContractSerializer(rows, many=True).data, status=status.HTTP_200_OK)

    @allow_finance_access
    def post(self, request, slug, project_id):
        project = _get_project(slug, project_id)
        _ensure_profile(project)
        serializer = ContractSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(project=project, workspace_id=project.workspace_id)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ContractDetailEndpoint(BaseAPIView):
    @allow_finance_access
    def get(self, request, slug, project_id, pk):
        row = Contract.objects.get(pk=pk, project_id=project_id, workspace__slug=slug)
        return Response(ContractSerializer(row).data, status=status.HTTP_200_OK)

    @allow_finance_access
    def patch(self, request, slug, project_id, pk):
        row = Contract.objects.get(pk=pk, project_id=project_id, workspace__slug=slug)
        serializer = ContractSerializer(row, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @allow_finance_access
    def delete(self, request, slug, project_id, pk):
        row = Contract.objects.get(pk=pk, project_id=project_id, workspace__slug=slug)
        row.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class InvoicesEndpoint(BaseAPIView):
    @allow_finance_access
    def get(self, request, slug, project_id):
        project = _get_project(slug, project_id)
        materialize_retainer_invoices(project)
        rows = list(
            Invoice.objects.filter(project=project).select_related("contract").order_by("-due_date")
        )
        paid = _paid_map(rows)
        for row in rows:
            row._paid_amount = paid.get(row.id)
        serializer = InvoiceSerializer(rows, many=True, context={"project_id": project_id})
        return Response(serializer.data, status=status.HTTP_200_OK)

    @allow_finance_access
    def post(self, request, slug, project_id):
        project = _get_project(slug, project_id)
        _ensure_profile(project)
        serializer = InvoiceSerializer(data=request.data, context={"project_id": project_id})
        if serializer.is_valid():
            serializer.save(project=project, workspace_id=project.workspace_id)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class InvoiceDetailEndpoint(BaseAPIView):
    @allow_finance_access
    def get(self, request, slug, project_id, pk):
        row = Invoice.objects.get(pk=pk, project_id=project_id, workspace__slug=slug)
        return Response(
            InvoiceSerializer(row, context={"project_id": project_id}).data, status=status.HTTP_200_OK
        )

    @allow_finance_access
    def patch(self, request, slug, project_id, pk):
        row = Invoice.objects.get(pk=pk, project_id=project_id, workspace__slug=slug)
        serializer = InvoiceSerializer(row, data=request.data, partial=True, context={"project_id": project_id})
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @allow_finance_access
    def delete(self, request, slug, project_id, pk):
        row = Invoice.objects.get(pk=pk, project_id=project_id, workspace__slug=slug)
        row.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class PaymentsEndpoint(BaseAPIView):
    @allow_finance_access
    def get(self, request, slug, project_id):
        rows = Payment.objects.filter(project_id=project_id, workspace__slug=slug).select_related(
            "invoice"
        )
        return Response(PaymentSerializer(rows, many=True).data, status=status.HTTP_200_OK)

    @allow_finance_access
    def post(self, request, slug, project_id):
        project = _get_project(slug, project_id)
        _ensure_profile(project)
        serializer = PaymentSerializer(data=request.data, context={"project_id": project_id})
        if serializer.is_valid():
            serializer.save(project=project, workspace_id=project.workspace_id)
            # if the invoice is now fully covered, mark it as paid
            invoice = serializer.instance.invoice
            if invoice and invoice.status == "pending":
                paid = _paid_map([invoice]).get(invoice.id)
                if paid is not None and paid >= invoice.amount:
                    invoice.status = "paid"
                    invoice.save(update_fields=["status", "updated_at"])
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class PaymentDetailEndpoint(BaseAPIView):
    @allow_finance_access
    def get(self, request, slug, project_id, pk):
        row = Payment.objects.get(pk=pk, project_id=project_id, workspace__slug=slug)
        return Response(PaymentSerializer(row).data, status=status.HTTP_200_OK)

    @allow_finance_access
    def patch(self, request, slug, project_id, pk):
        row = Payment.objects.get(pk=pk, project_id=project_id, workspace__slug=slug)
        serializer = PaymentSerializer(row, data=request.data, partial=True, context={"project_id": project_id})
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @allow_finance_access
    def delete(self, request, slug, project_id, pk):
        row = Payment.objects.get(pk=pk, project_id=project_id, workspace__slug=slug)
        row.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------
# Command center: expenses, cash snapshots, P&L, forecast, insights
# --------------------------------------------------------------------------
from plane.finance.analytics import build_forecast, build_insights, build_pnl  # noqa: E402
from plane.finance.models import CashSnapshot, ExpenseEntry  # noqa: E402
from plane.finance.serializers import CashSnapshotSerializer, ExpenseEntrySerializer  # noqa: E402


class ExpensesEndpoint(BaseAPIView):
    @allow_finance_access
    def get(self, request, slug):
        qs = ExpenseEntry.objects.filter(workspace__slug=slug)
        month = request.query_params.get("month")
        if month:
            qs = qs.filter(month=month)
        return Response(ExpenseEntrySerializer(qs, many=True).data, status=status.HTTP_200_OK)

    @allow_finance_access
    def post(self, request, slug):
        workspace = Workspace.objects.get(slug=slug)
        serializer = ExpenseEntrySerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(workspace=workspace)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ExpenseDetailEndpoint(BaseAPIView):
    @allow_finance_access
    def patch(self, request, slug, pk):
        row = ExpenseEntry.objects.get(pk=pk, workspace__slug=slug)
        serializer = ExpenseEntrySerializer(row, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @allow_finance_access
    def delete(self, request, slug, pk):
        row = ExpenseEntry.objects.get(pk=pk, workspace__slug=slug)
        row.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class CashSnapshotsEndpoint(BaseAPIView):
    @allow_finance_access
    def get(self, request, slug):
        qs = CashSnapshot.objects.filter(workspace__slug=slug)[:24]
        return Response(CashSnapshotSerializer(qs, many=True).data, status=status.HTTP_200_OK)

    @allow_finance_access
    def post(self, request, slug):
        workspace = Workspace.objects.get(slug=slug)
        serializer = CashSnapshotSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(workspace=workspace)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class CashSnapshotDetailEndpoint(BaseAPIView):
    @allow_finance_access
    def delete(self, request, slug, pk):
        row = CashSnapshot.objects.get(pk=pk, workspace__slug=slug)
        row.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class FinancePnlEndpoint(BaseAPIView):
    @allow_finance_access
    def get(self, request, slug):
        workspace = Workspace.objects.get(slug=slug)
        return Response(build_pnl(workspace), status=status.HTTP_200_OK)


class FinanceForecastEndpoint(BaseAPIView):
    @allow_finance_access
    def get(self, request, slug):
        workspace = Workspace.objects.get(slug=slug)
        return Response(build_forecast(workspace), status=status.HTTP_200_OK)


class FinanceInsightsEndpoint(BaseAPIView):
    @allow_finance_access
    def get(self, request, slug):
        workspace = Workspace.objects.get(slug=slug)
        return Response(build_insights(workspace), status=status.HTTP_200_OK)
