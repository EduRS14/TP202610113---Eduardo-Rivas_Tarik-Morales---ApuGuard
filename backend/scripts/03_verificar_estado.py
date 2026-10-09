"""
03_verificar_estado.py
=======================
Muestra el estado actual del sistema en base de datos:
  - Capturas satelitales recientes
  - Parches por estado (PENDIENTE/PROCESADO/ERROR)
  - Casos de auditoria recientes
  - Resumen por tipo de caso y estado ecologico

Uso (dentro del contenedor web):
    docker compose exec web python /app/scripts/03_verificar_estado.py
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

from core.models import CapturaSatelital, ParcheProcesamiento, CasoAuditoria, SectorReserva, TecnicoCampo, RegistroSMS


def main():
    print("=" * 70)
    print(" APU GUARD - Estado del sistema")
    print("=" * 70)

    print("\n[CAPTURAS SATELITALES] (ultimas 5)")
    capturas = list(CapturaSatelital.objects.all().order_by("-fecha_adquisicion")[:5])
    if not capturas:
        print("  (sin capturas registradas)")
    for c in capturas:
        print(f"  Captura {c.pk}: {c.fecha_adquisicion} | {c.estado_liberacion} | nubes={c.cobertura_nubes:.1f}%")

    print("\n[PARCHES DE PROCESAMIENTO]")
    total = ParcheProcesamiento.objects.count()
    por_estado = {}
    for p in ParcheProcesamiento.objects.all():
        por_estado[p.estado_sagemaker] = por_estado.get(p.estado_sagemaker, 0) + 1
    print(f"  Total: {total}")
    if total == 0:
        print("  (sin parches registrados - ejecuta el script 04 para lanzar la quincena)")
    for estado, count in sorted(por_estado.items()):
        print(f"    {estado}: {count}")

    print("\n[CASOS DE AUDITORIA]")
    casos = CasoAuditoria.objects.all()
    print(f"  Total casos: {casos.count()}")
    if casos.exists():
        for tipo, _ in CasoAuditoria.TipoCaso.choices:
            n = casos.filter(tipo_caso=tipo).count()
            print(f"    {tipo}: {n}")
        for estado, _ in CasoAuditoria.EstadoEcologico.choices:
            n = casos.filter(estado_ecologico=estado).count()
            print(f"    Estado ecologico {estado}: {n}")
        print("\n  Ultimos 5 casos:")
        for c in casos.order_by("-fecha_creacion")[:5]:
            print(f"    Caso {c.pk}: {c.tipo_caso} | {c.estado_caso} | "
                  f"confianza={c.score_confianza:.2f} | {c.estado_ecologico}")

    print("\n[SECTORES DE RESERVA]")
    ns = SectorReserva.objects.filter(activo=True).count()
    print(f"  Sectores activos: {ns}/5")

    print("\n[TECNICOS DE CAMPO Y SMS]")
    nt = TecnicoCampo.objects.filter(activo=True).count()
    nsms = RegistroSMS.objects.count()
    print(f"  Tecnicos activos: {nt}")
    print(f"  SMS enviados (total): {nsms}")
    if nsms:
        for est, _ in RegistroSMS.EstadoSMS.choices:
            n = RegistroSMS.objects.filter(estado=est).count()
            print(f"    {est}: {n}")

    print("\n" + "=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
