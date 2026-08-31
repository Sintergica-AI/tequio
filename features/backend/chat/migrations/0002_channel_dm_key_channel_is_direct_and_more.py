# Sintergica CE extension: chat v2 — DMs (is_direct, dm_key), private
# channels (name now blank-able) and pinned messages. GENERATED inside the
# image (see 0001); db dependency pinned to 0122 for the same reason (the
# generator points at the language patch's phantom db.0123).


import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('chat', '0001_initial'),
        ('db', '0122_alter_draftissue_assignees_alter_issue_assignees_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='channel',
            name='dm_key',
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
        migrations.AddField(
            model_name='channel',
            name='is_direct',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='chatmessage',
            name='pinned_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='chatmessage',
            name='pinned_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='chat_pinned_messages', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterField(
            model_name='channel',
            name='name',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
        migrations.AddConstraint(
            model_name='channel',
            constraint=models.UniqueConstraint(condition=models.Q(('deleted_at__isnull', True), ('dm_key__isnull', False)), fields=('workspace', 'dm_key'), name='chat_channel_dm_key_uq'),
        ),
    ]
