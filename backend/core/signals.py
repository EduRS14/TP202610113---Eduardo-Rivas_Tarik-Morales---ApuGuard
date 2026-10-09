"""
signals.py — APU GUARD Core
Dispara SMS cuando un CasoAuditoria cambia a MONITOREO_ACTIVO.
Funciona desde el admin Django, la API REST, o cualquier otra vía.
"""
import logging

from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver

logger = logging.getLogger(__name__)


@receiver(pre_save, sender="core.CasoAuditoria")
def marcar_cambio_monitoreo_activo(sender, instance, **kwargs):
    """
    Antes de guardar: detectar si el estado CAMBIA a MONITOREO_ACTIVO
    y marcarlo en el instance para que post_save lo procese.
    Para casos nuevos (pk=None) con MONITOREO_ACTIVO, también marcar.
    """
    from core.models import CasoAuditoria

    instance._disparar_sms = False

    if instance.pk is None:
        # Caso nuevo directo a MONITOREO_ACTIVO
        if instance.estado_caso == CasoAuditoria.EstadoCaso.MONITOREO_ACTIVO:
            instance._disparar_sms = True
        return

    # Caso existente: verificar cambio de estado
    try:
        anterior = CasoAuditoria.objects.get(pk=instance.pk)
    except CasoAuditoria.DoesNotExist:
        return

    if (anterior.estado_caso != CasoAuditoria.EstadoCaso.MONITOREO_ACTIVO
            and instance.estado_caso == CasoAuditoria.EstadoCaso.MONITOREO_ACTIVO):
        instance._disparar_sms = True


@receiver(post_save, sender="core.CasoAuditoria")
def disparar_sms_monitoreo_activo(sender, instance, created, **kwargs):
    """
    Después de guardar: si pre_save marcó _disparar_sms, enviar SMS.
    En post_save el objeto ya tiene pk, por lo que M2M funciona correctamente.
    Solo actúa si no viene del pipeline ML (que ya envía SMS propio).
    """
    if getattr(instance, "_disparar_sms", False) and not getattr(instance, "_desde_pipeline", False):
        _enviar_sms(instance)


def _enviar_sms(caso):
    """Envía SMS Twilio a todos los técnicos de los sectores del caso."""
    from django.conf import settings
    from core.models import RegistroSMS

    try:
        from twilio.rest import Client
        twilio = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
    except Exception as e:
        logger.error(f"[SMS] Error inicializando Twilio: {e}")
        return

    sectores = caso.sectores.prefetch_related("tecnicos").all()
    tecnicos_notificados = set()

    for sector in sectores:
        for tecnico in sector.tecnicos.filter(activo=True):
            if tecnico.id in tecnicos_notificados:
                continue
            tecnicos_notificados.add(tecnico.id)

            if not tecnico.telefono:
                logger.warning(f"[SMS] Técnico {tecnico} sin teléfono, omitiendo.")
                continue

            coords = ""
            if caso.geom_afectada:
                try:
                    centroide = caso.geom_afectada.centroid
                    coords = f"\nCoordenadas: {centroide.y:.5f}, {centroide.x:.5f}"
                except Exception:
                    pass

            mensaje = (
                f"[APU GUARD] Deforestacion en {sector.codigo} - {sector.nombre}."
                f"{coords}. Verificar en campo y reportar."
            )

            estado_sms = RegistroSMS.EstadoSMS.PENDIENTE
            try:
                msg = twilio.messages.create(
                    body=mensaje,
                    from_=settings.TWILIO_PHONE_NUMBER,
                    to=tecnico.telefono,
                )
                estado_sms = RegistroSMS.EstadoSMS.ENVIADO
                logger.info(f"[SMS] Enviado a {tecnico.telefono}: {msg.sid}")
            except Exception as e:
                estado_sms = RegistroSMS.EstadoSMS.FALLIDO
                logger.error(f"[SMS] Error enviando a {tecnico.telefono}: {e}")

            if caso.pk:
                RegistroSMS.objects.create(
                    caso=caso,
                    tecnico=tecnico,
                    mensaje=mensaje,
                    estado=estado_sms,
                )
