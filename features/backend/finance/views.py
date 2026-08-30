# Sintergica CE extension: finance endpoints (session-authenticated app API).
# (AGPL-3.0-only)


from rest_framework import status
from rest_framework.response import Response

from plane.app.views.base import BaseAPIView
from plane.db.models import Project, Workspace, WorkspaceMember
from plane.finance.models import Contract, FinanceAccess, FinanceProfile, Invoice, Payment
from plane.finance.permissions import (
    allow_collections_access,
    allow_finance_access,
    allow_finance_admin,
    finance_role,
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


def _parse_range(request):
    """Optional ?date_from=YYYY-MM-DD&date_to=YYYY-MM-DD; invalid values are
    ignored rather than erroring so a stale link never breaks the page."""
    from datetime import date as _d

    out = []
    for name in ("date_from", "date_to"):
        raw = request.query_params.get(name) or (request.data.get(name) if isinstance(request.data, dict) else None)
        try:
            out.append(_d.fromisoformat(raw) if raw else None)
        except (TypeError, ValueError):
            out.append(None)
    date_from, date_to = out
    if date_from and date_to and date_to < date_from:
        date_from, date_to = date_to, date_from
    return date_from, date_to


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
        role = finance_role(request.user, slug)
        return Response(
            {
                "has_access": role == "finance",
                "is_admin": is_workspace_admin(request.user, slug),
                "role": role,
                "has_collections": role is not None,
            },
            status=status.HTTP_200_OK,
        )


class FinanceDashboardEndpoint(BaseAPIView):
    @allow_finance_access
    def get(self, request, slug):
        workspace = Workspace.objects.get(slug=slug)
        date_from, date_to = _parse_range(request)
        return Response(
            build_dashboard(workspace, date_from=date_from, date_to=date_to),
            status=status.HTTP_200_OK,
        )


class FinanceAccessEndpoint(BaseAPIView):
    @allow_finance_admin
    def get(self, request, slug):
        rows = FinanceAccess.objects.filter(workspace__slug=slug).select_related("member")
        return Response(FinanceAccessSerializer(rows, many=True).data, status=status.HTTP_200_OK)

    @allow_finance_admin
    def post(self, request, slug):
        workspace = Workspace.objects.get(slug=slug)

        # single-member upsert from the members page: {member_id, role}
        # role "none" removes the row.
        single_member = request.data.get("member_id")
        if single_member:
            role = request.data.get("role", "finance")
            if role not in ("finance", "collections", "none"):
                return Response({"error": "Invalid role."}, status=status.HTTP_400_BAD_REQUEST)
            if not WorkspaceMember.objects.filter(
                workspace=workspace, member_id=single_member, is_active=True
            ).exists():
                return Response(
                    {"error": "The user is not an active member of this workspace."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if role == "none":
                for row in FinanceAccess.objects.filter(workspace=workspace, member_id=single_member):
                    row.delete(soft=False)
                return Response(status=status.HTTP_204_NO_CONTENT)
            row, created = FinanceAccess.objects.get_or_create(
                workspace=workspace, member_id=single_member, defaults={"role": role}
            )
            if not created and row.role != role:
                row.role = role
                row.save(update_fields=["role", "updated_at"])
            return Response(
                FinanceAccessSerializer(row).data,
                status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
            )

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
# Cobranza (collections role): only pending charges + payment recording.
# Deliberately exposes NO revenue, KPIs, P&L, contracts or client fiscal data.
# --------------------------------------------------------------------------


class FinanceCollectionsEndpoint(BaseAPIView):
    @allow_collections_access
    def get(self, request, slug):
        from datetime import date as _dt

        today = _dt.today()
        workspace = Workspace.objects.get(slug=slug)
        for profile in FinanceProfile.objects.filter(workspace=workspace).select_related("project"):
            materialize_retainer_invoices(profile.project)
        invoices = list(
            Invoice.objects.filter(workspace=workspace, status="pending").select_related("project")
        )
        paid = _paid_map(invoices)
        rows = []
        for inv in invoices:
            paid_amount = paid.get(inv.id) or 0
            remaining = inv.amount - paid_amount
            if remaining <= 0:
                continue
            rows.append(
                {
                    "id": str(inv.id),
                    "project_id": str(inv.project_id),
                    "project_name": inv.project.name,
                    "concept": inv.concept,
                    "amount": float(inv.amount),
                    "paid_amount": float(paid_amount),
                    "remaining": float(remaining),
                    "currency": inv.currency,
                    "issue_date": inv.issue_date.isoformat(),
                    "due_date": inv.due_date.isoformat(),
                    "status": "overdue" if inv.due_date < today else "pending",
                    "days": (today - inv.due_date).days if inv.due_date < today else (inv.due_date - today).days,
                }
            )
        rows.sort(key=lambda r: (0 if r["status"] == "overdue" else 1, r["due_date"]))
        return Response({"invoices": rows}, status=status.HTTP_200_OK)


class FinanceCollectionsPaymentEndpoint(BaseAPIView):
    @allow_collections_access
    def post(self, request, slug, invoice_id):
        invoice = Invoice.objects.get(pk=invoice_id, workspace__slug=slug)
        if invoice.status != "pending":
            return Response(
                {"error": "Este cobro ya no está pendiente."}, status=status.HTTP_400_BAD_REQUEST
            )
        data = {
            "invoice": str(invoice.id),
            "amount": request.data.get("amount"),
            "currency": invoice.currency,
            "paid_at": request.data.get("paid_at"),
            "method": request.data.get("method", "transfer"),
            "reference": request.data.get("reference", ""),
            "notes": request.data.get("notes", ""),
        }
        serializer = PaymentSerializer(data=data, context={"project_id": str(invoice.project_id)})
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        serializer.save(project_id=invoice.project_id, workspace_id=invoice.workspace_id)
        # fully covered -> mark as paid (same rule as the full payments endpoint)
        paid = _paid_map([invoice]).get(invoice.id)
        if paid is not None and paid >= invoice.amount:
            invoice.status = "paid"
            invoice.save(update_fields=["status", "updated_at"])
        return Response(serializer.data, status=status.HTTP_201_CREATED)


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
        date_from, date_to = _parse_range(request)
        if date_from:
            qs = qs.filter(month__gte=f"{date_from.year:04d}-{date_from.month:02d}")
        if date_to:
            qs = qs.filter(month__lte=f"{date_to.year:04d}-{date_to.month:02d}")
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
        date_from, date_to = _parse_range(request)
        return Response(
            build_pnl(workspace, date_from=date_from, date_to=date_to), status=status.HTTP_200_OK
        )


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


# --------------------------------------------------------------------------
# Finance AI: bank statement import + CFO-style analysis
# --------------------------------------------------------------------------
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser  # noqa: E402

from plane.finance.ai import FinanceAINotConfigured, FinanceAIUnavailable, analyze_finances, parse_bank_statement  # noqa: E402
from plane.finance.ai import MAX_STATEMENT_CHARS, PdfWithoutText, extract_pdf_text  # noqa: E402
from datetime import date as _date  # noqa: E402
from plane.finance.services import build_dashboard  # noqa: E402
from plane.utils.exception_logger import log_exception  # noqa: E402


MAX_IMPORT_FILE_SIZE = 15 * 1024 * 1024  # a bank PDF is rarely over a few MB


class FinanceImportParseEndpoint(BaseAPIView):
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    @allow_finance_access
    def post(self, request, slug):
        upload = request.FILES.get("file")
        if upload is not None:
            if upload.size > MAX_IMPORT_FILE_SIZE:
                return Response(
                    {"error": "El archivo es demasiado grande (máx. 15 MB)."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            name = (upload.name or "").lower()
            if name.endswith(".pdf") or upload.content_type == "application/pdf":
                try:
                    content = extract_pdf_text(upload)
                except PdfWithoutText:
                    return Response(
                        {
                            "error": "El PDF no contiene texto legible (probablemente es un "
                            "escaneo). Exporta el estado de cuenta como CSV o copia el texto "
                            "de la banca en línea."
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                except Exception as e:
                    log_exception(e)
                    return Response(
                        {"error": "No se pudo leer el PDF. Verifica que no esté dañado ni protegido con contraseña."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
            else:
                raw = upload.read()
                try:
                    content = raw.decode("utf-8")
                except UnicodeDecodeError:
                    content = raw.decode("latin-1", errors="replace")
        else:
            content = request.data.get("content") or ""
        if not isinstance(content, str) or not content.strip():
            return Response({"error": "El contenido está vacío."}, status=status.HTTP_400_BAD_REQUEST)
        if len(content) > MAX_STATEMENT_CHARS:
            return Response(
                {"error": "El estado de cuenta es demasiado grande (máx. 200 mil caracteres)."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            transactions = parse_bank_statement(content)
        except FinanceAINotConfigured as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except FinanceAIUnavailable as e:
            return Response({"error": str(e)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except Exception as e:
            log_exception(e)
            return Response(
                {"error": "No se pudo interpretar el estado de cuenta. Inténtalo de nuevo."},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        return Response({"transactions": transactions}, status=status.HTTP_200_OK)


class FinanceImportCommitEndpoint(BaseAPIView):
    @allow_finance_access
    def post(self, request, slug):
        workspace = Workspace.objects.get(slug=slug)
        expenses = request.data.get("expenses") or []
        if not isinstance(expenses, list) or not expenses:
            return Response({"error": "No hay gastos que importar."}, status=status.HTTP_400_BAD_REQUEST)
        if len(expenses) > 500:
            return Response({"error": "Demasiados movimientos en una sola importación."}, status=status.HTTP_400_BAD_REQUEST)

        serializer = ExpenseEntrySerializer(data=expenses, many=True)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        rows = serializer.save(workspace=workspace)
        return Response(
            {"created": len(rows), "expenses": ExpenseEntrySerializer(rows, many=True).data},
            status=status.HTTP_201_CREATED,
        )


def _analysis_context(workspace, date_from=None, date_to=None):
    dashboard = build_dashboard(workspace, date_from=date_from, date_to=date_to)
    context = {
        "hoy": _date.today().isoformat(),
        "totales": dashboard["totals"],
        "clientes": dashboard["clients"],
        "alertas": dashboard["alerts"][:10],
        "pnl_12m": build_pnl(workspace, date_from=date_from, date_to=date_to)["months"],
        "proyeccion_6m": build_forecast(workspace),
        "hallazgos": build_insights(workspace)["insights"],
    }
    if date_from or date_to:
        context["periodo_filtrado"] = {
            "desde": date_from.isoformat() if date_from else None,
            "hasta": date_to.isoformat() if date_to else None,
        }
    return context


def _run_analysis(context):
    """Returns (analysis, error_response); exactly one is non-None."""
    try:
        return analyze_finances(context), None
    except FinanceAINotConfigured as e:
        return None, Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
    except FinanceAIUnavailable as e:
        return None, Response({"error": str(e)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    except Exception as e:
        log_exception(e)
        return None, Response(
            {"error": "El análisis no está disponible en este momento. Inténtalo de nuevo."},
            status=status.HTTP_502_BAD_GATEWAY,
        )


class FinanceAnalyzeEndpoint(BaseAPIView):
    """Legacy one-shot analysis (kept for API compatibility; not persisted)."""

    @allow_finance_access
    def post(self, request, slug):
        workspace = Workspace.objects.get(slug=slug)
        analysis, error = _run_analysis(_analysis_context(workspace))
        if error is not None:
            return error
        return Response({"analysis": analysis}, status=status.HTTP_200_OK)


class FinanceAnalysesEndpoint(BaseAPIView):
    @allow_finance_access
    def get(self, request, slug):
        rows = FinanceAnalysis.objects.filter(workspace__slug=slug).select_related("created_by")[:50]
        return Response(FinanceAnalysisSerializer(rows, many=True).data, status=status.HTTP_200_OK)

    @allow_finance_access
    def post(self, request, slug):
        workspace = Workspace.objects.get(slug=slug)
        date_from, date_to = _parse_range(request)
        analysis, error = _run_analysis(_analysis_context(workspace, date_from, date_to))
        if error is not None:
            return error
        row = FinanceAnalysis.objects.create(
            workspace=workspace,
            content=analysis,
            period_from=date_from,
            period_to=date_to,
            created_by=request.user,
        )
        return Response(FinanceAnalysisSerializer(row).data, status=status.HTTP_201_CREATED)


class FinanceAnalysisDetailEndpoint(BaseAPIView):
    @allow_finance_access
    def delete(self, request, slug, pk):
        row = FinanceAnalysis.objects.get(pk=pk, workspace__slug=slug)
        row.delete(soft=False)
        return Response(status=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------
# CSF (Constancia de Situación Fiscal): a single PDF per client profile,
# stored through FileAsset/MinIO with the same presigned flow as the drive.
# --------------------------------------------------------------------------
from django.http import HttpResponseRedirect  # noqa: E402
from django.utils import timezone  # noqa: E402

from plane.bgtasks.storage_metadata_task import get_asset_object_metadata  # noqa: E402
from plane.db.models import FileAsset  # noqa: E402
from plane.finance.models import FinanceAnalysis  # noqa: E402
from plane.finance.serializers import FinanceAnalysisSerializer  # noqa: E402
from plane.settings.storage import S3Storage  # noqa: E402
from plane.utils.path_validator import sanitize_filename  # noqa: E402

CSF_ENTITY_TYPE = "FINANCE_CSF"
CSF_MAX_SIZE = 10 * 1024 * 1024


class ProjectFinanceCsfEndpoint(BaseAPIView):
    def _profile(self, slug, project_id):
        return FinanceProfile.objects.filter(
            project_id=project_id, workspace__slug=slug
        ).select_related("csf_asset").first()

    @allow_finance_access
    def get(self, request, slug, project_id):
        profile = self._profile(slug, project_id)
        asset = profile.csf_asset if profile else None
        if asset is None or not asset.is_uploaded or asset.is_deleted:
            return Response({"error": "No hay CSF cargada."}, status=status.HTTP_404_NOT_FOUND)
        storage = S3Storage(request=request)
        signed_url = storage.generate_presigned_url(
            object_name=asset.asset.name,
            disposition="inline",  # a PDF; safe to render in the browser
            filename=(asset.attributes or {}).get("name", "CSF.pdf"),
        )
        return HttpResponseRedirect(signed_url)

    @allow_finance_access
    def post(self, request, slug, project_id):
        project = _get_project(slug, project_id)
        name = sanitize_filename(str(request.data.get("name") or "CSF.pdf"))
        content_type = request.data.get("type") or "application/pdf"
        if content_type != "application/pdf" or not name.lower().endswith(".pdf"):
            return Response({"error": "La CSF debe ser un PDF."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            size = int(request.data.get("size", 0))
        except (TypeError, ValueError):
            return Response({"error": "Tamaño inválido."}, status=status.HTTP_400_BAD_REQUEST)
        if size <= 0 or size > CSF_MAX_SIZE:
            return Response(
                {"error": "La CSF debe pesar entre 1 byte y 10 MB."}, status=status.HTTP_400_BAD_REQUEST
            )
        import uuid as _uuid

        asset_key = f"{project.workspace_id}/{_uuid.uuid4().hex}-{name}"
        asset = FileAsset.objects.create(
            attributes={"name": name, "type": content_type, "size": size},
            asset=asset_key,
            size=size,
            workspace_id=project.workspace_id,
            project=project,
            created_by=request.user,
            entity_type=CSF_ENTITY_TYPE,
        )
        storage = S3Storage(request=request)
        presigned_url = storage.generate_presigned_post(
            object_name=asset_key, file_type=content_type, file_size=size
        )
        if presigned_url is None:
            return Response(
                {"error": "No se pudo generar la URL de subida."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        return Response(
            {"upload_data": presigned_url, "asset_id": str(asset.id)}, status=status.HTTP_200_OK
        )

    @allow_finance_access
    def patch(self, request, slug, project_id):
        project = _get_project(slug, project_id)
        asset = FileAsset.objects.get(
            pk=request.data.get("asset_id"),
            project=project,
            entity_type=CSF_ENTITY_TYPE,
            is_deleted=False,
        )
        if not asset.is_uploaded:
            asset.is_uploaded = True
            asset.save(update_fields=["is_uploaded"])
            if not asset.storage_metadata:
                get_asset_object_metadata.delay(asset_id=str(asset.id))
        _ensure_profile(project)
        profile = FinanceProfile.objects.select_related("csf_asset").get(project=project)
        old = profile.csf_asset
        if old is not None and old.id != asset.id:
            old.is_deleted = True
            old.deleted_at = timezone.now()
            old.save(update_fields=["is_deleted", "deleted_at"])
        profile.csf_asset = asset
        profile.save(update_fields=["csf_asset", "updated_at"])
        return Response(FinanceProfileSerializer(profile).data, status=status.HTTP_200_OK)

    @allow_finance_access
    def delete(self, request, slug, project_id):
        profile = self._profile(slug, project_id)
        if profile is None or profile.csf_asset is None:
            return Response(status=status.HTTP_204_NO_CONTENT)
        asset = profile.csf_asset
        profile.csf_asset = None
        profile.save(update_fields=["csf_asset", "updated_at"])
        asset.is_deleted = True
        asset.deleted_at = timezone.now()
        asset.save(update_fields=["is_deleted", "deleted_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)
