"""
audit.py - APU GUARD
====================
Registro de actividad de usuarios en la tabla `django_admin_log`
(django.contrib.admin.models.LogEntry), que es la que alimenta:

  * GET /api/dashboard/audit-logs/   (core/views.py AuditLogListView)
  * AuditLogSerializer               (core/serializers.py)
  * la tabla "Registro de Actividad" y el exportarCSV del dashboard

Se reutiliza LogEntry en vez de crear un modelo nuevo para no necesitar
migracion: la tabla ya existe porque `django.contrib.admin` esta en
INSTALLED_APPS.

Convenciones:
  * Solo se registran acciones de escritura (nunca GET/HEAD/OPTIONS).
  * Solo si la operacion termino bien (status < 400).
  * Un fallo de auditoria NUNCA debe romper la peticion: todo va
    envuelto en try/except.
"""

import logging

from django.contrib.admin.models import ADDITION, CHANGE, DELETION, LogEntry
from django.contrib.contenttypes.models import ContentType

# Reexportados para que views.py pueda hacer `from core.audit import ...`
__all__ = ["registrar_actividad", "ADDITION", "CHANGE", "DELETION"]

logger = logging.getLogger(__name__)

MAX_REPR = 200


def registrar_actividad(user, accion, obj=None, flag=CHANGE):
    """
    Crea una fila de auditoria.

    Args:
        user:   usuario autenticado (request.user). Si no esta autenticado
                se registra como `user=None` (aparece como "Sistema").
        accion: texto libre que se muestra en la columna ACCION REALIZADA.
        obj:    instancia opcional asociada (usuario, tecnico, caso...).
        flag:   ADDITION | CHANGE | DELETION (django.contrib.admin.models).

    Returns:
        LogEntry creado, o None si algo fallo.
    """
    try:
        autenticado = bool(getattr(user, "is_authenticated", False))
        if not autenticado:
            user = None

        content_type_id = None
        object_id = None
        object_repr = "Sistema"

        if obj is not None:
            content_type_id = ContentType.objects.get_for_model(obj).pk
            object_id = str(getattr(obj, "pk", "") or "")
            object_repr = str(obj)[:MAX_REPR]

        return LogEntry.objects.create(
            user=user,
            content_type_id=content_type_id,
            object_id=object_id,
            object_repr=object_repr,
            action_flag=flag,
            change_message=str(accion),
        )
    except Exception as exc:  # noqa: BLE001 - la auditoria jamas rompe la peticion
        logger.warning(f"[AUDITORIA] No se pudo registrar '{accion}': {exc}")
        return None
