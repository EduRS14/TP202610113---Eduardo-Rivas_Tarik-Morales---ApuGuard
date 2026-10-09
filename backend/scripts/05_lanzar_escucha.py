"""
05_lanzar_escucha.py
=====================
Lanza manualmente la tarea procesar_resultado_sagemaker (una vez).

Esta tarea escucha SQS, descarga los resultados .npz de SageMaker
y crea CasoAuditoria cuando hay deteccion.

Uso (dentro del contenedor web):
    docker compose exec web python /app/scripts/05_lanzar_escucha.py
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
    print("Lanzando tarea: procesar_resultado_sagemaker (1 vez)")
    resultado = procesar_resultado_sagemaker.delay()
    print(f"[OK] Tarea encolada. task_id = {resultado.id}")
    print(f"     Monitorea con: docker compose logs -f celery_worker")
    return 0


if __name__ == "__main__":
    sys.exit(main())
