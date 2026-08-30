# Sintergica CE extension: the assistant's read-only tools (phase 1).
#
# Every tool is a plain function over the ORM. Two invariants hold for all of
# them, and both are enforced here rather than in the prompt:
#
#   1. Scope. Queries are restricted to ctx.project_ids — the projects where
#      the requesting user is an active member. The model cannot widen this by
#      asking; an unknown or unreachable project simply resolves to nothing.
#   2. Size. Every result is capped and every free-text field truncated. An
#      unbounded tool result is the fastest way to blow the context window and
#      the bill on a single question.
#
# Going through the ORM instead of the MCP server is deliberate: MCP
# authenticates with a fixed X-API-Key, i.e. always the same identity, which is
# wrong for a per-user chat.

from dataclasses import dataclass, field

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Case, Count, IntegerField, Q, Value, When
from django.utils import timezone

from plane.db.models import (
    Cycle,
    CycleIssue,
    Issue,
    IssueComment,
    IssueLink,
    IssueRelation,
    Module,
    ModuleIssue,
    Page,
    Project,
    ProjectMember,
    ProjectPage,
    WorkspaceMember,
)

MAX_LIMIT = 100
DEFAULT_LIMIT = 25
DESCRIPTION_CHARS = 4000
COMMENT_CHARS = 1500
MAX_COMMENTS = 15

PRIORITIES = ("urgent", "high", "medium", "low", "none")

PRIORITY_ORDER = Case(
    *[When(priority=p, then=Value(i)) for i, p in enumerate(PRIORITIES)],
    default=Value(len(PRIORITIES)),
    output_field=IntegerField(),
)
STATE_GROUPS = ("backlog", "unstarted", "started", "completed", "cancelled")


class ToolError(Exception):
    """Raised for bad arguments. The message goes back to the model as the tool
    result so it can correct itself instead of the turn dying."""


@dataclass
class ToolContext:
    user: object
    workspace: object
    slug: str
    project_ids: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _truncate(text, limit):
    if not text:
        return ""
    text = str(text)
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n…[truncado, {len(text) - limit} caracteres más]"


def _clamp_limit(limit):
    try:
        limit = int(limit or DEFAULT_LIMIT)
    except (TypeError, ValueError):
        return DEFAULT_LIMIT
    return max(1, min(limit, MAX_LIMIT))


def _resolve_project(ctx, value):
    """Accept a project id, its identifier (SIN) or its name, case-insensitive."""
    if not value:
        return None
    value = str(value).strip()
    qs = Project.objects.filter(id__in=ctx.project_ids)
    for lookup in ("identifier__iexact", "name__iexact", "name__icontains"):
        project = qs.filter(**{lookup: value}).first()
        if project:
            return project
    # Last resort: a raw uuid. An unparseable value raises ValidationError,
    # which just means "not a project id" — not an error worth surfacing.
    try:
        return qs.filter(id=value).first()
    except (ValueError, TypeError, DjangoValidationError):
        return None


def _resolve_user(ctx, value):
    """'me' or a display name / email of an active workspace member."""
    if not value:
        return None
    if str(value).lower() in ("me", "yo", "mi", "myself"):
        return ctx.user
    members = WorkspaceMember.objects.filter(
        workspace=ctx.workspace, is_active=True
    ).select_related("member")
    value = str(value).strip().lower()
    for wm in members:
        m = wm.member
        if value in (
            (m.email or "").lower(),
            (m.display_name or "").lower(),
            f"{m.first_name or ''} {m.last_name or ''}".strip().lower(),
        ):
            return m
    for wm in members:
        m = wm.member
        haystack = f"{m.first_name or ''} {m.last_name or ''} {m.display_name or ''}".lower()
        if value and value in haystack:
            return m
    return None


def _person(user):
    if not user:
        return None
    name = f"{user.first_name or ''} {user.last_name or ''}".strip()
    return name or user.display_name or user.email


def _issue_url(ctx, issue):
    return f"/{ctx.slug}/projects/{issue.project_id}/issues/{issue.id}"


