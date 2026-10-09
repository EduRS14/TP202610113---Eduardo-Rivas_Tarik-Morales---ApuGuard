"""
serializers.py - APU GUARD Core
=================================
Serializadores GeoJSON usando rest_framework_gis.

Salida compatible con GeoJSON Feature/FeatureCollection
para consumo directo por el frontend (Mapbox, Leaflet, etc.).
"""

from django.contrib.auth.models import User
from django.contrib.admin.models import LogEntry
from rest_framework import serializers
from rest_framework_gis.serializers import GeoFeatureModelSerializer

from core.models import CasoAuditoria, DocumentoReporte, PerfilAnalista, RegistroSMS, SectorReserva, TecnicoCampo


class SectorReservaSerializer(GeoFeatureModelSerializer):
    """
    GeoJSON Feature de un SectorReserva.
    Geometry: geom (Polygon, SRID=4326)
    """
    tecnicos_count = serializers.SerializerMethodField()

    class Meta:
        model  = SectorReserva
        geo_field = "geom"
        fields = [
            "id", "nombre", "codigo", "activo", "tecnicos_count",
        ]

    def get_tecnicos_count(self, obj):
        return obj.tecnicos.filter(activo=True).count()


class CasoAuditoriaSerializer(GeoFeatureModelSerializer):
    """
    GeoJSON Feature de un CasoAuditoria.
    Geometry: geom_afectada (MultiPolygon, SRID=4326)

    Incluye campos de IA, estado ecologico y referencias al parche.
    """
    captura_fecha  = serializers.DateField(
        source="parche.captura.fecha_adquisicion", read_only=True
    )
    parche_id      = serializers.IntegerField(source="parche.id", read_only=True)
    sectores_ids   = serializers.PrimaryKeyRelatedField(
        source="sectores", many=True, read_only=True
    )

    class Meta:
        model     = CasoAuditoria
        geo_field = "geom_afectada"
        fields = [
            "id",
            "parche_id",
            "captura_fecha",
            "tipo_caso",
            "estado_caso",
            "score_confianza",
            "estado_ecologico",
            "ciclos_limpios_consecutivos",
            "fecha_recuperacion",
            "fecha_creacion",
            "fecha_actualizacion",
            "notas_tecnico",
            "sectores_ids",
        ]
        read_only_fields = [
            "id", "parche_id", "captura_fecha", "tipo_caso",
            "score_confianza", "estado_ecologico",
            "ciclos_limpios_consecutivos", "fecha_recuperacion",
            "fecha_creacion", "fecha_actualizacion", "sectores_ids",
        ]


class CasoAuditoriaDetalleSerializer(CasoAuditoriaSerializer):
    """
    Extiende CasoAuditoriaSerializer con URLs presignadas S3
    para el endpoint de auditoria GET /api/auditoria/<id>/.

    Las URLs se generan dinamicamente en la vista (no en el serializador)
    y se inyectan como contexto.
    """
    url_imagen_satelital = serializers.SerializerMethodField()
    url_capa_ia          = serializers.SerializerMethodField()

    class Meta(CasoAuditoriaSerializer.Meta):
        fields = CasoAuditoriaSerializer.Meta.fields + [
            "url_imagen_satelital",
            "url_capa_ia",
        ]

    def get_url_imagen_satelital(self, obj):
        return self.context.get("url_imagen_satelital", None)

    def get_url_capa_ia(self, obj):
        return self.context.get("url_capa_ia", None)


class DocumentoReporteSerializer(serializers.ModelSerializer):
    """
    Serializador para GET /api/reportes/.
    Incluye URL presignada S3 generada dinamicamente en la vista.
    """
    s3_presigned_url = serializers.SerializerMethodField()

    class Meta:
        model  = DocumentoReporte
        fields = [
            "id",
            "anio",
            "mes",
            "casos_validados",
            "casos_recuperados",
            "total_sms_enviados",
            "fecha_emision",
            "s3_presigned_url",
        ]
        read_only_fields = fields

    def get_s3_presigned_url(self, obj):
        return self.context.get("presigned_urls", {}).get(obj.pk)


# ---------------------------------------------------------------------------
# Usuario
# ---------------------------------------------------------------------------

