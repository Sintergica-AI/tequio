# Sintergica CE extension: fix — the workspace-level name uniqueness must
# exclude DMs: every DM has name "" and project NULL, so the SECOND DM in a
# workspace violated the constraint (hit in production as soon as a real DM
# existed). GENERATED inside the image; db dependency pinned to 0122 (the
# generator points at the phantom db.0123, see 0001).

import django.db.models.functions.text
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('chat', '0002_channel_dm_key_channel_is_direct_and_more'),
        ('db', '0122_alter_draftissue_assignees_alter_issue_assignees_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='channel',
            name='chat_channel_workspace_name_uq',
        ),
        migrations.AddConstraint(
            model_name='channel',
            constraint=models.UniqueConstraint(django.db.models.functions.text.Lower('name'), models.F('workspace'), condition=models.Q(('deleted_at__isnull', True), ('is_direct', False), ('project__isnull', True)), name='chat_channel_workspace_name_uq'),
        ),
    ]
