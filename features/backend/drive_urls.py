# Sintergica CE extension: URL routes for the file manager ("Drive").

from django.urls import path

from plane.app.views.drive_ext import (
    WorkspaceDriveEndpoint,
    WorkspaceDriveAssetEndpoint,
    ProjectDriveEndpoint,
    ProjectDriveAssetEndpoint,
)

urlpatterns = [
    path(
        "workspaces/<str:slug>/drive/",
        WorkspaceDriveEndpoint.as_view(),
        name="workspace-drive",
    ),
    path(
        "workspaces/<str:slug>/drive/<uuid:asset_id>/",
        WorkspaceDriveAssetEndpoint.as_view(),
        name="workspace-drive-asset",
    ),
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/drive/",
        ProjectDriveEndpoint.as_view(),
        name="project-drive",
    ),
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/drive/<uuid:asset_id>/",
        ProjectDriveAssetEndpoint.as_view(),
        name="project-drive-asset",
    ),
]
