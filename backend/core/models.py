"""
models.py - APU GUARD Core
===========================
Modelos de base de datos con PostGIS (SRID=4326).

Jerarquia principal:
  ConfiguracionGlobal (singleton)
  SectorReserva <--> TecnicoCampo (ManyToMany)
  CapturaSatelital
    └── ParcheProcesamiento (FK)
          └── CasoAuditoria (OneToOne)
                ├── SectorReserva (ManyToMany)
                └── RegistroSMS (FK)
"""

from django.contrib.auth.models import User
from django.contrib.gis.db import models
from django.utils import timezone


# ---------------------------------------------------------------------------
# 1. ConfiguracionGlobal — Singleton
# ---------------------------------------------------------------------------

class ConfiguracionGlobal(models.Model):
    """
    Tabla singleton: solo puede existir un registro (id=1).
    Contiene parametros operacionales del sistema.
    """
    umbral_recuperacion_quincenas = models.IntegerField(
        default=24,
        help_text=(
            "Numero de quincenas consecutivas sin deforestacion "
            "necesarias para declarar un sector como RECUPERADO."
        ),
    )
    umbral_cierre_incertidumbre_quincenas = models.IntegerField(
        default=6,
        help_text=(
            "Pasadas sin volver a detectar un caso INCERTIDUMBRE antes de "
            "cerrarlo automaticamente como DESCARTADO."
        ),
    )

    class Meta:
        verbose_name = "Configuracion Global"
        verbose_name_plural = "Configuracion Global"

    def save(self, *args, **kwargs):
        self.pk = 1   # Fuerza singleton
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        pass   # No se puede eliminar

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return (f"ConfiguracionGlobal (umbral={self.umbral_recuperacion_quincenas}, "
                f"cierre_incertidumbre={self.umbral_cierre_incertidumbre_quincenas})")


# ---------------------------------------------------------------------------
# 2. SectorReserva
# ---------------------------------------------------------------------------

class SectorReserva(models.Model):
    """
    Sector geografico dentro de la Reserva de Tambopata.
    Puede tener multiples tecnicos de campo asignados.
    """
    nombre = models.CharField(max_length=200)
    codigo = models.CharField(max_length=50, unique=True)
    geom   = models.PolygonField(srid=4326)
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Sector de Reserva"
        verbose_name_plural = "Sectores de Reserva"

    def __str__(self):
        return f"{self.codigo} — {self.nombre}"


# ---------------------------------------------------------------------------
# 3. TecnicoCampo
# ---------------------------------------------------------------------------

class TecnicoCampo(models.Model):
    """
    Tecnico responsable de verificar alertas en campo.
    Asignado a uno o mas sectores de la reserva.
    """
    user      = models.OneToOneField(
        User,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="tecnico_perfil",
        help_text="Usuario Django asociado a este tecnico (para autenticacion JWT).",
    )
    nombre    = models.CharField(max_length=200)
    telefono  = models.CharField(max_length=20, help_text="Numero E.164: +51987654321")
    email     = models.EmailField(blank=True)
    sectores  = models.ManyToManyField(
        SectorReserva,
        related_name="tecnicos",
        blank=True,
    )
    activo    = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Tecnico de Campo"
        verbose_name_plural = "Tecnicos de Campo"

    def __str__(self):
        return f"{self.nombre} ({self.telefono})"



# ---------------------------------------------------------------------------
# 3b. PerfilAnalista
# ---------------------------------------------------------------------------

class PerfilAnalista(models.Model):
    """
    Perfil de usuario con rol Analista (is_staff=False, no es TecnicoCampo).
    Permite asignar sectores al analista para filtrar las alertas que ve en la app.
    No recibe SMS — eso es exclusivo de TecnicoCampo.
    """
    user     = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="analista_perfil",
    )
    sectores = models.ManyToManyField(
        SectorReserva,
        related_name="analistas",
        blank=True,
    )

    class Meta:
        verbose_name = "Perfil Analista"
        verbose_name_plural = "Perfiles Analista"

    def __str__(self):
        return f"Analista: {self.user.username}"


# ---------------------------------------------------------------------------
# 4. CapturaSatelital
# ---------------------------------------------------------------------------

