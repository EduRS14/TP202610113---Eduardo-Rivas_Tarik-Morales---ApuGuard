"""
04_lanzar_quincena.py
======================
Lanza manualmente la tarea procesar_quincena_tambopata.

Esta tarea descarga el composite Sentinel-2 desde la fuente configurada
(IMAGERY_SOURCE: STAC/AWS por defecto, GEE opcional), lo procesa y
envia parches a SageMaker para inferencia.

Uso (dentro del contenedor web):
    docker compose exec web python /app/scripts/04_lanzar_quincena.py
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

from ml_engine.tasks import procesar_quincena_tambopata


def main():
    print("Lanzando tarea: procesar_quincena_tambopata (forzar=True)")
    # forzar=True: la tarea tiene una guarda que, sin forzar, solo deja
    # pasar los dias 1/16 (proteccion contra el catch-up de beat).
    resultado = procesar_quincena_tambopata.delay(forzar=True)
    print(f"[OK] Tarea encolada. task_id = {resultado.id}")
    print(f"     Monitorea con: docker compose logs -f celery_worker")
    return 0


if __name__ == "__main__":
    sys.exit(main())