def _base_issue_qs(ctx):
    return Issue.issue_objects.filter(project_id__in=ctx.project_ids).select_related(
        "state", "project"
    )


def _brief(ctx, issue):
    return {
        "identifier": f"{issue.project.identifier}-{issue.sequence_id}",
        "name": issue.name,
        "project": issue.project.name,
        "state": issue.state.name if issue.state else None,
        "state_group": issue.state.group if issue.state else None,
        "priority": issue.priority,
        "assignees": [_person(a) for a in issue.assignees.all()],
        "start_date": issue.start_date.isoformat() if issue.start_date else None,
        "target_date": issue.target_date.isoformat() if issue.target_date else None,
        "url": _issue_url(ctx, issue),
    }


# ---------------------------------------------------------------------------
# tools
# ---------------------------------------------------------------------------


def whoami(ctx):
    role = (
        WorkspaceMember.objects.filter(
            member=ctx.user, workspace=ctx.workspace, is_active=True
        )
        .values_list("role", flat=True)
        .first()
    )
    role_name = {20: "admin", 15: "member", 5: "guest"}.get(role, "unknown")
    assigned = _base_issue_qs(ctx).filter(assignees=ctx.user)
    today = timezone.now().date()
    return {
        "name": _person(ctx.user),
        "email": ctx.user.email,
        "workspace": ctx.workspace.name,
        "workspace_role": role_name,
        "timezone": getattr(ctx.user, "user_timezone", None),
        "today": today.isoformat(),
        "projects": list(
            Project.objects.filter(id__in=ctx.project_ids).values_list("name", flat=True)
        ),
        "assigned_open": assigned.exclude(
            state__group__in=["completed", "cancelled"]
        ).count(),
        "assigned_overdue": assigned.exclude(state__group__in=["completed", "cancelled"])
        .filter(target_date__lt=today)
        .count(),
    }


def list_projects(ctx):
    out = []
    for p in Project.objects.filter(id__in=ctx.project_ids).order_by("name"):
        out.append(
            {
                "name": p.name,
                "identifier": p.identifier,
                "description": _truncate(p.description, 300),
                "url": f"/{ctx.slug}/projects/{p.id}/issues",
            }
        )
    return {"projects": out, "count": len(out)}