class CapturaSatelital(models.Model):
    """
    Composite quincenal de Sentinel-2 descargado desde la fuente configurada
    (STAC/AWS por defecto, GEE opcional).
    Un registro por quincena procesada.
    """

    class EstadoLiberacion(models.TextChoices):
        PROCESANDO = "PROCESANDO", "Procesando"
        AUDITORIA  = "AUDITORIA",  "En Auditoria"
        LIBERADO   = "LIBERADO",   "Liberado"

    fecha_adquisicion  = models.DateField(
        unique=True,
        help_text="Fecha de inicio de la ventana quincenal. Un registro por pasada.",
    )
    s3_path_raw        = models.CharField(
        max_length=500,
        help_text="Ruta S3 del raster GeoTIFF crudo descargado (Sentinel-2)."
    )
    cobertura_nubes    = models.FloatField(
        default=0.0,
        help_text="Porcentaje de cobertura de nubes en el composite [0-100]."
    )
    estado_liberacion  = models.CharField(
        max_length=20,
        choices=EstadoLiberacion.choices,
        default=EstadoLiberacion.PROCESANDO,
    )
    fecha_creacion     = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Captura Satelital"
        verbose_name_plural = "Capturas Satelitales"
        ordering = ["-fecha_adquisicion"]

    def __str__(self):
        return f"Captura {self.fecha_adquisicion} [{self.estado_liberacion}]"


# ---------------------------------------------------------------------------
# 5. ParcheProcesamiento
# ---------------------------------------------------------------------------

class ParcheProcesamiento(models.Model):
    """
    Parche de 128x128 pixeles extraido de una CapturaSatelital.
    Cada parche se envia individualmente a SageMaker para inferencia.
    """

    class EstadoSageMaker(models.TextChoices):
        PENDIENTE  = "PENDIENTE",  "Pendiente"
        PROCESADO  = "PROCESADO",  "Procesado"
        ERROR      = "ERROR",      "Error"

    captura         = models.ForeignKey(
        CapturaSatelital,
        on_delete=models.CASCADE,
        related_name="parches",
    )
    fila_idx        = models.IntegerField(
        help_text="Indice de fila en la grilla de tiling (stride=64)."
    )
    col_idx         = models.IntegerField(
        help_text="Indice de columna en la grilla de tiling (stride=64)."
    )
    s3_path_tensor  = models.CharField(
        max_length=500,
        help_text="Ruta S3 del archivo .npy del parche enviado a SageMaker."
    )
    s3_path_resultado = models.CharField(
        max_length=500,
        blank=True,
        help_text="Ruta S3 del archivo .npz de resultado de SageMaker."
    )
    estado_sagemaker = models.CharField(
        max_length=20,
        choices=EstadoSageMaker.choices,
        default=EstadoSageMaker.PENDIENTE,
    )
    geom            = models.PolygonField(
        srid=4326,
        help_text="Footprint geografico del parche en coordenadas WGS84."
    )
    sagemaker_request_id = models.CharField(
        max_length=200,
        blank=True,
        help_text="ID de la invocacion asincrona de SageMaker."
    )
    fecha_envio     = models.DateTimeField(null=True, blank=True)
    fecha_respuesta = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Parche de Procesamiento"
        verbose_name_plural = "Parches de Procesamiento"
        unique_together = [("captura", "fila_idx", "col_idx")]

    def __str__(self):
        return (f"Parche [{self.fila_idx},{self.col_idx}] "
                f"— Captura {self.captura.fecha_adquisicion} "
                f"[{self.estado_sagemaker}]")


# ---------------------------------------------------------------------------
# 6. CasoAuditoria
# ---------------------------------------------------------------------------

