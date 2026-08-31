# Sintergica CE extension: chat tables. Additive only — no Plane table is
# altered. GENERATED inside the built image with `manage.py makemigrations
# chat` (like the finance migrations) so the constraint/index deconstruction
# matches Django exactly — a hand-written 0001 failed the --check gate over
# Q() kwarg ordering. Two manual edits: this header, and the db dependency
# pinned to 0122 (the generator pointed at db.0123_alter_profile_language,
# which is the deliberate no-migration language patch and does not exist as a
# file).


import django.db.models.deletion
import django.db.models.functions.text
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('db', '0122_alter_draftissue_assignees_alter_issue_assignees_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Channel',
            fields=[
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Created At')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Last Modified At')),
                ('deleted_at', models.DateTimeField(blank=True, null=True, verbose_name='Deleted At')),
                ('id', models.UUIDField(db_index=True, default=uuid.uuid4, editable=False, primary_key=True, serialize=False, unique=True)),
                ('name', models.CharField(max_length=255)),
                ('description', models.TextField(blank=True, default='')),
                ('is_general', models.BooleanField(default=False)),
                ('access', models.PositiveSmallIntegerField(default=0)),
                ('archived_at', models.DateTimeField(blank=True, null=True)),
                ('created_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(class)s_created_by', to=settings.AUTH_USER_MODEL, verbose_name='Created By')),
                ('project', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='chat_channels', to='db.project')),
                ('updated_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(class)s_updated_by', to=settings.AUTH_USER_MODEL, verbose_name='Last Modified By')),
                ('workspace', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='chat_channels', to='db.workspace')),
            ],
            options={
                'verbose_name': 'Chat Channel',
                'verbose_name_plural': 'Chat Channels',
                'db_table': 'chat_channels',
                'ordering': ('name',),
            },
        ),
        migrations.CreateModel(
            name='ChannelMember',
            fields=[
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Created At')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Last Modified At')),
                ('deleted_at', models.DateTimeField(blank=True, null=True, verbose_name='Deleted At')),
                ('id', models.UUIDField(db_index=True, default=uuid.uuid4, editable=False, primary_key=True, serialize=False, unique=True)),
                ('last_read_at', models.DateTimeField(blank=True, null=True)),
                ('is_muted', models.BooleanField(default=False)),
                ('channel', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='members', to='chat.channel')),
                ('created_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(class)s_created_by', to=settings.AUTH_USER_MODEL, verbose_name='Created By')),
                ('member', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='chat_channel_memberships', to=settings.AUTH_USER_MODEL)),
                ('updated_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(class)s_updated_by', to=settings.AUTH_USER_MODEL, verbose_name='Last Modified By')),
                ('workspace', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='chat_channel_members', to='db.workspace')),
            ],
            options={
                'verbose_name': 'Chat Channel Member',
                'verbose_name_plural': 'Chat Channel Members',
                'db_table': 'chat_channel_members',
                'ordering': ('-created_at',),
            },
        ),
        migrations.CreateModel(
            name='ChatMessage',
            fields=[
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Created At')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Last Modified At')),
                ('deleted_at', models.DateTimeField(blank=True, null=True, verbose_name='Deleted At')),
                ('id', models.UUIDField(db_index=True, default=uuid.uuid4, editable=False, primary_key=True, serialize=False, unique=True)),
                ('message_html', models.TextField(blank=True, default='<p></p>')),
                ('message_json', models.JSONField(blank=True, null=True)),
                ('message_stripped', models.TextField(blank=True, null=True)),
                ('edited_at', models.DateTimeField(blank=True, null=True)),
                ('is_removed', models.BooleanField(default=False)),
                ('actor', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='chat_messages', to=settings.AUTH_USER_MODEL)),
                ('channel', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='messages', to='chat.channel')),
                ('created_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(class)s_created_by', to=settings.AUTH_USER_MODEL, verbose_name='Created By')),
                ('parent', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='replies', to='chat.chatmessage')),
                ('project', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='chat_messages', to='db.project')),
                ('updated_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(class)s_updated_by', to=settings.AUTH_USER_MODEL, verbose_name='Last Modified By')),
                ('workspace', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='chat_messages', to='db.workspace')),
            ],
            options={
                'verbose_name': 'Chat Message',
                'verbose_name_plural': 'Chat Messages',
                'db_table': 'chat_messages',
                'ordering': ('created_at', 'id'),
            },
        ),
        migrations.CreateModel(
            name='MessageReaction',
            fields=[
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Created At')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Last Modified At')),
                ('deleted_at', models.DateTimeField(blank=True, null=True, verbose_name='Deleted At')),
                ('id', models.UUIDField(db_index=True, default=uuid.uuid4, editable=False, primary_key=True, serialize=False, unique=True)),
                ('reaction', models.CharField(max_length=20)),
                ('actor', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='chat_message_reactions', to=settings.AUTH_USER_MODEL)),
                ('created_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(class)s_created_by', to=settings.AUTH_USER_MODEL, verbose_name='Created By')),
                ('message', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='reactions', to='chat.chatmessage')),
                ('updated_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(class)s_updated_by', to=settings.AUTH_USER_MODEL, verbose_name='Last Modified By')),
                ('workspace', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='chat_message_reactions', to='db.workspace')),
            ],
            options={
                'verbose_name': 'Chat Message Reaction',
                'verbose_name_plural': 'Chat Message Reactions',
                'db_table': 'chat_message_reactions',
                'ordering': ('created_at',),
            },
        ),
        migrations.CreateModel(
            name='MessageWorkItemLink',
            fields=[
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Created At')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Last Modified At')),
                ('deleted_at', models.DateTimeField(blank=True, null=True, verbose_name='Deleted At')),
                ('id', models.UUIDField(db_index=True, default=uuid.uuid4, editable=False, primary_key=True, serialize=False, unique=True)),
                ('created_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(class)s_created_by', to=settings.AUTH_USER_MODEL, verbose_name='Created By')),
                ('issue', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='chat_message_links', to='db.issue')),
                ('message', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='work_item_links', to='chat.chatmessage')),
                ('updated_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(class)s_updated_by', to=settings.AUTH_USER_MODEL, verbose_name='Last Modified By')),
                ('workspace', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='chat_work_item_links', to='db.workspace')),
            ],
            options={
                'verbose_name': 'Chat Message Work Item Link',
                'verbose_name_plural': 'Chat Message Work Item Links',
                'db_table': 'chat_message_work_items',
                'ordering': ('created_at',),
            },
        ),
        migrations.AddIndex(
            model_name='channel',
            index=models.Index(fields=['workspace', 'project'], name='chat_channel_scope_idx'),
        ),
        migrations.AddConstraint(
            model_name='channel',
            constraint=models.UniqueConstraint(django.db.models.functions.text.Lower('name'), models.F('workspace'), models.F('project'), condition=models.Q(('deleted_at__isnull', True), ('project__isnull', False)), name='chat_channel_project_name_uq'),
        ),
        migrations.AddConstraint(
            model_name='channel',
            constraint=models.UniqueConstraint(django.db.models.functions.text.Lower('name'), models.F('workspace'), condition=models.Q(('deleted_at__isnull', True), ('project__isnull', True)), name='chat_channel_workspace_name_uq'),
        ),
        migrations.AddConstraint(
            model_name='channel',
            constraint=models.UniqueConstraint(condition=models.Q(('deleted_at__isnull', True), ('is_general', True)), fields=('project',), name='chat_channel_general_uq'),
        ),
        migrations.AddConstraint(
            model_name='channelmember',
            constraint=models.UniqueConstraint(condition=models.Q(('deleted_at__isnull', True)), fields=('channel', 'member'), name='chat_channel_member_uq'),
        ),
        migrations.AddIndex(
            model_name='chatmessage',
            index=models.Index(condition=models.Q(('deleted_at__isnull', True)), fields=['channel', 'created_at'], name='chat_message_channel_ts_idx'),
        ),
        migrations.AddIndex(
            model_name='chatmessage',
            index=models.Index(fields=['parent'], name='chat_message_parent_idx'),
        ),
        migrations.AddConstraint(
            model_name='messagereaction',
            constraint=models.UniqueConstraint(condition=models.Q(('deleted_at__isnull', True)), fields=('message', 'actor', 'reaction'), name='chat_message_reaction_uq'),
        ),
        migrations.AddConstraint(
            model_name='messageworkitemlink',
            constraint=models.UniqueConstraint(condition=models.Q(('deleted_at__isnull', True)), fields=('message', 'issue'), name='chat_message_work_item_uq'),
        ),
    ]