class UsuarioSerializer(serializers.ModelSerializer):
    """
    Serializer para listar y crear usuarios del sistema.
    'rol' se deriva de is_staff: Administrador | Analista.
    Los Analistas tienen 'sectores_ids' con los IDs de sus sectores asignados.
    """
    rol                 = serializers.SerializerMethodField()
    estado              = serializers.SerializerMethodField()
    nombre_completo     = serializers.SerializerMethodField()
    sectores_ids        = serializers.SerializerMethodField()
    fecha_ultimo_acceso = serializers.DateTimeField(source="last_login", read_only=True, allow_null=True)

    class Meta:
        model  = User
        fields = [
            "id", "username", "email", "first_name", "last_name",
            "nombre_completo", "rol", "estado", "sectores_ids",
            "fecha_ultimo_acceso", "last_login", "date_joined",
        ]
        read_only_fields = [
            "id", "rol", "estado", "nombre_completo",
            "sectores_ids", "fecha_ultimo_acceso", "last_login", "date_joined",
        ]

    def get_rol(self, obj):
        return "Administrador" if obj.is_staff else "Analista"

    def get_estado(self, obj):
        return "Activo" if obj.is_active else "Inactivo"

    def get_nombre_completo(self, obj):
        return f"{obj.first_name} {obj.last_name}".strip() or obj.username

    def get_sectores_ids(self, obj):
        if hasattr(obj, "analista_perfil"):
            return list(obj.analista_perfil.sectores.values_list("id", flat=True))
        return []


class UsuarioCreateSerializer(serializers.ModelSerializer):
    """Solo para POST /api/usuarios/ (admin crea usuario)."""
    password = serializers.CharField(write_only=True, min_length=8)
    rol      = serializers.ChoiceField(
        choices=["Administrador", "Analista"], write_only=True, default="Analista"
    )
    estado   = serializers.ChoiceField(
        choices=["Activo", "Inactivo"], write_only=True, default="Activo"
    )

    class Meta:
        model  = User
        fields = ["username", "email", "first_name", "last_name", "password", "rol", "estado"]

    sectores_ids = serializers.ListField(
        child=serializers.IntegerField(), write_only=True, required=False, default=list
    )

    def create(self, validated_data):
        rol          = validated_data.pop("rol", "Analista")
        estado       = validated_data.pop("estado", "Activo")
        sectores_ids = validated_data.pop("sectores_ids", [])
        password     = validated_data.pop("password")
        user = User(**validated_data)
        user.set_password(password)
        user.is_staff  = (rol == "Administrador")
        user.is_active = (estado == "Activo")
        user.save()
        # Crear PerfilAnalista solo para Analistas
        if not user.is_staff:
            perfil = PerfilAnalista.objects.create(user=user)
            if sectores_ids:
                perfil.sectores.set(sectores_ids)
        return user


class UsuarioPatchSerializer(serializers.ModelSerializer):
    """Para PATCH /api/usuarios/<id>/ y /api/usuarios/me/"""
    rol          = serializers.ChoiceField(choices=["Administrador", "Analista"], required=False)
    estado       = serializers.ChoiceField(choices=["Activo", "Inactivo"],        required=False)
    sectores_ids = serializers.ListField(
        child=serializers.IntegerField(), write_only=True, required=False
    )

    class Meta:
        model  = User
        fields = ["first_name", "last_name", "email", "rol", "estado", "sectores_ids"]

    def update(self, instance, validated_data):
        rol          = validated_data.pop("rol",          None)
        estado       = validated_data.pop("estado",       None)
        sectores_ids = validated_data.pop("sectores_ids", None)

        if rol    is not None: instance.is_staff  = (rol    == "Administrador")
        if estado is not None: instance.is_active = (estado == "Activo")

        instance = super().update(instance, validated_data)

        # Actualizar sectores del PerfilAnalista si se enviaron
        if sectores_ids is not None and not instance.is_staff:
            perfil, _ = PerfilAnalista.objects.get_or_create(user=instance)
            perfil.sectores.set(sectores_ids)

        return instance


# ---------------------------------------------------------------------------
# TecnicoCampo
# ---------------------------------------------------------------------------

class SectorSimpleSerializer(serializers.ModelSerializer):
    class Meta:
        model  = SectorReserva
        fields = ["id", "nombre", "codigo"]