def search_work_items(
    ctx,
    query=None,
    project=None,
    assignee=None,
    state=None,
    state_group=None,
    priority=None,
    label=None,
    cycle=None,
    module=None,
    target_date_before=None,
    target_date_after=None,
    overdue=None,
    unassigned=None,
    limit=None,
):
    if not ctx.project_ids:
        return {"work_items": [], "count": 0, "note": "El usuario no es miembro de ningún proyecto."}

    qs = _base_issue_qs(ctx).prefetch_related("assignees")
    applied = {}

    if project:
        p = _resolve_project(ctx, project)
        if not p:
            raise ToolError(f"No encuentro un proyecto accesible llamado '{project}'.")
        qs = qs.filter(project=p)
        applied["project"] = p.name

    if query:
        qs = qs.filter(Q(name__icontains=query) | Q(description_stripped__icontains=query))
        applied["query"] = query

    if assignee:
        u = _resolve_user(ctx, assignee)
        if not u:
            raise ToolError(f"No encuentro a un miembro llamado '{assignee}'.")
        qs = qs.filter(assignees=u)
        applied["assignee"] = _person(u)

    if unassigned:
        qs = qs.filter(assignees__isnull=True)
        applied["unassigned"] = True

    if state_group:
        groups = [state_group] if isinstance(state_group, str) else list(state_group)
        bad = [g for g in groups if g not in STATE_GROUPS]
        if bad:
            raise ToolError(f"state_group inválido {bad}. Valores: {', '.join(STATE_GROUPS)}.")
        qs = qs.filter(state__group__in=groups)
        applied["state_group"] = groups

    if state:
        qs = qs.filter(state__name__iexact=state)
        applied["state"] = state

    if priority:
        prios = [priority] if isinstance(priority, str) else list(priority)
        bad = [p for p in prios if p not in PRIORITIES]
        if bad:
            raise ToolError(f"priority inválida {bad}. Valores: {', '.join(PRIORITIES)}.")
        qs = qs.filter(priority__in=prios)
        applied["priority"] = prios

    if label:
        qs = qs.filter(labels__name__iexact=label)
        applied["label"] = label

    if cycle:
        if str(cycle).lower() in ("current", "actual", "activo", "active"):
            now = timezone.now()
            cyc = Cycle.objects.filter(
                project_id__in=ctx.project_ids, start_date__lte=now, end_date__gte=now
            ).first()
        else:
            cyc = Cycle.objects.filter(
                project_id__in=ctx.project_ids, name__icontains=str(cycle)
            ).first()
        if not cyc:
            raise ToolError(f"No encuentro un ciclo '{cycle}'.")
        qs = qs.filter(id__in=CycleIssue.objects.filter(cycle=cyc).values("issue_id"))
        applied["cycle"] = cyc.name

    if module:
        mod = Module.objects.filter(
            project_id__in=ctx.project_ids, name__icontains=str(module)
        ).first()
        if not mod:
            raise ToolError(f"No encuentro un módulo '{module}'.")
        qs = qs.filter(id__in=ModuleIssue.objects.filter(module=mod).values("issue_id"))
        applied["module"] = mod.name

    if overdue:
        qs = qs.filter(
            target_date__lt=timezone.now().date()
        ).exclude(state__group__in=["completed", "cancelled"])
        applied["overdue"] = True

    if target_date_before:
        qs = qs.filter(target_date__lte=target_date_before)
        applied["target_date_before"] = target_date_before

    if target_date_after:
        qs = qs.filter(target_date__gte=target_date_after)
        applied["target_date_after"] = target_date_after

    limit = _clamp_limit(limit)
    total = qs.distinct().count()
    # priority es CharField: ordenar por el campo da urgent, none, medium, low,
    # high (alfabético). Hay que mapearlo a un peso explícito.
    items = (
        qs.distinct()
        .annotate(priority_rank=PRIORITY_ORDER)
        .order_by("target_date", "priority_rank", "-created_at")[:limit]
    )

    result = {
        "work_items": [_brief(ctx, i) for i in items],
        "count": total,
        "returned": min(total, limit),
        "filters": applied,
    }
    if total > limit:
        result["note"] = (
            f"Hay {total} resultados y se devuelven {limit}. Afina los filtros "
            f"o usa work_item_stats si sólo necesitas conteos."
        )
    return result


def resolve_issue(ctx, identifier):
    """Un work item por su identificador legible (SIN-123) o su UUID, siempre
    dentro del alcance del usuario. Compartido con las herramientas de
    escritura, que necesitan resolverlo antes de proponer un cambio."""
    if not identifier:
        raise ToolError("Falta 'identifier' (por ejemplo SIN-123).")
    issue = None
    raw = str(identifier).strip()
    if "-" in raw:
        prefix, _, seq = raw.rpartition("-")
        if seq.isdigit():
            issue = (
                _base_issue_qs(ctx)
                .filter(project__identifier__iexact=prefix, sequence_id=int(seq))
                .first()
            )
    if issue is None:
        # Un identificador que no es UUID hace que Django lance ValidationError
        # al construir el filtro, no ValueError: significa "no es un id", que
        # aquí es un caso normal y termina en el ToolError de abajo.
        try:
            issue = _base_issue_qs(ctx).filter(id=raw).first()
        except (ValueError, TypeError, DjangoValidationError):
            issue = None
    if issue is None:
        raise ToolError(
            f"No encuentro el work item '{identifier}' entre los proyectos del usuario."
        )
    return issue


