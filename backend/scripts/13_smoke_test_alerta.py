"""
13_smoke_test_alerta.py
=========================
Crea un CasoAuditoria manual con geometria sintetica para probar
el flujo end-to-end de visualizacion en el frontend.

Uso (dentro del contenedor web):
    docker compose exec web python /app/scripts/13_smoke_test_alerta.py
"""
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _template_python import setup
setup()

import django
django.setup()

from django.contrib.gis.geos import MultiPolygon, Polygon
from core.models import CasoAuditoria, CapturaSatelital, ParcheProcesamiento, SectorReserva


def main():
    captura = CapturaSatelital.objects.order_by("-pk").first()
    if not captura:
        print("[ERROR] No hay capturas en BD. Ejecuta primero 04_lanzar_quincena.py")
        return 1

    parche = (
        ParcheProcesamiento.objects.filter(captura=captura)
        .order_by("fila_idx", "col_idx")
        .first()
    )
    if not parche:
        print(f"[ERROR] No hay parches para la captura {captura.pk}.")
        return 1

    sectores = list(SectorReserva.objects.filter(activo=True))
    if not sectores:
        print("[ERROR] No hay sectores activos. Ejecuta 01_cargar_sectores.py")
        return 1

    bbox = parche.geom.extent
    poly = Polygon.from_bbox(bbox)
    geom = MultiPolygon(poly, srid=4326)

    caso = CasoAuditoria.objects.create(
        parche=parche,
        tipo_caso=CasoAuditoria.TipoCaso.DETECCION,
        estado_caso=CasoAuditoria.EstadoCaso.PENDIENTE_REVISION,
        score_confianza=0.87,
        geom_afectada=geom,
        estado_ecologico=CasoAuditoria.EstadoEcologico.PERTURBADO,
        ciclos_limpios_consecutivos=0,
    )
    caso.sectores.set(sectores)

    print(f"[OK] CasoAuditoria #{caso.pk} creado (smoke test)")
    print(f"     Captura   : {captura.pk}")
    print(f"     Parche    : fila={parche.fila_idx} col={parche.col_idx}")
    print(f"     Tipo      : {caso.tipo_caso}")
    print(f"     Confianza : {caso.score_confianza}")
    print(f"     Estado    : {caso.estado_caso}")
    print(f"     Sectores  : {', '.join(s.codigo for s in sectores)}")
    print(f"\nVisualizalo en: http://localhost:4200/alertas")
    return 0


if __name__ == "__main__":
    sys.exit(main())