class TecnicoCampoSerializer(serializers.ModelSerializer):
    sectores   = SectorSimpleSerializer(many=True, read_only=True)
    # Campo singular para compatibilidad con frontend (primer sector asignado)
    sector     = serializers.SerializerMethodField()
    sector_id  = serializers.PrimaryKeyRelatedField(
        source="sectores", many=False, queryset=SectorReserva.objects.all(),
        write_only=True, required=False
    )

    class Meta:
        model  = TecnicoCampo
        fields = [
            "id", "nombre", "telefono", "email",
            "sector", "sector_id", "sectores", "activo",
        ]

    def get_sector(self, obj):
        primer = obj.sectores.first()
        return SectorSimpleSerializer(primer).data if primer else None

    def create(self, validated_data):
        sector = validated_data.pop("sectores", None)   # viene como objeto por PrimaryKeyRelatedField
        tecnico = TecnicoCampo.objects.create(**validated_data)
        if sector:
            tecnico.sectores.set([sector])
        return tecnico

    def update(self, instance, validated_data):
        sector = validated_data.pop("sectores", None)
        instance = super().update(instance, validated_data)
        if sector is not None:
            instance.sectores.set([sector])
        return instance


# ---------------------------------------------------------------------------
# Alertas (alias frontend de CasoAuditoria)
# ---------------------------------------------------------------------------

class RegistroSMSSimpleSerializer(serializers.ModelSerializer):
    """Historial SMS embebido en el detalle de alerta."""
    tecnico_nombre   = serializers.SerializerMethodField()
    tecnico_telefono = serializers.SerializerMethodField()

    class Meta:
        model  = RegistroSMS
        fields = ["id", "tecnico_nombre", "tecnico_telefono", "fecha_envio", "estado", "error_detalle"]

    def get_tecnico_nombre(self, obj):
        return obj.tecnico.nombre if obj.tecnico else "—"

    def get_tecnico_telefono(self, obj):
        return obj.tecnico.telefono if obj.tecnico else "—"


class AlertaSerializer(serializers.ModelSerializer):
    """
    Vista simplificada de CasoAuditoria para el frontend (tabla de alertas).
    Mapea los campos internos a la nomenclatura del mockup.
    """
    codigo       = serializers.SerializerMethodField()
    zona         = serializers.SerializerMethodField()
    coordenadas  = serializers.SerializerMethodField()
    area_ha      = serializers.SerializerMethodField()
    severidad    = serializers.SerializerMethodField()
    estado       = serializers.SerializerMethodField()
    fecha        = serializers.DateTimeField(source="fecha_creacion", format="%Y-%m-%d")
    es_nueva     = serializers.SerializerMethodField()
    fecha_nacimiento         = serializers.SerializerMethodField()
    fecha_ultima_deteccion   = serializers.SerializerMethodField()
    sms_historial = RegistroSMSSimpleSerializer(source="sms_enviados", many=True, read_only=True)

    class Meta:
        model  = CasoAuditoria
        fields = [
            "id", "codigo", "fecha", "zona", "coordenadas",
            "area_ha", "severidad", "estado", "notas_tecnico",
            "tipo_caso", "score_confianza", "estado_ecologico",
            "ciclos_limpios_consecutivos", "sms_historial",
            # Fase G6: deduplicacion / "nueva en esta pasada"
            "es_nueva", "fecha_nacimiento", "fecha_ultima_deteccion",
            "veces_detectado",
        ]

    def get_codigo(self, obj):
        return f"ALT-{obj.pk:03d}"

    def get_es_nueva(self, obj):
        """
        True si el caso nacio en la ultima pasada procesada.

        Anotado por AlertaListView como `ultima_captura_id` para evitar una
        consulta por fila. `?solo_nuevas=true` filtra en SQL con el mismo
        criterio, de modo que tabla y KPIs no pueden divergir.
        """
        ultima = getattr(obj, "ultima_captura_id", None)
        if ultima is None:
            ultima = self.context.get("ultima_captura_id")
        return bool(ultima) and obj.captura_nacimiento_id == ultima

    def get_fecha_nacimiento(self, obj):
        if obj.captura_nacimiento_id:
            return str(obj.captura_nacimiento.fecha_adquisicion)
        return None

    def get_fecha_ultima_deteccion(self, obj):
        if obj.captura_ultima_deteccion_id:
            return str(obj.captura_ultima_deteccion.fecha_adquisicion)
        return None

    def get_zona(self, obj):
        sector = obj.sectores.first()
        return sector.nombre if sector else "Sin sector"

    def get_coordenadas(self, obj):
        if obj.geom_afectada:
            centroid = obj.geom_afectada.centroid
            return f"{centroid.y:.4f}, {centroid.x:.4f}"
        return "—"

    def get_area_ha(self, obj):
        if obj.geom_afectada:
            # Área aproximada en ha (geom en EPSG:4326 → convertir a m²)
            try:
                from django.contrib.gis.db.models.functions import Area, Transform
                geom_proj = obj.geom_afectada.transform(32719, clone=True)
                return round(geom_proj.area / 10_000, 2)
            except Exception:
                pass
        return 0.0

    def get_severidad(self, obj):
        if obj.score_confianza >= 0.8:
            return "Alta"
        elif obj.score_confianza >= 0.5:
            return "Media"
        return "Baja"

    def get_estado(self, obj):
        mapa = {
            "PENDIENTE_REVISION": "Pendiente",
            "MONITOREO_ACTIVO":   "Pendiente",
            "VALIDADO_POSITIVO":  "Validada en campo",
            "DESCARTADO":         "Descartada",
            "RECUPERADO":         "Descartada",
        }
        return mapa.get(obj.estado_caso, "Pendiente")