def get_work_item(ctx, identifier):
    issue = resolve_issue(ctx, identifier)

    cycle = (
        CycleIssue.objects.filter(issue=issue).select_related("cycle").first()
    )
    modules = list(
        ModuleIssue.objects.filter(issue=issue)
        .select_related("module")
        .values_list("module__name", flat=True)
    )
    comments = (
        IssueComment.objects.filter(issue=issue)
        .select_related("actor")
        .order_by("-created_at")[:MAX_COMMENTS]
    )
    links = list(IssueLink.objects.filter(issue=issue).values("title", "url"))
    relations = [
        {
            "type": r.relation_type,
            "with": f"{r.related_issue.project.identifier}-{r.related_issue.sequence_id}",
        }
        for r in IssueRelation.objects.filter(issue=issue).select_related(
            "related_issue", "related_issue__project"
        )
    ]
    children = [
        _brief(ctx, c) for c in _base_issue_qs(ctx).filter(parent=issue).prefetch_related("assignees")
    ]

    data = _brief(ctx, issue)
    data.update(
        {
            "description": _truncate(issue.description_stripped, DESCRIPTION_CHARS),
            "labels": [lbl.name for lbl in issue.labels.all()],
            "cycle": cycle.cycle.name if cycle else None,
            "modules": modules,
            "created_at": issue.created_at.isoformat(),
            "updated_at": issue.updated_at.isoformat(),
            "completed_at": issue.completed_at.isoformat() if issue.completed_at else None,
            "parent": (
                f"{issue.parent.project.identifier}-{issue.parent.sequence_id}"
                if issue.parent_id
                else None
            ),
            "sub_items": children,
            "links": links,
            "relations": relations,
            "comments": [
                {
                    "author": _person(c.actor),
                    "at": c.created_at.isoformat(),
                    "text": _truncate(c.comment_stripped, COMMENT_CHARS),
                }
                for c in reversed(list(comments))
            ],
        }
    )
    return data


def list_cycles(ctx, project=None):
    qs = Cycle.objects.filter(project_id__in=ctx.project_ids).select_related("project")
    if project:
        p = _resolve_project(ctx, project)
        if not p:
            raise ToolError(f"No encuentro un proyecto accesible llamado '{project}'.")
        qs = qs.filter(project=p)
    now = timezone.now()
    out = []
    for c in qs.order_by("-start_date")[:MAX_LIMIT]:
        if c.start_date and c.end_date:
            status = (
                "current"
                if c.start_date <= now <= c.end_date
                else ("upcoming" if c.start_date > now else "completed")
            )
        else:
            status = "draft"
        total = CycleIssue.objects.filter(cycle=c).count()
        done = CycleIssue.objects.filter(
            cycle=c, issue__state__group="completed"
        ).count()
        out.append(
            {
                "name": c.name,
                "project": c.project.name,
                "status": status,
                "start_date": c.start_date.date().isoformat() if c.start_date else None,
                "end_date": c.end_date.date().isoformat() if c.end_date else None,
                "work_items": total,
                "completed": done,
            }
        )
    return {"cycles": out, "count": len(out)}


def list_modules(ctx, project=None):
    qs = Module.objects.filter(project_id__in=ctx.project_ids).select_related(
        "project", "lead"
    )
    if project:
        p = _resolve_project(ctx, project)
        if not p:
            raise ToolError(f"No encuentro un proyecto accesible llamado '{project}'.")
        qs = qs.filter(project=p)
    out = []
    for m in qs.order_by("name")[:MAX_LIMIT]:
        total = ModuleIssue.objects.filter(module=m).count()
        done = ModuleIssue.objects.filter(
            module=m, issue__state__group="completed"
        ).count()
        out.append(
            {
                "name": m.name,
                "project": m.project.name,
                "status": m.status,
                "lead": _person(m.lead),
                "start_date": m.start_date.isoformat() if m.start_date else None,
                "target_date": m.target_date.isoformat() if m.target_date else None,
                "work_items": total,
                "completed": done,
            }
        )
    return {"modules": out, "count": len(out)}