class CasoAuditoria(models.Model):
    """
    Caso de alerta o incertidumbre generado por el modelo de IA.

    tipo_caso:
      DETECCION    : el modelo detecta deforestacion nueva con alta confianza
      INCERTIDUMBRE: entropy_media > 0.5*ln(2), requiere validacion visual

    estado_ecologico (time-series):
      PERTURBADO   : deforestacion detectada activa
      RECUPERANDO  : sin deforestacion por N quincenas pero aun no llega al umbral
      RECUPERADO   : ciclos_limpios_consecutivos >= umbral_recuperacion_quincenas

    score_confianza = 1 - (mean(entropy) / ln(2))  in [0, 1]
    """

    class TipoCaso(models.TextChoices):
        DETECCION     = "DETECCION",     "Deteccion"
        INCERTIDUMBRE = "INCERTIDUMBRE", "Incertidumbre"

    class EstadoCaso(models.TextChoices):
        PENDIENTE_REVISION = "PENDIENTE_REVISION", "Pendiente de Revision"
        MONITOREO_ACTIVO   = "MONITOREO_ACTIVO",   "Monitoreo Activo"
        VALIDADO_POSITIVO  = "VALIDADO_POSITIVO",  "Validado Positivo"
        DESCARTADO         = "DESCARTADO",         "Descartado"
        RECUPERADO         = "RECUPERADO",         "Recuperado"

    class EstadoEcologico(models.TextChoices):
        PERTURBADO  = "PERTURBADO",  "Perturbado"
        RECUPERANDO = "RECUPERANDO", "Recuperando"
        RECUPERADO  = "RECUPERADO",  "Recuperado"

    # -- Relaciones --
    parche   = models.OneToOneField(
        ParcheProcesamiento,
        on_delete=models.CASCADE,
        related_name="caso_auditoria",
        null=True, blank=True,
    )
    sectores = models.ManyToManyField(
        SectorReserva,
        related_name="casos",
        blank=True,
        help_text="Sectores que intersectan geometricamente con la zona afectada.",
    )

    # -- Campos de IA --
    tipo_caso        = models.CharField(
        max_length=20, choices=TipoCaso.choices
    )
    estado_caso      = models.CharField(
        max_length=20,
        choices=EstadoCaso.choices,
        default=EstadoCaso.PENDIENTE_REVISION,
        help_text=(
            "PENDIENTE_REVISION: IA detecto INCERTIDUMBRE, requiere validacion. "
            "MONITOREO_ACTIVO: Admin confirma sospecha — dispara SMS al tecnico para verificar en campo. "
            "VALIDADO_POSITIVO: Admin valida el reporte del tecnico — registro oficial. "
            "DESCARTADO: Admin descarto como falso positivo. "
            "RECUPERADO: Sistema asigna al alcanzar ciclos limpios."
        ),
    )
    score_confianza  = models.FloatField(
        help_text="1 - (mean_entropy / ln2). Rango [0, 1]. 1 = maxima confianza."
    )
    geom_afectada    = models.MultiPolygonField(
        srid=4326,
        null=True, blank=True,
        help_text="Geometria de la zona de deforestacion nueva detectada.",
    )

    # -- Campos de recuperacion ecologica (time-series) --
    estado_ecologico           = models.CharField(
        max_length=20,
        choices=EstadoEcologico.choices,
        default=EstadoEcologico.PERTURBADO,
    )
    ciclos_limpios_consecutivos = models.IntegerField(
        default=0,
        help_text=(
            "Quincenas consecutivas sin deforestacion detectada. "
            "Se reinicia a 0 si la IA detecta deforestacion nueva."
        ),
    )
    fecha_recuperacion = models.DateField(
        null=True, blank=True,
        help_text="Fecha en que el sector alcanzo estado RECUPERADO.",
    )

    # -- Historial entre pasadas (dedup y semantica "alarma nueva") --
    captura_nacimiento = models.ForeignKey(
        CapturaSatelital,
        on_delete=models.PROTECT,
        related_name="casos_nacidos",
        null=True, blank=True,
        help_text=(
            "Captura en que se creo este caso por primera vez. "
            "Es la base de 'alarma nueva en esta pasada'."
        ),
    )
    captura_ultima_deteccion = models.ForeignKey(
        CapturaSatelital,
        on_delete=models.PROTECT,
        related_name="casos_detectados",
        null=True, blank=True,
        help_text="Captura mas reciente en que se volvio a detectar este caso.",
    )
    captura_ultimo_ciclo = models.ForeignKey(
        CapturaSatelital,
        on_delete=models.PROTECT,
        related_name="casos_ciclo",
        null=True, blank=True,
        help_text=(
            "Captura en que se aplico por ultima vez la logica ecologica. "
            "Garantiza a lo sumo UNA transicion de ciclo por pasada aunque "
            "varios parches adyacentes toquen el mismo caso."
        ),
    )
    veces_detectado = models.PositiveIntegerField(
        default=1,
        help_text="Numero de pasadas en que se ha detectado este caso.",
    )

    # -- Evidencia de campo --
    evidencia_s3_key = models.CharField(
        max_length=500,
        blank=True,
        help_text="Ruta S3 de la foto de evidencia subida por el tecnico (jpg/png).",
    )

    # -- Auditoria --
    fecha_creacion      = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)
    notas_tecnico       = models.TextField(blank=True)

    class Meta:
        verbose_name = "Caso de Auditoria"
        verbose_name_plural = "Casos de Auditoria"
        ordering = ["-fecha_creacion"]
        indexes = [
            models.Index(
                fields=["captura_nacimiento", "estado_caso"],
                name="caso_nac_estado_idx",
            ),
            models.Index(
                fields=["tipo_caso", "estado_caso"],
                name="caso_tipo_estado_idx",
            ),
        ]

    def __str__(self):
        return (f"Caso {self.pk} [{self.tipo_caso}] "
                f"score={self.score_confianza:.3f} "
                f"[{self.estado_caso}]")

    def incrementar_ciclo_limpio(self):
        """
        Suma +1 al contador de quincenas limpias.
        Si llega al umbral, marca como RECUPERADO.
        """
        self.ciclos_limpios_consecutivos += 1
        umbral = ConfiguracionGlobal.get().umbral_recuperacion_quincenas

        if (self.ciclos_limpios_consecutivos >= umbral
                and self.estado_ecologico != self.EstadoEcologico.RECUPERADO):
            self.estado_ecologico  = self.EstadoEcologico.RECUPERADO
            self.fecha_recuperacion = timezone.now().date()
            self.estado_caso        = self.EstadoCaso.RECUPERADO

        elif self.estado_ecologico == self.EstadoEcologico.PERTURBADO:
            self.estado_ecologico = self.EstadoEcologico.RECUPERANDO

        self.save(update_fields=[
            "ciclos_limpios_consecutivos",
            "estado_ecologico",
            "fecha_recuperacion",
            "estado_caso",
        ])

    def reiniciar_ciclo(self):
        """
        La IA detecto deforestacion nueva: reinicia el contador.
        """
        self.ciclos_limpios_consecutivos = 0
        self.estado_ecologico            = self.EstadoEcologico.PERTURBADO
        self.fecha_recuperacion          = None
        self.save(update_fields=[
            "ciclos_limpios_consecutivos",
            "estado_ecologico",
            "fecha_recuperacion",
        ])


