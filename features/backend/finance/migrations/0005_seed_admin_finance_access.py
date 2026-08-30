# Data migration: workspace admins used to have IMPLICIT full finance access.
# That implicit rule is gone (an admin can now exist without finance access),
# so this seeds an explicit "finance" row for every active admin at upgrade
# time — nobody loses access on deploy; admins can then be stripped from the
# members page like anyone else. Reverse is a no-op on purpose: rows are data
# the user may have edited afterwards. (AGPL-3.0-only)

from django.db import migrations


def seed_admin_access(apps, schema_editor):
    FinanceAccess = apps.get_model("finance", "FinanceAccess")
    WorkspaceMember = apps.get_model("db", "WorkspaceMember")

    ADMIN_ROLE = 20
    for wm in WorkspaceMember.objects.filter(role=ADMIN_ROLE, is_active=True):
        exists = FinanceAccess.objects.filter(
            workspace_id=wm.workspace_id, member_id=wm.member_id, deleted_at__isnull=True
        ).exists()
        if not exists:
            FinanceAccess.objects.create(
                workspace_id=wm.workspace_id, member_id=wm.member_id, role="finance"
            )


class Migration(migrations.Migration):

    dependencies = [
        ("db", "0122_alter_draftissue_assignees_alter_issue_assignees_and_more"),
        ("finance", "0004_financeaccess_role"),
    ]

    operations = [
        migrations.RunPython(seed_admin_access, migrations.RunPython.noop),
    ]
