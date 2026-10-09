"""
views.py - APU GUARD Core
===========================
Endpoints REST para la capa de API del frontend.

GET  /api/sectores/                   -> GeoJSON sectores (filtrado por rol)
GET  /api/casos/                      -> GeoJSON casos de auditoria (con filtros)
GET  /api/auditoria/<caso_id>/        -> Detalle caso + URLs presignadas S3
PATCH /api/auditoria/<caso_id>/       -> Veredicto humano (solo Administrador)
"""

import logging

import boto3

import shutil

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.admin.models import ADDITION, CHANGE, DELETION, LogEntry
from django.db.models import IntegerField, Value
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, generics, status, serializers
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import (
    CapturaSatelital,
    CasoAuditoria,
    DocumentoReporte,
    PerfilAnalista,
    SectorReserva,
    TecnicoCampo,
)

from core.permissions import IsAdministrador, IsTecnicoOAdministrador
from core.audit import registrar_actividad
from core.serializers import (
    AlertaPatchSerializer,
    AlertaSerializer,
    CasoAuditoriaDetalleSerializer,
    CasoAuditoriaSerializer,
    CasoAuditoriaVeredictoSerializer,
    DocumentoReporteSerializer,
    SectorReservaSerializer,
    SectorSimpleSerializer,
    TecnicoCampoSerializer,
    UsuarioCreateSerializer,
    UsuarioPatchSerializer,
    UsuarioSerializer,
)
from ml_engine.tasks import _enlazar_sectores_y_alertar

from .serializers import AuditLogSerializer

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Filtros
# ---------------------------------------------------------------------------

def _sectores_ids_para_usuario(user):
    """
    Devuelve el queryset de IDs de sectores accesibles para el usuario.
    - Admin/staff: None (sin restricción)
    - TecnicoCampo: sectores asignados al técnico
    - Analista (PerfilAnalista): sectores asignados al perfil analista
    - Sin perfil: set vacío
    """
    if user.is_staff or user.is_superuser:
        return None  # sin restricción

    if hasattr(user, "tecnico_perfil"):
        return user.tecnico_perfil.sectores.values_list("id", flat=True)

    if hasattr(user, "analista_perfil"):
        return user.analista_perfil.sectores.values_list("id", flat=True)

    return []  # sin acceso



import django_filters

class CasoAuditoriaFilter(django_filters.FilterSet):
    fecha_desde = django_filters.DateFilter(
        field_name="fecha_creacion", lookup_expr="gte"
    )
    fecha_hasta = django_filters.DateFilter(
        field_name="fecha_creacion", lookup_expr="lte"
    )

    class Meta:
        model  = CasoAuditoria
        fields = ["estado_caso", "tipo_caso", "estado_ecologico"]


# ---------------------------------------------------------------------------
# GET /api/sectores/
# ---------------------------------------------------------------------------

class SectorSimpleListView(generics.ListAPIView):
    """
    GET /api/sectores/simple/
    Lista plana [{id, nombre, region, codigo}] — para poblar selects en el frontend.
    """
    serializer_class   = SectorSimpleSerializer
    permission_classes = [IsTecnicoOAdministrador]

    def get_queryset(self):
        return SectorReserva.objects.filter(activo=True).order_by("nombre")


class SectorReservaListView(generics.ListAPIView):
    """
    Retorna GeoJSON FeatureCollection de sectores.
    - Administrador: todos los sectores activos.
    - Tecnico:       solo los sectores asignados a su perfil.
    """
    serializer_class   = SectorReservaSerializer
    permission_classes = [IsTecnicoOAdministrador]

    def get_queryset(self):
        user = self.request.user
        qs   = SectorReserva.objects.filter(activo=True)
        ids  = _sectores_ids_para_usuario(user)

        if ids is None:
            return qs
        if not ids:
            return qs.none()
        return qs.filter(id__in=ids)


# ---------------------------------------------------------------------------
# GET /api/casos/
# ---------------------------------------------------------------------------

class CasoAuditoriaListView(generics.ListAPIView):
    """
    Retorna GeoJSON FeatureCollection de casos de auditoria.
    Filtros disponibles via query params:
      ?estado_caso=MONITOREO_ACTIVO
      ?tipo_caso=DETECCION
      ?estado_ecologico=PERTURBADO
      ?fecha_desde=2024-01-01
      ?fecha_hasta=2024-12-31

    - Administrador: todos los casos.
    - Tecnico:       solo casos que intersectan con sus sectores asignados.
    """
    serializer_class   = CasoAuditoriaSerializer
    permission_classes = [IsTecnicoOAdministrador]
    filterset_class    = CasoAuditoriaFilter

    def get_queryset(self):
        user = self.request.user
        qs   = CasoAuditoria.objects.select_related(
            "parche", "parche__captura"
        ).prefetch_related("sectores")
        ids  = _sectores_ids_para_usuario(user)

        if ids is None:
            return qs
        if not ids:
            return qs.none()
        return qs.filter(sectores__id__in=ids).distinct()


# ---------------------------------------------------------------------------
# GET + PATCH /api/auditoria/<caso_id>/
# ---------------------------------------------------------------------------

