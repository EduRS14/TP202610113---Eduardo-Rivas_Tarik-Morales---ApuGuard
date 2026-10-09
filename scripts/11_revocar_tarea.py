"""
11_revocar_tarea.py
====================
Revoca una tarea Celery por su task_id.

Uso (dentro del contenedor web):
    docker compose exec web python /app/scripts/11_revocar_tarea.py <TASK_ID>
    TASK_ID se obtiene de los logs de celery_worker o de la respuesta de
    procesar_*.delay()
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

from apuguard.celery import app


def main():
    if len(sys.argv) < 2:
        print("Uso: python 11_revocar_tarea.py <TASK_ID> [--terminar]")
        print("")
        print("Ejemplo:")
        print("  python 11_revocar_tarea.py 5abd0500-c68b-440e-9995-95b2582e2e58")
        print("  python 11_revocar_tarea.py 5abd0500-c68b-440e-9995-95b2582e2e58 --terminar")
        return 1

    task_id = sys.argv[1]
    terminar = "--terminar" in sys.argv

    print(f"Revocando tarea {task_id} (terminate={terminar})")
    app.control.revoke(task_id, terminate=terminar, signal="SIGKILL" if terminar else "SIGTERM")
    print(f"[OK] Tarea {task_id} revocada.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
