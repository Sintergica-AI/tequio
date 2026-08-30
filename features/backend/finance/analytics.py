# Sintergica CE extension: finance analytics — monthly P&L, 6-month forecast
# (committed retainer billing + one-off run rate − expense run rate, anchored
# on the latest cash snapshot) and a rule-based insights engine. Insights carry
# structured data only (kind + severity + values); the frontend translates.
# Amounts are never summed across currencies. (AGPL-3.0-only)

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Sum

from plane.finance.models import CashSnapshot, Contract, ExpenseEntry, Invoice, Payment
from plane.finance.services import CYCLE_STEP_MONTHS, _add_months, _paid_map

CURRENCIES = ("MXN", "USD")
FORECAST_MONTHS = 6
PNL_MONTHS = 12
RUN_RATE_MONTHS = 3
CONCENTRATION_THRESHOLD = 0.40
RENEWAL_WINDOW_DAYS = 60


def _month_key(d):
    return f"{d.year:04d}-{d.month:02d}"


def _zero():
    return {c: Decimal("0") for c in CURRENCIES}


def _month_range(end_year, end_month, count):
    """List of (year, month) for `count` months ending at (end_year, end_month)."""
    start_y, start_m = _add_months(end_year, end_month, -(count - 1))
    out = []
    y, m = start_y, start_m
    for _ in range(count):
        out.append((y, m))
        y, m = _add_months(y, m, 1)
    return out


def _monthly_sums(qs, date_field, start_date):
    """{ "YYYY-MM": {cur: Decimal} } for a queryset with amount+currency."""
    buckets = defaultdict(_zero)
    for row in qs.filter(**{f"{date_field}__gte": start_date}).values("currency", date_field, "amount"):
        key = _month_key(row[date_field])
        if row["currency"] in CURRENCIES:
            buckets[key][row["currency"]] += row["amount"]
    return buckets


def _monthly_expense_sums(workspace, month_keys):
    buckets = defaultdict(_zero)
    for row in ExpenseEntry.objects.filter(workspace=workspace, month__in=month_keys).values(
        "month", "currency"
    ).annotate(total=Sum("amount")):
        if row["currency"] in CURRENCIES:
            buckets[row["month"]][row["currency"]] += row["total"] or Decimal("0")
    return buckets


# --------------------------------------------------------------------- P&L
def build_pnl(workspace, today=None, months=PNL_MONTHS, date_from=None, date_to=None):
    today = today or date.today()
    if date_from or date_to:
        end = date_to or today
        start = date_from or date(*_add_months(end.year, end.month, -(PNL_MONTHS - 1)), 1)
        span = (end.year - start.year) * 12 + (end.month - start.month) + 1
        months = max(1, min(span, 36))
        month_list = _month_range(end.year, end.month, months)
    else:
        month_list = _month_range(today.year, today.month, months)
    month_keys = [f"{y:04d}-{m:02d}" for y, m in month_list]
    start = date(month_list[0][0], month_list[0][1], 1)

    income = _monthly_sums(Payment.objects.filter(workspace=workspace), "paid_at", start)
    expenses = _monthly_expense_sums(workspace, month_keys)

    rows = []
    for key in month_keys:
        entry = {"month": key}
        for c in CURRENCIES:
            inc = income.get(key, _zero())[c]
            exp = expenses.get(key, _zero())[c]
            entry[c] = {"income": float(inc), "expenses": float(exp), "net": float(inc - exp)}
        rows.append(entry)
    return {"months": rows}


# ----------------------------------------------------------------- helpers
def _monthly_equivalent(contract):
    step = CYCLE_STEP_MONTHS.get(contract.billing_cycle)
    if not step:
        return Decimal("0")
    return contract.amount / Decimal(step)


def _committed_mrr(workspace, today):
    """Monthly-equivalent committed recurring revenue from active retainers
    currently in force."""
    mrr = _zero()
    for c in Contract.objects.filter(workspace=workspace, kind="retainer", status="active"):
        if c.start_date > today:
            continue
        if c.end_date and c.end_date < today:
            continue
        if c.currency in mrr:
            mrr[c.currency] += _monthly_equivalent(c)
    return mrr


