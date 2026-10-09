"""
0007_backfill_capturas_casos.py
===============================
Backfill de los campos de historial entre pasadas creados en 0006.

  captura_nacimiento        -> captura del parche del caso
  captura_ultima_deteccion  -> misma captura (no se conoce una posterior)
  captura_ultimo_ciclo      -> misma captura
  veces_detectado           -> ya es 1 por defecto

Se agrupa por captura y se actualiza por lotes para no disparar
2.746 UPDATEs individuales.
"""
from django.db import migrations


def backfill_capturas(apps, schema_editor):
    CasoAuditoria = apps.get_model("core", "CasoAuditoria")

    pendientes = list(
        CasoAuditoria.objects
        .filter(captura_nacimiento__isnull=True)
        .values_list("id", "parche__captura")
    )
    if not pendientes:
        return

    por_captura = {}
    for caso_id, captura_id in pendientes:
        por_captura.setdefault(captura_id, []).append(caso_id)

    actualizados = 0
    for captura_id, caso_ids in por_captura.items():
        if captura_id is None:
            # Casos huerfanos (sin parche o parche sin captura): se dejan
            # en NULL para que la ausencia de historial sea visible.
            continue
        for i in range(0, len(caso_ids), 500):
            lote = caso_ids[i:i + 500]
            actualizados += CasoAuditoria.objects.filter(id__in=lote).update(
                captura_nacimiento_id=captura_id,
                captura_ultima_deteccion_id=captura_id,
                captura_ultimo_ciclo_id=captura_id,
            )

    print(f"[0007] backfill: {actualizados} casos vinculados a su captura "
          f"({len(por_captura)} captura(s) distintas)")


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0006_casoauditoria_captura_nacimiento_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill_capturas, migrations.RunPython.noop),
    ]