class AuditoriaDetalleView(APIView):
    """
    GET  -> Retorna metadata completa del caso + 2 URLs presignadas S3 (15 min).
    PATCH -> Solo Administrador. Cambia estado_caso y opcionalmente dispara SMS.
    """
    permission_classes = [IsTecnicoOAdministrador]

    def _get_caso(self, caso_id, user):
        try:
            caso = CasoAuditoria.objects.select_related(
                "parche", "parche__captura"
            ).prefetch_related("sectores").get(pk=caso_id)
        except CasoAuditoria.DoesNotExist:
            return None

        # Tecnico / Analista: solo puede ver casos en sus sectores
        ids = _sectores_ids_para_usuario(user)
        if ids is not None:
            caso_sectores = set(caso.sectores.values_list("id", flat=True))
            if not set(ids).intersection(caso_sectores):
                return None

        return caso

    def _generar_presigned_urls(self, parche):
        """
        Genera las dos URLs presignadas apuntando a los PNGs depositados por Lambda.

        Convencion de rutas (espejo de sagemaker-outputs/):
          sagemaker-visualizations/captura_{captura_id}/parche_{fila}_{col}_rgb.png
          sagemaker-visualizations/captura_{captura_id}/parche_{fila}_{col}_mask.png
        """
        s3         = boto3.client("s3", region_name=settings.AWS_REGION_NAME)
        bucket     = settings.AWS_S3_BUCKET_NAME
        expiracion = getattr(settings, "S3_PRESIGNED_URL_EXPIRATION", 900)

        captura_id = parche.captura_id
        fila       = parche.fila_idx
        col        = parche.col_idx
        base       = f"sagemaker-visualizations/captura_{captura_id}/parche_{fila}_{col}"

        key_rgb  = f"{base}_rgb.png"
        key_mask = f"{base}_mask.png"

        try:
            url_rgb = s3.generate_presigned_url(
                ClientMethod="get_object",
                Params={"Bucket": bucket, "Key": key_rgb},
                ExpiresIn=expiracion,
            )
        except Exception as e:
            logger.warning(f"[PRESIGNED] No se pudo generar URL RGB: {e}")
            url_rgb = None

        try:
            url_mask = s3.generate_presigned_url(
                ClientMethod="get_object",
                Params={"Bucket": bucket, "Key": key_mask},
                ExpiresIn=expiracion,
            )
        except Exception as e:
            logger.warning(f"[PRESIGNED] No se pudo generar URL mask: {e}")
            url_mask = None

        return url_rgb, url_mask

    def get(self, request, caso_id):
        caso = self._get_caso(caso_id, request.user)
        if caso is None:
            return Response(
                {"detail": "No encontrado."}, status=status.HTTP_404_NOT_FOUND
            )

        url_rgb, url_mask = self._generar_presigned_urls(caso.parche)

        serializer = CasoAuditoriaDetalleSerializer(
            caso,
            context={
                "request": request,
                "url_imagen_satelital": url_rgb,
                "url_capa_ia": url_mask,
            },
        )
        return Response(serializer.data)

    def patch(self, request, caso_id):
        if not (request.user.is_staff or request.user.is_superuser):
            raise PermissionDenied("Solo los administradores pueden emitir veredictos.")

        caso = self._get_caso(caso_id, request.user)
        if caso is None:
            return Response(
                {"detail": "No encontrado."}, status=status.HTTP_404_NOT_FOUND
            )

        serializer = CasoAuditoriaVeredictoSerializer(
            caso, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)

        nuevo_estado = serializer.validated_data.get("estado_caso")
        serializer.save()

        registrar_actividad(
            request.user,
            f"Actualizó el veredicto del caso #{caso.pk} (estado → {caso.get_estado_caso_display()})",
            caso,
            CHANGE,
        )

        # Al pasar a MONITOREO_ACTIVO → IA confirmó detección → SMS al técnico para verificar en campo
        if nuevo_estado == CasoAuditoria.EstadoCaso.MONITOREO_ACTIVO:
            try:
                _enlazar_sectores_y_alertar(caso)
                logger.info(f"[AUDITORIA] SMS despachados para caso {caso_id}")
            except Exception as e:
                logger.error(f"[AUDITORIA] Error despachando SMS para caso {caso_id}: {e}")

        return Response(
            CasoAuditoriaDetalleSerializer(
                caso,
                context={"request": request}
            ).data
        )


# ---------------------------------------------------------------------------
# GET /api/reportes/
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# GET+POST /api/usuarios/    PATCH+DELETE /api/usuarios/<id>/
# GET+PATCH /api/usuarios/me/
# ---------------------------------------------------------------------------

class UsuarioListCreateView(generics.ListCreateAPIView):
    """
    GET  /api/usuarios/ → lista todos los usuarios (solo admin).
    POST /api/usuarios/ → crea un nuevo usuario (solo admin).
    """
    permission_classes = [IsAdministrador]

    def get_queryset(self):
        qs = User.objects.filter(is_active=True).order_by("date_joined")
        rol = self.request.query_params.get("rol")
        if rol == "Administrador":
            qs = qs.filter(is_staff=True)
        elif rol == "Analista":
            qs = qs.filter(is_staff=False)
        return qs

    def get_serializer_class(self):
        return UsuarioCreateSerializer if self.request.method == "POST" else UsuarioSerializer

    def create(self, request, *args, **kwargs):
        serializer = UsuarioCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        registrar_actividad(
            request.user,
            f'Creó el usuario "{user.username}"',
            user,
            ADDITION,
        )
        return Response(UsuarioSerializer(user).data, status=status.HTTP_201_CREATED)


class UsuarioDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    PATCH  /api/usuarios/<id>/ → editar usuario (solo admin).
    DELETE /api/usuarios/<id>/ → desactivar usuario (solo admin, soft-delete).
    """
    permission_classes = [IsAdministrador]
    queryset = User.objects.all()

    def get_serializer_class(self):
        return UsuarioPatchSerializer if self.request.method == "PATCH" else UsuarioSerializer

    def perform_update(self, serializer):
        user = serializer.save()
        registrar_actividad(
            self.request.user,
            f'Actualizó el usuario "{user.username}"',
            user,
            CHANGE,
        )

    def destroy(self, request, *args, **kwargs):
        user = self.get_object()
        user.is_active = False   # soft-delete: no borramos para mantener historial
        user.save(update_fields=["is_active"])
        registrar_actividad(
            request.user,
            f'Desactivó el usuario "{user.username}"',
            user,
            CHANGE,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class MiPerfilView(APIView):
    """
    GET   /api/usuarios/me/ → perfil del usuario autenticado.
    PATCH /api/usuarios/me/ → actualizar nombre, teléfono, email.
    """
    def get(self, request):
        return Response(UsuarioSerializer(request.user).data)

    def patch(self, request):
        serializer = UsuarioPatchSerializer(
            request.user, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        registrar_actividad(
            request.user,
            "Actualizó su perfil",
            request.user,
            CHANGE,
        )
        return Response(UsuarioSerializer(request.user).data)


# ---------------------------------------------------------------------------
# GET+POST /api/tecnicos/    PATCH+DELETE /api/tecnicos/<id>/
# ---------------------------------------------------------------------------

class TecnicoListCreateView(generics.ListCreateAPIView):
    """
    GET  /api/tecnicos/ → lista técnicos de campo.
    POST /api/tecnicos/ → crea técnico (solo admin).
    """
    serializer_class   = TecnicoCampoSerializer
    permission_classes = [IsAdministrador]
    queryset           = TecnicoCampo.objects.prefetch_related("sectores").filter(activo=True)

    def perform_create(self, serializer):
        tecnico = serializer.save()
        registrar_actividad(
            self.request.user,
            f'Creó el contacto "{tecnico.nombre}"',
            tecnico,
            ADDITION,
        )


class TecnicoDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    PATCH  /api/tecnicos/<id>/ → editar técnico (solo admin).
    DELETE /api/tecnicos/<id>/ → desactivar técnico (solo admin).
    """
    serializer_class   = TecnicoCampoSerializer
    permission_classes = [IsAdministrador]
    queryset           = TecnicoCampo.objects.prefetch_related("sectores")

    def perform_update(self, serializer):
        tecnico = serializer.save()
        registrar_actividad(
            self.request.user,
            f'Actualizó el contacto "{tecnico.nombre}"',
            tecnico,
            CHANGE,
        )

    def destroy(self, request, *args, **kwargs):
        tecnico = self.get_object()
        tecnico.activo = False
        tecnico.save(update_fields=["activo"])
        registrar_actividad(
            request.user,
            f'Desactivó el contacto "{tecnico.nombre}"',
            tecnico,
            CHANGE,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# GET /api/alertas/   PATCH /api/alertas/<id>/
# POST /api/alertas/<id>/notificar/
# GET  /api/alertas/<id>/geojson/
# ---------------------------------------------------------------------------

class AlertaListView(generics.ListAPIView):
    """
    GET /api/alertas/ → tabla de alertas para el frontend.
    Mapea CasoAuditoria a la estructura simplificada del mockup.
    Filtros: ?fecha__gte=  ?fecha__lte=  ?zona__icontains=  ?estado=
             ?solo_nuevas=true  (solo casos que nacieron en la ultima pasada)
             ?solo_nuevas=false (todas las alarmas, arrastradas incluidas)
    """
    serializer_class   = AlertaSerializer
    permission_classes = [IsTecnicoOAdministrador]

    @staticmethod
    def ultima_captura_id():
        return (
            CapturaSatelital.objects.order_by("-fecha_adquisicion")
            .values_list("pk", flat=True).first()
        )

    def get_queryset(self):
        user = self.request.user
        ultima = self.ultima_captura_id()
        qs   = CasoAuditoria.objects.prefetch_related(
            "sectores",
            "sms_enviados",
            "sms_enviados__tecnico",
        ).select_related(
            "parche", "parche__captura",
            "captura_nacimiento", "captura_ultima_deteccion",
        ).annotate(
            # constante por fila: el serializer la compara con
            # captura_nacimiento_id para exponer `es_nueva`
            ultima_captura_id=Value(ultima, output_field=IntegerField()),
        ).order_by("-fecha_creacion")
        ids  = _sectores_ids_para_usuario(user)

        if ids is None:
            pass  # admin: sin restriccion
        elif not ids:
            return qs.none()
        else:
            qs = qs.filter(sectores__id__in=ids).distinct()

        # Filtros opcionales
        params = self.request.query_params
        if params.get("fecha__gte"):
            qs = qs.filter(fecha_creacion__date__gte=params["fecha__gte"])
        if params.get("fecha__lte"):
            qs = qs.filter(fecha_creacion__date__lte=params["fecha__lte"])
        if params.get("zona__icontains"):
            # `zona` se construye en el serializer desde el sector, asi que el
            # filtro se empareja en el mismo lado (antes se mandaba y se ignoraba)
            qs = qs.filter(
                sectores__nombre__icontains=params["zona__icontains"]
            ).distinct()
        if str(params.get("solo_nuevas", "")).lower() in ("1", "true", "yes"):
            if ultima:
                qs = qs.filter(captura_nacimiento_id=ultima)
            else:
                qs = qs.none()

        return qs


class AlertaDetailView(APIView):
    """
    PATCH /api/alertas/<id>/        → cambiar estado/notas.
    POST  /api/alertas/<id>/notificar/ → enviar SMS manual a técnicos.
    GET   /api/alertas/<id>/geojson/   → exportar geometría como GeoJSON.
    """
    permission_classes = [IsTecnicoOAdministrador]

    def _get_caso(self, pk):
        try:
            return CasoAuditoria.objects.prefetch_related("sectores").get(pk=pk)
        except CasoAuditoria.DoesNotExist:
            return None

    def patch(self, request, pk):
        caso = self._get_caso(pk)
        if not caso:
            return Response({"detail": "No encontrado."}, status=status.HTTP_404_NOT_FOUND)

        serializer = AlertaPatchSerializer(caso, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        cambios = []
        if "estado" in request.data:
            cambios.append(f"estado → {request.data['estado']}")
        if "notas_tecnico" in request.data:
            cambios.append("notas del técnico")
        detalle = f": {', '.join(cambios)}" if cambios else ""
        registrar_actividad(
            request.user,
            f"Actualizó la alerta ALT-{caso.pk:03d}{detalle}",
            caso,
            CHANGE,
        )

        # Si cambió a MONITOREO_ACTIVO → disparar SMS al técnico para verificar en campo
        if caso.estado_caso == CasoAuditoria.EstadoCaso.MONITOREO_ACTIVO:
            try:
                _enlazar_sectores_y_alertar(caso)
            except Exception as e:
                logger.error(f"[ALERTAS] Error SMS caso {pk}: {e}")

        return Response(AlertaSerializer(caso).data)


class AlertaNotificarView(APIView):
    """POST /api/alertas/<pk>/notificar/ — SMS manual a técnicos seleccionados."""
    permission_classes = [IsAdministrador]

    def post(self, request, pk):
        try:
            caso = CasoAuditoria.objects.prefetch_related("sectores").get(pk=pk)
        except CasoAuditoria.DoesNotExist:
            return Response({"detail": "No encontrado."}, status=status.HTTP_404_NOT_FOUND)

        tecnico_ids = request.data.get("tecnico_ids", [])
        tecnicos = TecnicoCampo.objects.filter(id__in=tecnico_ids, activo=True)

        enviados = 0
        twilio   = None
        try:
            from twilio.rest import Client
            twilio = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        except Exception as e:
            logger.error(f"[NOTIFICAR] Error Twilio init: {e}")
            return Response({"error": "Error al conectar con Twilio."}, status=500)

        sector = caso.sectores.first()
        zona   = sector.nombre if sector else "Desconocida"

        for tecnico in tecnicos:
            if not tecnico.telefono:
                continue
            mensaje = (
                f"🚨 ALERTA DEFORESTACIÓN - ApuGuard\n"
                f"Zona: {zona}\n"
                f"Caso: ALT-{caso.pk:03d}\n"
                f"Score: {caso.score_confianza:.2f}"
            )
            try:
                twilio.messages.create(
                    body=mensaje,
                    from_=settings.TWILIO_PHONE_NUMBER,
                    to=tecnico.telefono,
                )
                enviados += 1
            except Exception as e:
                logger.error(f"[NOTIFICAR] SMS a {tecnico.telefono} falló: {e}")

        registrar_actividad(
            request.user,
            f"Envió SMS a {enviados} técnico(s) por ALT-{caso.pk:03d}",
            caso,
            CHANGE,
        )
        return Response({"enviados": enviados})


class AlertaPdfView(APIView):
    """GET /api/alertas/<pk>/pdf/ — genera PDF de reporte del caso."""
    permission_classes = [IsTecnicoOAdministrador]

    def get(self, request, pk):
        try:
            caso = CasoAuditoria.objects.prefetch_related(
                "sectores", "sms_enviados", "sms_enviados__tecnico"
            ).get(pk=pk)
        except CasoAuditoria.DoesNotExist:
            return Response({"detail": "No encontrado."}, status=404)

        from io import BytesIO
        from django.http import HttpResponse
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
        )
        from reportlab.lib.enums import TA_LEFT, TA_CENTER

        buffer = BytesIO()
        doc    = SimpleDocTemplate(
            buffer, pagesize=A4,
            leftMargin=2*cm, rightMargin=2*cm,
            topMargin=2*cm, bottomMargin=2*cm,
        )

        styles = getSampleStyleSheet()
        verde  = colors.HexColor("#166534")
        gris   = colors.HexColor("#6b7280")
        rojo   = colors.HexColor("#dc2626")

        estilo_titulo = ParagraphStyle(
            "titulo", fontSize=16, textColor=verde,
            spaceAfter=4, fontName="Helvetica-Bold", alignment=TA_LEFT
        )
        estilo_subtitulo = ParagraphStyle(
            "subtitulo", fontSize=10, textColor=gris,
            spaceAfter=12, fontName="Helvetica"
        )
        estilo_seccion = ParagraphStyle(
            "seccion", fontSize=10, textColor=verde,
            spaceBefore=12, spaceAfter=6, fontName="Helvetica-Bold"
        )
        estilo_body = ParagraphStyle(
            "body", fontSize=9, textColor=colors.HexColor("#111827"),
            spaceAfter=4, fontName="Helvetica", leading=14
        )

        # Datos del caso
        codigo     = f"ALT-{caso.pk:03d}"
        sector     = caso.sectores.first()
        zona       = sector.nombre if sector else "Sin sector"
        fecha_str  = caso.fecha_creacion.strftime("%d/%m/%Y %H:%M") if caso.fecha_creacion else "—"

        if caso.geom_afectada:
            centroid = caso.geom_afectada.centroid
            coords   = f"{centroid.y:.4f}, {centroid.x:.4f}"
            try:
                geom_proj = caso.geom_afectada.transform(32719, clone=True)
                area_ha   = round(geom_proj.area / 10_000, 2)
            except Exception:
                area_ha = 0.0
        else:
            coords  = "—"
            area_ha = 0.0

        tipo_label = {"DETECCION": "Detección", "INCERTIDUMBRE": "Incertidumbre"}.get(caso.tipo_caso, caso.tipo_caso)
        eco_label  = {"PERTURBADO": "Perturbado", "RECUPERANDO": "Recuperándose", "RECUPERADO": "Recuperado"}.get(caso.estado_ecologico, caso.estado_ecologico)
        conf_pct   = f"{caso.score_confianza * 100:.1f}%"

        story = []

        # Encabezado
        story.append(Paragraph("APU GUARD — Sistema de Detección de Deforestación", estilo_titulo))
        story.append(Paragraph(f"Reporte de Alerta {codigo} · Reserva Nacional Tambopata", estilo_subtitulo))
        story.append(HRFlowable(width="100%", thickness=1, color=verde, spaceAfter=12))

        # Resumen
        story.append(Paragraph("Identificación del Caso", estilo_seccion))
        resumen_data = [
            ["Código",        codigo,      "Fecha de detección", fecha_str],
            ["Zona / Sector", zona,        "Área afectada",      f"{area_ha} Ha"],
            ["Coordenadas GPS", coords,    "Estado del caso",    caso.get_estado_caso_display()],
        ]
        t_resumen = Table(resumen_data, colWidths=[3.5*cm, 6*cm, 4*cm, 4*cm])
        t_resumen.setStyle(TableStyle([
            ("FONTNAME",    (0, 0), (-1, -1), "Helvetica"),
            ("FONTSIZE",    (0, 0), (-1, -1), 9),
            ("FONTNAME",    (0, 0), (0, -1), "Helvetica-Bold"),
            ("FONTNAME",    (2, 0), (2, -1), "Helvetica-Bold"),
            ("TEXTCOLOR",   (0, 0), (0, -1), gris),
            ("TEXTCOLOR",   (2, 0), (2, -1), gris),
            ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.HexColor("#f9fafb"), colors.white]),
            ("GRID",        (0, 0), (-1, -1), 0.5, colors.HexColor("#e5e7eb")),
            ("PADDING",     (0, 0), (-1, -1), 6),
        ]))
        story.append(t_resumen)

        # Análisis IA
        story.append(Paragraph("Análisis de Detección (IA)", estilo_seccion))
        ia_data = [
            ["Campo", "Valor"],
            ["Tipo de detección",              tipo_label],
            ["Nivel de confianza del modelo",  conf_pct],
            ["Estado ecológico actual",        eco_label],
            ["Ciclos quincenales sin actividad", f"{caso.ciclos_limpios_consecutivos} quincenas"],
        ]
        t_ia = Table(ia_data, colWidths=[9*cm, 8.5*cm])
        t_ia.setStyle(TableStyle([
            ("FONTNAME",    (0, 0), (-1, 0),  "Helvetica-Bold"),
            ("FONTNAME",    (0, 1), (-1, -1), "Helvetica"),
            ("FONTSIZE",    (0, 0), (-1, -1), 9),
            ("TEXTCOLOR",   (0, 0), (-1, 0),  colors.white),
            ("BACKGROUND",  (0, 0), (-1, 0),  verde),
            ("TEXTCOLOR",   (0, 1), (0, -1),  gris),
            ("FONTNAME",    (0, 1), (0, -1),  "Helvetica-Bold"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#f9fafb"), colors.white]),
            ("GRID",        (0, 0), (-1, -1), 0.5, colors.HexColor("#e5e7eb")),
            ("PADDING",     (0, 0), (-1, -1), 6),
        ]))
        story.append(t_ia)

        # Historial SMS
        story.append(Paragraph("Historial de Notificaciones SMS", estilo_seccion))
        sms_qs = caso.sms_enviados.select_related("tecnico").order_by("fecha_envio")
        if sms_qs.exists():
            sms_data = [["Técnico", "Teléfono", "Fecha de envío", "Estado"]]
            for sms in sms_qs:
                nombre   = sms.tecnico.nombre   if sms.tecnico else "—"
                telefono = sms.tecnico.telefono if sms.tecnico else "—"
                fecha_e  = sms.fecha_envio.strftime("%d/%m/%Y %H:%M") if sms.fecha_envio else "—"
                sms_data.append([nombre, telefono, fecha_e, sms.estado])

            t_sms = Table(sms_data, colWidths=[5*cm, 4*cm, 5*cm, 3.5*cm])
            t_sms.setStyle(TableStyle([
                ("FONTNAME",    (0, 0), (-1, 0),  "Helvetica-Bold"),
                ("FONTNAME",    (0, 1), (-1, -1), "Helvetica"),
                ("FONTSIZE",    (0, 0), (-1, -1), 9),
                ("TEXTCOLOR",   (0, 0), (-1, 0),  colors.white),
                ("BACKGROUND",  (0, 0), (-1, 0),  verde),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#f9fafb"), colors.white]),
                ("GRID",        (0, 0), (-1, -1), 0.5, colors.HexColor("#e5e7eb")),
                ("PADDING",     (0, 0), (-1, -1), 6),
            ]))
            story.append(t_sms)
        else:
            story.append(Paragraph("Sin notificaciones SMS registradas para este caso.", estilo_body))

        # Notas técnicas
        if caso.notas_tecnico:
            story.append(Paragraph("Notas / Observaciones Técnicas", estilo_seccion))
            story.append(Paragraph(caso.notas_tecnico.replace("\n", "<br/>"), estilo_body))

        # Pie de página
        story.append(Spacer(1, 1*cm))
        story.append(HRFlowable(width="100%", thickness=0.5, color=gris))
        story.append(Spacer(1, 0.2*cm))
        from django.utils import timezone
        story.append(Paragraph(
            f"Generado el {timezone.now().strftime('%d/%m/%Y %H:%M')} · APU GUARD · Reserva Nacional Tambopata, Madre de Dios, Perú",
            ParagraphStyle("pie", fontSize=7, textColor=gris, alignment=TA_CENTER)
        ))

        doc.build(story)
        buffer.seek(0)

        response = HttpResponse(buffer, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="apuguard_{codigo}.pdf"'
        return response


class AlertaGeoJsonView(APIView):
    """GET /api/alertas/<pk>/geojson/ — exportar geometría."""
    permission_classes = [IsTecnicoOAdministrador]

    def get(self, request, pk):
        try:
            caso = CasoAuditoria.objects.get(pk=pk)
        except CasoAuditoria.DoesNotExist:
            return Response({"detail": "No encontrado."}, status=404)

        if not caso.geom_afectada:
            return Response({"detail": "Sin geometría."}, status=404)

        import json
        geojson = {
            "type": "Feature",
            "properties": {
                "caso_id":   caso.pk,
                "codigo":    f"ALT-{caso.pk:03d}",
                "estado":    caso.estado_caso,
                "score":     caso.score_confianza,
            },
            "geometry": json.loads(caso.geom_afectada.geojson),
        }
        from django.http import JsonResponse
        return JsonResponse(geojson)


class AlertaEvidenciaView(APIView):
    """
    POST /api/alertas/<pk>/evidencia/
    Genera una presigned PUT URL de S3 para subir la foto de evidencia.
    El frontend sube el archivo directamente a S3 con esa URL.
    Una vez confirmado el upload, actualiza evidencia_s3_key en el caso.

    Body:
      { "filename": "foto.jpg", "content_type": "image/jpeg" }
    o
      { "s3_key": "evidencias/caso_5_foto.jpg" }  (para confirmar el upload)
    """
    permission_classes = [IsTecnicoOAdministrador]

    def post(self, request, pk):
        try:
            caso = CasoAuditoria.objects.get(pk=pk)
        except CasoAuditoria.DoesNotExist:
            return Response({"detail": "No encontrado."}, status=status.HTTP_404_NOT_FOUND)

        # Confirmar upload (el frontend llama de nuevo con s3_key tras subir el archivo)
        if "s3_key" in request.data:
            caso.evidencia_s3_key = request.data["s3_key"]
            caso.save(update_fields=["evidencia_s3_key"])
            registrar_actividad(
                request.user,
                f"Registró evidencia en ALT-{caso.pk:03d}",
                caso,
                ADDITION,
            )
            return Response({"status": "guardado", "s3_key": caso.evidencia_s3_key})

        # Generar presigned PUT URL
        filename     = request.data.get("filename", "evidencia.jpg")
        content_type = request.data.get("content_type", "image/jpeg")

        import re
        safe_name = re.sub(r"[^\w.\-]", "_", filename)
        s3_key    = f"evidencias/caso_{pk}_{safe_name}"

        s3         = boto3.client("s3", region_name=settings.AWS_REGION_NAME)
        bucket     = settings.AWS_S3_BUCKET_NAME
        expiracion = getattr(settings, "S3_PRESIGNED_URL_EXPIRATION", 900)

        try:
            upload_url = s3.generate_presigned_url(
                ClientMethod="put_object",
                Params={
                    "Bucket":      bucket,
                    "Key":         s3_key,
                    "ContentType": content_type,
                },
                ExpiresIn=expiracion,
            )
        except Exception as e:
            logger.error(f"[EVIDENCIA] Error generando presigned PUT URL: {e}")
            return Response({"error": "No se pudo generar URL de subida."}, status=500)

        return Response({
            "upload_url": upload_url,
            "s3_key":     s3_key,
            "expires_in": expiracion,
        })


# ---------------------------------------------------------------------------
# GET /api/dashboard/stats/
# ---------------------------------------------------------------------------

class DashboardStatsView(APIView):
    """
    GET /api/dashboard/stats/ → KPIs y metadata dinámicas reales del sistema.
    """
    permission_classes = [IsTecnicoOAdministrador]

    def get(self, request):
        user = request.user
        es_admin = user.is_staff or user.is_superuser
        ids_sectores = _sectores_ids_para_usuario(user)

        qs_base = CasoAuditoria.objects.all()
        if ids_sectores is not None:
            qs_base = qs_base.filter(sectores__id__in=ids_sectores).distinct()

        # Ultima captura procesada: define "la ultima pasada"
        ultima = CapturaSatelital.objects.order_by("-fecha_adquisicion").first()

        abiertos = [
            CasoAuditoria.EstadoCaso.PENDIENTE_REVISION,
            CasoAuditoria.EstadoCaso.MONITOREO_ACTIVO,
        ]
        con_validacion = abiertos + [CasoAuditoria.EstadoCaso.VALIDADO_POSITIVO]

        # 1. Alertas activas reales (casos abiertos) + cuantas nacieron en la
        #    ultima pasada (decision 1: "nueva en esta pasada" = captura_nacimiento)
        alertas_activas = qs_base.filter(estado_caso__in=abiertos).count()
        alertas_nuevas_pasada = (
            qs_base.filter(estado_caso__in=abiertos, captura_nacimiento=ultima).count()
            if ultima else 0
        )

        def _suma_area(qs):
            """Suma de geom_afectada en hectareas (EPSG:4326 -> UTM 19S)."""
            total = 0.0
            for caso in qs.exclude(geom_afectada=None):
                try:
                    total += caso.geom_afectada.transform(32719, clone=True).area / 10_000.0
                except Exception:
                    pass
            return total

        # 2. Area afectada acumulada (Ha). Solo DETECCION: la INCERTIDUMBRE
        #    tiene geometria desde la Fase G2 pero NO es area confirmada.
        area_ha = _suma_area(
            qs_base.filter(tipo_caso=CasoAuditoria.TipoCaso.DETECCION,
                           estado_caso__in=con_validacion)
        )

        # 3. Area NUEVA de la ultima pasada (Ha): casos que nacieron ahi
        area_nueva_ha = (
            _suma_area(qs_base.filter(captura_nacimiento=ultima,
                                      tipo_caso=CasoAuditoria.TipoCaso.DETECCION))
            if ultima else 0.0
        )

        # 4. Pasos del Pipeline basados en el registro real
        pipeline_steps = []
        if ultima:
            pct_limpio = max(0, 100 - int(ultima.cobertura_nubes))
            pipeline_steps = [
                {"nombre": "1. Descarga Sentinel-2", "porcentaje": 100, "estado": "Completado"},
                {"nombre": "2. Filtro de Nubes", "porcentaje": pct_limpio, "estado": f"{ultima.cobertura_nubes:.1f}% Nubes"},
                {"nombre": "3. Segmentación IA", "porcentaje": 100 if ultima.estado_liberacion == "LIBERADO" else 50, "estado": ultima.get_estado_liberacion_display()},
            ]

        # 5. Cálculo REAL de Almacenamiento en disco servidor
        total_b, used_b, _ = shutil.disk_usage("/")
        storage_total_gb = round(total_b / (1024**3), 2)
        storage_usado_gb = round(used_b / (1024**3), 2)

        # 6. Lista REAL de Usuarios para select de auditoría
        usuarios_lista = list(
            User.objects.filter(is_active=True).values("id", "username", "first_name", "last_name")
        )

        data = {
            # KPIs (Fase G6) ---------------------------------------------
            "alertas_activas": alertas_activas,
            "alertas_nuevas_pasada": alertas_nuevas_pasada,
            "alertas_totales": qs_base.count(),
            "area_afectada_ha": round(area_ha, 2),
            "area_nueva_pasada_ha": round(area_nueva_ha, 2),
            "usuarios_activos": len(usuarios_lista),
            "ultima_captura": {
                "id": ultima.pk,
                "fecha": str(ultima.fecha_adquisicion),
                "estado": ultima.get_estado_liberacion_display(),
            } if ultima else None,
            # Alias legacy (el frontend antiguo lo seguia leyendo)
            "nuevas_alertas_hoy": alertas_activas,
            # Metadatos -----------------------------------------------------
            "estado_sistema": "En Proceso" if (ultima and ultima.estado_liberacion == "PROCESANDO") else "Óptimo",
            "es_admin": es_admin,
            "storage_usado_gb": storage_usado_gb,
            "storage_total_gb": storage_total_gb,
            "usuarios": usuarios_lista,
            "ultima_imagen": {
                "nombre": ultima.s3_path_raw.split("/")[-1] if ultima else "—",
                "satelite": "Sentinel-2A",
                "fecha": str(ultima.fecha_adquisicion) if ultima else "—",
                "resultado": ultima.get_estado_liberacion_display() if ultima else "—",
            } if ultima else None,
            "pipeline_steps": pipeline_steps,
        }

        if not es_admin and hasattr(user, "analista_perfil"):
            data["sectores_count"] = user.analista_perfil.sectores.filter(activo=True).count()

        if es_admin:
            data["usuarios_activos"] = User.objects.filter(is_active=True).count()

        return Response(data)


# ---------------------------------------------------------------------------
# POST /api/pipeline/trigger/  (solo Admin)
# ---------------------------------------------------------------------------

class PipelineTriggerView(APIView):
    """
    POST /api/pipeline/trigger/ → dispara manualmente el pipeline quincenal.
    Solo para Administrador. Útil para pruebas y ejecuciones de emergencia.
    """
    permission_classes = [IsAdministrador]

    def post(self, request):
        try:
            from ml_engine.tasks import procesar_quincena_tambopata
            # forzar=True: disparo manual desde el panel (la guarda 1/16 solo
            # protege contra el catch-up de beat, no contra un admin).
            result = procesar_quincena_tambopata.delay(forzar=True)
            registrar_actividad(
                request.user,
                f"Lanzó el pipeline de detección (tarea {result.id})",
                None,
                CHANGE,
            )
            return Response({"task_id": result.id, "estado": "iniciado"})
        except Exception as e:
            logger.error(f"[TRIGGER] Error al lanzar tarea: {e}")
            return Response(
                {"error": f"No se pudo iniciar la tarea: {e}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class ReporteListView(generics.ListAPIView):
    """
    Lista todos los DocumentoReporte disponibles con URL presignada S3.
    Solo accesible para Administradores.
    """
    serializer_class   = DocumentoReporteSerializer
    permission_classes = [IsAdministrador]

    def get_queryset(self):
        return DocumentoReporte.objects.all()

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()

        # Generar URLs presignadas para todos los reportes en un solo paso
        s3         = boto3.client("s3", region_name=settings.AWS_REGION_NAME)
        bucket     = settings.AWS_S3_BUCKET_NAME
        expiracion = getattr(settings, "S3_PRESIGNED_URL_EXPIRATION", 900)

        presigned_urls = {}
        for reporte in queryset:
            try:
                url = s3.generate_presigned_url(
                    ClientMethod="get_object",
                    Params={"Bucket": bucket, "Key": reporte.s3_key},
                    ExpiresIn=expiracion,
                )
                presigned_urls[reporte.pk] = url
            except Exception as e:
                logger.warning(f"[REPORTES] No se pudo generar URL para reporte {reporte.pk}: {e}")
                presigned_urls[reporte.pk] = None

        serializer = self.get_serializer(
            queryset,
            many=True,
            context={"request": request, "presigned_urls": presigned_urls},
        )
        return Response(serializer.data)

# ---------------------------------------------------------------------------
# GET /api/dashboard/audit-logs/  (Administrador y Analista)
# ---------------------------------------------------------------------------

class AuditLogListView(generics.ListAPIView):
    """
    GET /api/dashboard/audit-logs/
    GET /api/dashboard/audit-logs/?usuario_id=3
    """
    permission_classes = [IsTecnicoOAdministrador]
    serializer_class   = AuditLogSerializer

    def get_queryset(self):
        qs = LogEntry.objects.select_related("user").order_by("-action_time")
        usuario_id = self.request.query_params.get("usuario_id")
        if usuario_id:
            qs = qs.filter(user_id=usuario_id)
        return qs[:20]  # Retorna los últimos 20 registros


# ---------------------------------------------------------------------------
# POST /api/auth/logout/   (revoca el refresh token + auditoría)
# ---------------------------------------------------------------------------

class LogoutView(APIView):
    """
    POST /api/auth/logout/
    Body: { "refresh": "<refresh token>" }

    Blanquea el refresh token mediante rest_framework_simplejwt.token_blacklist
    (queda inutilizable para pedir access tokens nuevos) y registra la salida
    en la tabla de auditoría.

    Nota: el access token emitido no se revoca y sigue válido hasta expirar
    (ACCESS_TOKEN_LIFETIME). El blacklist de SimpleJWT cubre el refresh.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        refresh = request.data.get("refresh")
        if not refresh:
            return Response(
                {"detail": "Falta el refresh token."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            from rest_framework_simplejwt.tokens import RefreshToken
            RefreshToken(refresh).blacklist()
        except Exception as e:
            logger.warning(f"[LOGOUT] Refresh token no revocable: {e}")
            return Response(
                {"detail": "Refresh token inválido o ya revocado."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        registrar_actividad(request.user, "Cerró sesión", request.user, DELETION)
        return Response({"detalle": "Sesión cerrada."})