# ---------------------------------------------------------------------------
# 7. DocumentoReporte
# ---------------------------------------------------------------------------

class DocumentoReporte(models.Model):
    """
    Registro de reporte mensual generado por Celery Beat.
    El archivo CSV fisico vive en S3; este modelo guarda la referencia.
    """
    anio          = models.IntegerField(help_text="Anio del periodo reportado.")
    mes           = models.IntegerField(help_text="Mes del periodo reportado (1-12).")
    s3_key        = models.CharField(
        max_length=500,
        help_text="Ruta S3 del CSV: apuguard-reports/YYYY/MM/reporte_mensual.csv"
    )
    casos_validados      = models.IntegerField(default=0)
    casos_recuperados    = models.IntegerField(default=0)
    total_sms_enviados   = models.IntegerField(default=0)
    fecha_emision        = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Documento de Reporte"
        verbose_name_plural = "Documentos de Reporte"
        ordering = ["-anio", "-mes"]
        unique_together = [("anio", "mes")]

    def __str__(self):
        return f"Reporte {self.anio}/{self.mes:02d}"


# ---------------------------------------------------------------------------
# 8. RegistroSMS
# ---------------------------------------------------------------------------

class RegistroSMS(models.Model):
    """
    Registro de cada SMS enviado via AWS SNS a un tecnico de campo.
    """

    class EstadoSMS(models.TextChoices):
        ENVIADO  = "ENVIADO",  "Enviado"
        FALLIDO  = "FALLIDO",  "Fallido"
        PENDIENTE = "PENDIENTE", "Pendiente"

    caso      = models.ForeignKey(
        CasoAuditoria,
        on_delete=models.CASCADE,
        related_name="sms_enviados",
    )
    tecnico   = models.ForeignKey(
        TecnicoCampo,
        on_delete=models.SET_NULL,
        null=True,
        related_name="sms_recibidos",
    )
    mensaje   = models.TextField()
    estado    = models.CharField(
        max_length=20,
        choices=EstadoSMS.choices,
        default=EstadoSMS.PENDIENTE,
    )
    sns_message_id = models.CharField(max_length=200, blank=True)
    fecha_envio    = models.DateTimeField(auto_now_add=True)
    error_detalle  = models.TextField(blank=True)

    class Meta:
        verbose_name = "Registro SMS"
        verbose_name_plural = "Registros SMS"
        ordering = ["-fecha_envio"]

    def __str__(self):
        return (f"SMS a {self.tecnico} "
                f"[Caso {self.caso_id}] [{self.estado}]")
