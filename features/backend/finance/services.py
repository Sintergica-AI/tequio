# Sintergica CE extension: finance domain services — lazy retainer invoice
# materialization and read-time aggregation (client status, dashboard payload).
# Amounts are never summed across currencies. (AGPL-3.0-only)

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django.db import IntegrityError
from django.db.models import Sum

from plane.finance.models import Contract, FinanceProfile, Invoice, Payment

CYCLE_STEP_MONTHS = {"monthly": 1, "quarterly": 3, "yearly": 12}
MAX_PERIODS = 24
UPCOMING_WINDOW_DAYS = 7
CURRENCIES = ("MXN", "USD")


def _add_months(year, month, months):
    total = (year * 12 + (month - 1)) + months
    return total // 12, (total % 12) + 1


def _period_label(year, month):
    months_es = [
        "enero", "febrero", "marzo", "abril", "mayo", "junio",
        "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
    ]
    return f"{months_es[month - 1]} {year}"


def materialize_retainer_invoices(project, today=None):
    """Create-only, idempotent generation of retainer invoices for elapsed
    periods. Existing rows are never touched, so manual edits survive."""
    today = today or date.today()
    profile = FinanceProfile.objects.filter(project=project).first()
    billing_day = profile.billing_day if profile else 1

    contracts = Contract.objects.filter(project=project, kind="retainer", status="active")
    for contract in contracts:
        step = CYCLE_STEP_MONTHS.get(contract.billing_cycle)
        if not step:
            continue
        year, month = contract.start_date.year, contract.start_date.month
        for _ in range(MAX_PERIODS):
            period_start = date(year, month, 1)
            if period_start > today:
                break
            if contract.end_date and period_start > contract.end_date:
                break
            issue_date = max(date(year, month, min(billing_day, 28)), contract.start_date)
            if issue_date > today:
                break
            period_key = f"{year:04d}-{month:02d}"
            try:
                Invoice.objects.get_or_create(
                    contract=contract,
                    period_key=period_key,
                    defaults={
                        "project": project,
                        "workspace_id": project.workspace_id,
                        "concept": f"{contract.name} — {_period_label(year, month)}",
                        "amount": contract.amount,
                        "currency": contract.currency,
                        "issue_date": issue_date,
                        "due_date": issue_date + timedelta(days=contract.payment_terms_days),
                        "status": "pending",
                    },
                )
            except IntegrityError:
                pass  # concurrent create — the row exists, which is all we need
            year, month = _add_months(year, month, step)


def invoice_effective_status(invoice, paid_amount, today=None):
    today = today or date.today()
    if invoice.status == "cancelled":
        return "cancelled"
    if invoice.status == "paid":
        return "paid"
    if paid_amount and paid_amount >= invoice.amount:
        return "paid"
    if paid_amount and Decimal("0") < paid_amount < invoice.amount:
        return "partial" if invoice.due_date >= today else "overdue"
    return "overdue" if invoice.due_date < today else "pending"


def _paid_map(invoices):
    """invoice_id -> paid amount, in one query."""
    rows = (
        Payment.objects.filter(invoice__in=[i.id for i in invoices])
        .values("invoice_id")
        .annotate(total=Sum("amount"))
    )
    return {r["invoice_id"]: r["total"] or Decimal("0") for r in rows}


def _zero_by_currency():
    return {c: Decimal("0") for c in CURRENCIES}


def project_financials(project, today=None, materialize=True):
    """Everything the client card / project summary needs, per currency."""
    today = today or date.today()
    if materialize:
        materialize_retainer_invoices(project, today)

    revenue = _zero_by_currency()
    for row in Payment.objects.filter(project=project).values("currency").annotate(total=Sum("amount")):
        if row["currency"] in revenue:
            revenue[row["currency"]] += row["total"] or Decimal("0")

    invoices = list(Invoice.objects.filter(project=project, status="pending"))
    paid = _paid_map(invoices)

    outstanding = _zero_by_currency()
    overdue_amount = _zero_by_currency()
    has_overdue = False
    has_due_soon = False
    next_due_date = None
    open_invoices = []
    for inv in invoices:
        remaining = inv.amount - paid.get(inv.id, Decimal("0"))
        if remaining <= 0:
            continue
        if inv.currency in outstanding:
            outstanding[inv.currency] += remaining
        if inv.due_date < today:
            has_overdue = True
            if inv.currency in overdue_amount:
                overdue_amount[inv.currency] += remaining
        elif inv.due_date <= today + timedelta(days=UPCOMING_WINDOW_DAYS):
            has_due_soon = True
        if inv.due_date >= today and (next_due_date is None or inv.due_date < next_due_date):
            next_due_date = inv.due_date
        open_invoices.append((inv, remaining))

    status = "vencido" if has_overdue else ("por_vencer" if has_due_soon else "al_corriente")

    retainer = (
        Contract.objects.filter(project=project, kind="retainer", status="active")
        .order_by("-start_date")
        .first()
    )

    return {
        "revenue": {c: float(v) for c, v in revenue.items()},
        "outstanding": {c: float(v) for c, v in outstanding.items()},
        "overdue_amount": {c: float(v) for c, v in overdue_amount.items()},
        "status": status,
        "next_due_date": next_due_date.isoformat() if next_due_date else None,
        "active_retainer": (
            {
                "amount": float(retainer.amount),
                "currency": retainer.currency,
                "cycle": retainer.billing_cycle,
            }
            if retainer
            else None
        ),
        "_open_invoices": open_invoices,  # internal: reused by the dashboard for alerts
    }