def _retainer_billing_for_month(workspace, year, month):
    """Amount each active retainer will bill during (year, month), stepping
    from its start date by its cycle."""
    total = _zero()
    month_start = date(year, month, 1)
    ny, nm = _add_months(year, month, 1)
    month_end = date(ny, nm, 1) - timedelta(days=1)
    for c in Contract.objects.filter(workspace=workspace, kind="retainer", status="active"):
        step = CYCLE_STEP_MONTHS.get(c.billing_cycle)
        if not step or c.start_date > month_end:
            continue
        if c.end_date and c.end_date < month_start:
            continue
        # does a billing period start in this month?
        months_since_start = (year - c.start_date.year) * 12 + (month - c.start_date.month)
        if months_since_start >= 0 and months_since_start % step == 0:
            if c.currency in total:
                total[c.currency] += c.amount
    return total


def _run_rates(workspace, today):
    """(one-off revenue avg, expense avg) per currency over the last
    RUN_RATE_MONTHS closed months."""
    ly, lm = _add_months(today.year, today.month, -1)  # last closed month
    month_list = _month_range(ly, lm, RUN_RATE_MONTHS)
    month_keys = [f"{y:04d}-{m:02d}" for y, m in month_list]
    start = date(month_list[0][0], month_list[0][1], 1)

    # one-off revenue: payments not applied to retainer invoices
    oneoff = defaultdict(_zero)
    for p in Payment.objects.filter(workspace=workspace, paid_at__gte=start).select_related(
        "invoice__contract"
    ):
        kind = p.invoice.contract.kind if (p.invoice and p.invoice.contract) else "one_off"
        if kind != "retainer" and p.currency in CURRENCIES:
            oneoff[_month_key(p.paid_at)][p.currency] += p.amount

    expenses = _monthly_expense_sums(workspace, month_keys)

    n = Decimal(len(month_keys))
    oneoff_avg = {c: sum((oneoff.get(k, _zero())[c] for k in month_keys), Decimal("0")) / n for c in CURRENCIES}
    expense_months = [k for k in month_keys if k in expenses]
    if expense_months:
        ne = Decimal(len(expense_months))
        expense_avg = {c: sum((expenses[k][c] for k in expense_months), Decimal("0")) / ne for c in CURRENCIES}
    else:
        expense_avg = _zero()
    return oneoff_avg, expense_avg


def _latest_cash(workspace):
    cash = {}
    for c in CURRENCIES:
        snap = CashSnapshot.objects.filter(workspace=workspace, currency=c).order_by("-as_of", "-created_at").first()
        cash[c] = snap
    return cash


# ------------------------------------------------------------------ forecast
def build_forecast(workspace, today=None):
    today = today or date.today()
    oneoff_avg, expense_avg = _run_rates(workspace, today)
    mrr = _committed_mrr(workspace, today)
    cash_snaps = _latest_cash(workspace)

    cash_now = {c: (cash_snaps[c].amount if cash_snaps[c] else None) for c in CURRENCIES}
    running = {c: cash_now[c] for c in CURRENCIES}

    months = []
    y, m = today.year, today.month
    for _ in range(FORECAST_MONTHS):
        billing = _retainer_billing_for_month(workspace, y, m)
        entry = {"month": f"{y:04d}-{m:02d}"}
        for c in CURRENCIES:
            income = billing[c] + oneoff_avg[c]
            net = income - expense_avg[c]
            if running[c] is not None:
                running[c] = running[c] + net
            entry[c] = {
                "retainer_income": float(billing[c]),
                "oneoff_income": float(oneoff_avg[c]),
                "expenses": float(expense_avg[c]),
                "net": float(net),
                "projected_cash": float(running[c]) if running[c] is not None else None,
            }
        months.append(entry)
        y, m = _add_months(y, m, 1)

    # runway per currency: months of cash left at the projected average burn
    runway = {}
    for c in CURRENCIES:
        snap = cash_snaps[c]
        avg_net = sum(Decimal(str(e[c]["net"])) for e in months) / Decimal(len(months))
        if snap is None:
            runway[c] = None  # sin snapshot no hay runway
        elif avg_net >= 0:
            runway[c] = "infinite"
        elif snap.amount <= 0:
            runway[c] = 0.0
        else:
            runway[c] = round(float(snap.amount / abs(avg_net)), 1)

    return {
        "mrr": {c: float(v) for c, v in mrr.items()},
        "oneoff_run_rate": {c: float(v) for c, v in oneoff_avg.items()},
        "expense_run_rate": {c: float(v) for c, v in expense_avg.items()},
        "cash": {
            c: (
                {"amount": float(cash_snaps[c].amount), "as_of": cash_snaps[c].as_of.isoformat()}
                if cash_snaps[c]
                else None
            )
            for c in CURRENCIES
        },
        "runway_months": runway,
        "months": months,
    }