class AlertaPatchSerializer(serializers.ModelSerializer):
    """PATCH /api/alertas/<id>/ — cambiar estado y notas."""
    estado = serializers.ChoiceField(
        choices=["Pendiente", "Validada en campo", "Descartada"],
        required=False
    )

    class Meta:
        model  = CasoAuditoria
        fields = ["estado", "notas_tecnico"]

    def update(self, instance, validated_data):
        estado_front = validated_data.pop("estado", None)
        if estado_front is not None:
            mapa = {
                "Pendiente":        CasoAuditoria.EstadoCaso.PENDIENTE_REVISION,
                "Validada en campo":CasoAuditoria.EstadoCaso.VALIDADO_POSITIVO,
                "Descartada":       CasoAuditoria.EstadoCaso.DESCARTADO,
            }
            instance.estado_caso = mapa[estado_front]
        return super().update(instance, validated_data)


class CasoAuditoriaVeredictoSerializer(serializers.ModelSerializer):
    """
    Serializador para el PATCH de veredicto humano.
    Solo permite cambiar estado_caso y notas_tecnico.
    """
    class Meta:
        model  = CasoAuditoria
        fields = ["estado_caso", "notas_tecnico"]

    def validate_estado_caso(self, value):
        estados_permitidos = [
            CasoAuditoria.EstadoCaso.VALIDADO_POSITIVO,
            CasoAuditoria.EstadoCaso.DESCARTADO,
            CasoAuditoria.EstadoCaso.MONITOREO_ACTIVO,
        ]
        if value not in estados_permitidos:
            raise serializers.ValidationError(
                f"Estado no permitido via PATCH. Valores validos: "
                f"{[e.value for e in estados_permitidos]}"
            )
        return value

# ---------------------------------------------------------------------------
# Auditoria / Registro de Actividad
# ---------------------------------------------------------------------------

class AuditLogSerializer(serializers.ModelSerializer):
    """
    Serializador para transformar las entradas de django.contrib.admin.models.LogEntry
    al formato esperado por la tabla de auditoría del frontend Angular.
    """
    usuario   = serializers.SerializerMethodField()
    accion    = serializers.CharField(source="change_message")
    fechaHora = serializers.DateTimeField(source="action_time", format="%Y-%m-%d %H:%M")
    estado    = serializers.SerializerMethodField()

    class Meta:
        model  = LogEntry
        fields = ["id", "usuario", "accion", "fechaHora", "estado"]

    def get_usuario(self, obj):
        if not obj.user:
            return "Sistema"
        nombre_completo = obj.user.get_full_name()
        return nombre_completo if nombre_completo.strip() else obj.user.username

    def get_estado(self, obj):
        return "Completado"