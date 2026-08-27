# Sintergica CE extension: URL patterns for pages / features / collections
# on the public API. Paths mirror what plane-sdk expects.

from django.urls import path

from plane.api.views.page_ext import (
    CollectionAPIEndpoint,
    ProjectFeatureAPIEndpoint,
    ProjectPageAPIEndpoint,
    ProjectPageArchiveAPIEndpoint,
    WorkItemPageAPIEndpoint,
    WorkspaceFeatureAPIEndpoint,
    WorkspacePageAPIEndpoint,
    WorkspacePageArchiveAPIEndpoint,
)

urlpatterns = [
    # Workspace pages
    path(
        "workspaces/<str:slug>/pages/",
        WorkspacePageAPIEndpoint.as_view(),
        name="ext-workspace-pages",
    ),
    path(
        "workspaces/<str:slug>/pages/<uuid:page_id>/",
        WorkspacePageAPIEndpoint.as_view(),
        name="ext-workspace-page-detail",
    ),
    path(
        "workspaces/<str:slug>/pages/<uuid:page_id>/archive/",
        WorkspacePageArchiveAPIEndpoint.as_view(),
        name="ext-workspace-page-archive",
    ),
    # Project pages
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/pages/",
        ProjectPageAPIEndpoint.as_view(),
        name="ext-project-pages",
    ),
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/pages/<uuid:page_id>/",
        ProjectPageAPIEndpoint.as_view(),
        name="ext-project-page-detail",
    ),
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/pages/<uuid:page_id>/archive/",
        ProjectPageArchiveAPIEndpoint.as_view(),
        name="ext-project-page-archive",
    ),
    # Features
    path(
        "workspaces/<str:slug>/features/",
        WorkspaceFeatureAPIEndpoint.as_view(),
        name="ext-workspace-features",
    ),
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/features/",
        ProjectFeatureAPIEndpoint.as_view(),
        name="ext-project-features",
    ),
    # Collections (CE stub)
    path(
        "workspaces/<str:slug>/collections/",
        CollectionAPIEndpoint.as_view(),
        name="ext-collections",
    ),
    path(
        "workspaces/<str:slug>/collections/<uuid:collection_id>/",
        CollectionAPIEndpoint.as_view(),
        name="ext-collection-detail",
    ),
    path(
        "workspaces/<str:slug>/collections/<uuid:collection_id>/<str:extra>/",
        CollectionAPIEndpoint.as_view(),
        name="ext-collection-extra",
    ),
    # Work-item pages (CE stub)
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/work-items/<uuid:work_item_id>/pages/",
        WorkItemPageAPIEndpoint.as_view(),
        name="ext-workitem-pages",
    ),
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/work-items/<uuid:work_item_id>/pages/<uuid:page_id>/",
        WorkItemPageAPIEndpoint.as_view(),
        name="ext-workitem-page-detail",
    ),
]