# ------------------------------------------------------------------ insights
def build_insights(workspace, today=None):
    """Rule engine. Each insight: {kind, severity, data} — the frontend owns
    the wording. Severity: critical > warning > info."""
    today = today or date.today()
    insights = []

    # 1. Collection: overdue invoices
    pending = list(
        Invoice.objects.filter(workspace=workspace, status="pending", due_date__lt=today).select_related("project")
    )
    paid = _paid_map(pending)
    overdue_total = _zero()
    overdue_clients = defaultdict(lambda: _zero())
    for inv in pending:
        remaining = inv.amount - paid.get(inv.id, Decimal("0"))
        if remaining > 0 and inv.currency in CURRENCIES:
            overdue_total[inv.currency] += remaining
            overdue_clients[inv.project.name][inv.currency] += remaining
    if any(v > 0 for v in overdue_total.values()):
        top = sorted(
            overdue_clients.items(), key=lambda kv: -max(kv[1].values())
        )[:3]
        insights.append(
            {
                "kind": "overdue_collection",
                "severity": "critical",
                "data": {
                    "total": {c: float(v) for c, v in overdue_total.items()},
                    "clients": [{"name": name, **{c: float(v) for c, v in amounts.items()}} for name, amounts in top],
                    "count": len([i for i in pending if (i.amount - paid.get(i.id, Decimal("0"))) > 0]),
                },
            }
        )

    # 2. Runway
    forecast = build_forecast(workspace, today)
    for c in CURRENCIES:
        rw = forecast["runway_months"][c]
        if isinstance(rw, (int, float)):
            severity = "critical" if rw < 3 else ("warning" if rw < 6 else None)
            if severity:
                insights.append(
                    {"kind": "low_runway", "severity": severity, "data": {"currency": c, "months": rw}}
                )
    if all(forecast["cash"][c] is None for c in CURRENCIES):
        insights.append({"kind": "no_cash_snapshot", "severity": "info", "data": {}})

    # 3. Client concentration (last 6 months of payments, per currency)
    six_start = date(*_add_months(today.year, today.month, -5), 1)
    by_client = defaultdict(_zero)
    total_6m = _zero()
    for p in Payment.objects.filter(workspace=workspace, paid_at__gte=six_start).select_related("project"):
        if p.currency in CURRENCIES:
            by_client[p.project.name][p.currency] += p.amount
            total_6m[p.currency] += p.amount
    for c in CURRENCIES:
        if total_6m[c] <= 0:
            continue
        for name, amounts in by_client.items():
            share = float(amounts[c] / total_6m[c])
            if share > CONCENTRATION_THRESHOLD:
                insights.append(
                    {
                        "kind": "client_concentration",
                        "severity": "warning",
                        "data": {"client": name, "currency": c, "share": round(share * 100), "amount": float(amounts[c])},
                    }
                )

    # 4. Upcoming retainer renewals
    horizon = today + timedelta(days=RENEWAL_WINDOW_DAYS)
    for con in Contract.objects.filter(
        workspace=workspace, kind="retainer", status="active", end_date__isnull=False,
        end_date__gte=today, end_date__lte=horizon,
    ).select_related("project"):
        insights.append(
            {
                "kind": "renewal_due",
                "severity": "warning",
                "data": {
                    "client": con.project.name,
                    "project_id": str(con.project_id),
                    "contract": con.name,
                    "end_date": con.end_date.isoformat(),
                    "amount": float(con.amount),
                    "currency": con.currency,
                },
            }
        )

    # 5. Negative margin last closed month (only meaningful if expenses captured)
    ly, lm = _add_months(today.year, today.month, -1)
    last_key = f"{ly:04d}-{lm:02d}"
    pnl = build_pnl(workspace, today, months=2)
    last_row = next((r for r in pnl["months"] if r["month"] == last_key), None)
    if last_row:
        for c in CURRENCIES:
            cell = last_row[c]
            if cell["expenses"] > 0 and cell["net"] < 0:
                insights.append(
                    {
                        "kind": "negative_margin",
                        "severity": "warning",
                        "data": {"month": last_key, "currency": c, "net": cell["net"]},
                    }
                )

    # 6. Expenses not captured for the last closed month
    if not ExpenseEntry.objects.filter(workspace=workspace, month=last_key).exists():
        insights.append({"kind": "missing_expenses", "severity": "info", "data": {"month": last_key}})

    order = {"critical": 0, "warning": 1, "info": 2}
    insights.sort(key=lambda i: order[i["severity"]])
    return {"insights": insights}