def list_members(ctx, project=None):
    if project:
        p = _resolve_project(ctx, project)
        if not p:
            raise ToolError(f"No encuentro un proyecto accesible llamado '{project}'.")
        rows = ProjectMember.objects.filter(project=p, is_active=True).select_related("member")
    else:
        rows = WorkspaceMember.objects.filter(
            workspace=ctx.workspace, is_active=True
        ).select_related("member")
    role_name = {20: "admin", 15: "member", 5: "guest"}
    out = [
        {
            "name": _person(r.member),
            "email": r.member.email,
            "role": role_name.get(r.role, str(r.role)),
        }
        for r in rows
    ]
    return {"members": out, "count": len(out)}


def work_item_stats(ctx, project=None, group_by="state", assignee=None):
    """Aggregate counts. Use this instead of listing hundreds of items."""
    if group_by not in ("state", "priority", "assignee", "project", "state_group"):
        raise ToolError(
            "group_by debe ser uno de: state, state_group, priority, assignee, project."
        )
    qs = _base_issue_qs(ctx)
    if project:
        p = _resolve_project(ctx, project)
        if not p:
            raise ToolError(f"No encuentro un proyecto accesible llamado '{project}'.")
        qs = qs.filter(project=p)
    if assignee:
        u = _resolve_user(ctx, assignee)
        if not u:
            raise ToolError(f"No encuentro a un miembro llamado '{assignee}'.")
        qs = qs.filter(assignees=u)

    field_map = {
        "state": "state__name",
        "state_group": "state__group",
        "priority": "priority",
        "project": "project__name",
        "assignee": "assignees__display_name",
    }
    rows = (
        qs.values(field_map[group_by])
        .annotate(count=Count("id", distinct=True))
        .order_by("-count")
    )
    today = timezone.now().date()
    return {
        "group_by": group_by,
        "buckets": [
            {"key": r[field_map[group_by]] or "sin asignar", "count": r["count"]}
            for r in rows
        ],
        "total": qs.distinct().count(),
        "overdue": qs.exclude(state__group__in=["completed", "cancelled"])
        .filter(target_date__lt=today)
        .distinct()
        .count(),
    }


def search_pages(ctx, query, project=None, limit=None):
    if not query:
        raise ToolError("Falta 'query'.")
    limit = _clamp_limit(limit)
    project_page_ids = ProjectPage.objects.filter(
        project_id__in=ctx.project_ids
    ).values("page_id")

    qs = Page.objects.filter(
        Q(workspace=ctx.workspace),
        Q(name__icontains=query) | Q(description_stripped__icontains=query),
        archived_at__isnull=True,
    ).filter(
        Q(is_global=True) | Q(id__in=project_page_ids)
    ).filter(
        Q(access=0) | Q(owned_by=ctx.user)
    )
    if project:
        p = _resolve_project(ctx, project)
        if not p:
            raise ToolError(f"No encuentro un proyecto accesible llamado '{project}'.")
        qs = qs.filter(id__in=ProjectPage.objects.filter(project=p).values("page_id"))

    pages = list(qs.select_related("owned_by").order_by("-updated_at")[:limit])
    # Una página de proyecto vive en /<slug>/projects/<project_id>/pages/<id>:
    # sin el project id el enlace apunta a una ruta inexistente.
    owning_project = dict(
        ProjectPage.objects.filter(page_id__in=[p.id for p in pages]).values_list(
            "page_id", "project_id"
        )
    )

    out = []
    for page in pages:
        if page.is_global:
            url = f"/{ctx.slug}/wiki/{page.id}"
        elif page.id in owning_project:
            url = f"/{ctx.slug}/projects/{owning_project[page.id]}/pages/{page.id}"
        else:
            url = None
        out.append(
            {
                "name": page.name or "(sin título)",
                "scope": "wiki" if page.is_global else "proyecto",
                "owner": _person(page.owned_by),
                "updated_at": page.updated_at.isoformat(),
                "excerpt": _truncate(page.description_stripped, 600),
                "url": url,
            }
        )
    return {"pages": out, "count": len(out)}
