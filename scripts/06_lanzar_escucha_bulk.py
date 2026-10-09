"""
06_lanzar_escucha_bulk.py
==========================
Lanza procesar_resultado_sagemaker 10 veces seguidas para vaciar
la cola SQS cuando hay muchos mensajes acumulados.

Uso (dentro del contenedor web):
    docker compose exec web python /app/scripts/06_lanzar_escucha_bulk.py
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

from ml_engine.tasks import procesar_resultado_sagemaker


def main():
    n = 10
    print(f"Lanzando {n} tareas de escucha SQS...")
    ids = []
    for i in range(n):
        r = procesar_resultado_sagemaker.delay()
        ids.append(r.id)
    print(f"[OK] {n} tareas encoladas:")
    for tid in ids:
        print(f"     - {tid}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
