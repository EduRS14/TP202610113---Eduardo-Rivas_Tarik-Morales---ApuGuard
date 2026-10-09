"""
01_cargar_sectores.py
======================
Carga o actualiza los 5 sectores de monitoreo APU GUARD en la base de datos.

Cobertura: bbox completo TAMBOPATA_BBOX (lon -70.10..-68.74, lat -12.50..-13.18)

  SEC-01  Frontera Agricola Oeste   (Mazuko, Laberinto)
  SEC-02  Puerto Maldonado          (Area periurbana, Rio Madre de Dios)
  SEC-03  Zona de Amortiguamiento   (ZA oficial RN Tambopata)
  SEC-04  RN Tambopata Norte        (Nucleo norte Reserva)
  SEC-05  Rio Heath                 (Cuenca Heath / PN Bahuaja Sonene)

Uso (dentro del contenedor web):
    docker compose exec web python /app/scripts/01_cargar_sectores.py
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

from django.contrib.gis.geos import GEOSGeometry
from core.models import SectorReserva


SECTORES = [
    {
        "nombre": "Frontera Agricola Oeste",
        "codigo": "SEC-01",
        "geom":   "POLYGON((-70.10 -13.18, -69.50 -13.18, -69.50 -12.50, -70.10 -12.50, -70.10 -13.18))",
    },
    {
        "nombre": "Puerto Maldonado",
        "codigo": "SEC-02",
        "geom":   "POLYGON((-69.50 -12.84, -69.20 -12.84, -69.20 -12.50, -69.50 -12.50, -69.50 -12.84))",
    },
    {
        "nombre": "Zona de Amortiguamiento",
        "codigo": "SEC-03",
        "geom":   "POLYGON((-69.50 -13.18, -69.20 -13.18, -69.20 -12.84, -69.50 -12.84, -69.50 -13.18))",
    },
    {
        "nombre": "RN Tambopata Norte",
        "codigo": "SEC-04",
        "geom":   "POLYGON((-69.20 -12.84, -68.74 -12.84, -68.74 -12.50, -69.20 -12.50, -69.20 -12.84))",
    },
    {
        "nombre": "Rio Heath",
        "codigo": "SEC-05",
        "geom":   "POLYGON((-69.20 -13.18, -68.74 -13.18, -68.74 -12.84, -69.20 -12.84, -69.20 -13.18))",
    },
]


def main():
    creados = 0
    actualizados = 0
    for s in SECTORES:
        geom_obj = GEOSGeometry(s["geom"], srid=4326)
        obj, created = SectorReserva.objects.get_or_create(
            codigo=s["codigo"],
            defaults={"nombre": s["nombre"], "geom": geom_obj, "activo": True},
        )
        if created:
            print(f"  CREADO:      {obj.codigo} - {obj.nombre}")
            creados += 1
        else:
            obj.nombre = s["nombre"]
            obj.geom   = geom_obj
            obj.activo = True
            obj.save(update_fields=["nombre", "geom", "activo"])
            print(f"  ACTUALIZADO: {obj.codigo} - {obj.nombre}")
            actualizados += 1

    print(f"\nResumen: {creados} creados, {actualizados} actualizados, {creados + actualizados}/5 total")
    print("\nCobertura del bbox [-70.10..-68.74, -12.50..-13.18]:")
    for s in SectorReserva.objects.filter(activo=True).order_by("codigo"):
        ext = s.geom.extent
        print(f"  {s.codigo} {s.nombre}: lon {ext[0]:.2f}..{ext[2]:.2f}, lat {ext[1]:.2f}..{ext[3]:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