def build_dashboard(workspace, today=None):
    today = today or date.today()
    profiles = FinanceProfile.objects.filter(workspace=workspace).select_related("project")

    totals = {
        c: {"revenue_ytd": Decimal("0"), "outstanding": Decimal("0"), "overdue_amount": Decimal("0")}
        for c in CURRENCIES
    }
    clients = []
    alerts = []

    for profile in profiles:
        project = profile.project
        fin = project_financials(project, today)
        for c in CURRENCIES:
            totals[c]["outstanding"] += Decimal(str(fin["outstanding"][c]))
            totals[c]["overdue_amount"] += Decimal(str(fin["overdue_amount"][c]))
        clients.append(
            {
                "project_id": str(project.id),
                "project_name": project.name,
                "status": fin["status"],
                "active_retainer": fin["active_retainer"],
                "revenue": fin["revenue"],
                "outstanding": fin["outstanding"],
                "next_due_date": fin["next_due_date"],
            }
        )
        for inv, remaining in fin["_open_invoices"]:
            if inv.due_date < today:
                alerts.append(
                    {
                        "type": "overdue",
                        "invoice_id": str(inv.id),
                        "project_id": str(project.id),
                        "project_name": project.name,
                        "concept": inv.concept,
                        "amount": float(remaining),
                        "currency": inv.currency,
                        "due_date": inv.due_date.isoformat(),
                        "days": (today - inv.due_date).days,
                    }
                )
            elif inv.due_date <= today + timedelta(days=UPCOMING_WINDOW_DAYS):
                alerts.append(
                    {
                        "type": "upcoming",
                        "invoice_id": str(inv.id),
                        "project_id": str(project.id),
                        "project_name": project.name,
                        "concept": inv.concept,
                        "amount": float(remaining),
                        "currency": inv.currency,
                        "due_date": inv.due_date.isoformat(),
                        "days": (inv.due_date - today).days,
                    }
                )

    # revenue YTD per currency (single query across the workspace's client projects)
    year_start = date(today.year, 1, 1)
    project_ids = [p.project_id for p in profiles]
    for row in (
        Payment.objects.filter(project_id__in=project_ids, paid_at__gte=year_start)
        .values("currency")
        .annotate(total=Sum("amount"))
    ):
        if row["currency"] in totals:
            totals[row["currency"]]["revenue_ytd"] += row["total"] or Decimal("0")

    # monthly revenue, last 12 months, per currency
    start_year, start_month = _add_months(today.year, today.month, -11)
    monthly_start = date(start_year, start_month, 1)
    buckets = defaultdict(lambda: {c: Decimal("0") for c in CURRENCIES})
    for row in (
        Payment.objects.filter(project_id__in=project_ids, paid_at__gte=monthly_start)
        .values("currency", "paid_at", "amount")
    ):
        key = f"{row['paid_at'].year:04d}-{row['paid_at'].month:02d}"
        if row["currency"] in CURRENCIES:
            buckets[key][row["currency"]] += row["amount"]

    monthly_revenue = []
    y, m = start_year, start_month
    for _ in range(12):
        key = f"{y:04d}-{m:02d}"
        entry = {"month": key}
        for c in CURRENCIES:
            entry[c] = float(buckets[key][c]) if key in buckets else 0.0
        monthly_revenue.append(entry)
        y, m = _add_months(y, m, 1)

    alerts.sort(key=lambda a: (0 if a["type"] == "overdue" else 1, -a["days"] if a["type"] == "overdue" else a["days"]))
    clients.sort(key=lambda cl: ({"vencido": 0, "por_vencer": 1, "al_corriente": 2}[cl["status"]], cl["project_name"].lower()))

    return {
        "totals": {c: {k: float(v) for k, v in t.items()} for c, t in totals.items()},
        "monthly_revenue": monthly_revenue,
        "clients": clients,
        "alerts": alerts,
    }
