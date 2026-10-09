from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from core.jwt_serializers import ApuGuardTokenSerializer
from rest_framework_simplejwt.views import TokenObtainPairView

from core.views import (
    # Auth
    MiPerfilView,
    # Usuarios
    UsuarioListCreateView,
    UsuarioDetailView,
    # Técnicos
    TecnicoListCreateView,
    TecnicoDetailView,
    # Alertas
    AlertaListView,
    AlertaDetailView,
    AlertaNotificarView,
    AlertaGeoJsonView,
    AlertaPdfView,
    AlertaEvidenciaView,
    # Sectores / Casos (mapa)
    SectorReservaListView,
    SectorSimpleListView,
    CasoAuditoriaListView,
    AuditoriaDetalleView,
    # Dashboard
    DashboardStatsView,
    AuditLogListView,
    # Sesión
    LogoutView,
    # Pipeline
    PipelineTriggerView,
    # Reportes
    ReporteListView,
)


class ApuGuardTokenView(TokenObtainPairView):
    serializer_class = ApuGuardTokenSerializer


urlpatterns = [

    # -- Autenticación JWT --
    path("auth/token/",         ApuGuardTokenView.as_view(),  name="token_obtain_pair"),
    path("auth/token/refresh/", TokenRefreshView.as_view(),   name="token_refresh"),
    path("auth/logout/",        LogoutView.as_view(),         name="logout"),

    # -- Perfil del usuario autenticado --
    path("usuarios/me/",        MiPerfilView.as_view(),        name="mi-perfil"),

    # -- Gestión de usuarios (admin) --
    path("usuarios/",           UsuarioListCreateView.as_view(), name="usuarios-list"),
    path("usuarios/<int:pk>/",  UsuarioDetailView.as_view(),     name="usuarios-detail"),

    # -- Técnicos de campo (admin) --
    path("tecnicos/",           TecnicoListCreateView.as_view(), name="tecnicos-list"),
    path("tecnicos/<int:pk>/",  TecnicoDetailView.as_view(),     name="tecnicos-detail"),

    # -- Alertas (CasoAuditoria simplificado) --
    path("alertas/",                          AlertaListView.as_view(),      name="alertas-list"),
    path("alertas/<int:pk>/",                 AlertaDetailView.as_view(),    name="alertas-detail"),
    path("alertas/<int:pk>/notificar/",       AlertaNotificarView.as_view(), name="alertas-notificar"),
    path("alertas/<int:pk>/geojson/",         AlertaGeoJsonView.as_view(),   name="alertas-geojson"),
    path("alertas/<int:pk>/pdf/",             AlertaPdfView.as_view(),       name="alertas-pdf"),
    path("alertas/<int:pk>/evidencia/",       AlertaEvidenciaView.as_view(), name="alertas-evidencia"),

    # -- Mapa (GeoJSON sectores y casos) --
    path("sectores/simple/",           SectorSimpleListView.as_view(),   name="sectores-simple"),
    path("sectores/",                  SectorReservaListView.as_view(),  name="sectores-list"),
    path("casos/",                     CasoAuditoriaListView.as_view(),  name="casos-list"),
    path("auditoria/<int:caso_id>/",   AuditoriaDetalleView.as_view(),   name="auditoria-detalle"),

    # -- Dashboard --
    path("dashboard/stats/",   DashboardStatsView.as_view(),  name="dashboard-stats"),
    path("dashboard/audit-logs/", AuditLogListView.as_view(), name="dashboard-audit-logs"),

    # -- Pipeline manual (admin) --
    path("pipeline/trigger/",  PipelineTriggerView.as_view(), name="pipeline-trigger"),

    # -- Reportes mensuales (admin) --
    path("reportes/",          ReporteListView.as_view(),     name="reportes-list"),
]
