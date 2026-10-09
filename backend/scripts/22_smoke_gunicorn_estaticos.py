#!/usr/bin/env python
"""
22_smoke_gunicorn_estaticos.py — Fase B

Verifica que el servidor WSGI real (gunicorn) arranca y sirve:
  * la vista de admin (Django respondiendo tras el WSGI)
  * los estaticos de Admin/DRF en su nombre original
  * los mismos estaticos con fingerprint (manifest de WhiteNoise)
  * un endpoint DRF (/api/auth/token/)

Se arranca un gunicorn temporal en DEBUG=False (modo produccion) para que
activen la manifest storage y la compresion de WhiteNoise; al terminar se
detiene. El servidor real de produccion se arranca con el CMD del Dockerfile.

Uso:  python scripts/22_smoke_gunicorn_estaticos.py [--puerto 8001]
"""
import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request

PUERTO = int(os.environ.get("PUERTO_SMOKE_WSGI", "8001"))
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_ROOT = os.path.join(BASE_DIR, "staticfiles")

OBJETIVOS = [
    ("/admin/login/", 200),
    ("/static/admin/css/base.css", 200),
    ("/static/rest_framework/js/coreapi-0.1.1.js", 200),
    ("/api/auth/token/", 405),
]


def _colectar_estaticos():
    """collectstatic en modo produccion (DEBUG=False)."""
    env = dict(os.environ, DEBUG="False")
    r = subprocess.run(
        [sys.executable, "manage.py", "collectstatic", "--noinput"],
        cwd=BASE_DIR, env=env, capture_output=True, text=True,
    )
    if r.returncode != 0:
        print("[FALLA] collectstatic (DEBUG=False):")
        print(r.stdout, r.stderr)
        return False
    print(f"[PASA] collectstatic (DEBUG=False): {r.stdout.strip().splitlines()[-1]}")
    return True


def _saltar_manifest():
    with open(os.path.join(STATIC_ROOT, "staticfiles.json"), encoding="utf-8") as fh:
        return json.load(fh)["paths"]


def _arrancar_gunicorn():
    env = dict(
        os.environ,
        DEBUG="False",
        DJANGO_SETTINGS_MODULE=os.environ.get("DJANGO_SETTINGS_MODULE", "apuguard.settings"),
    )
    # PID de una ejecucion anterior no debe confundir a gunicorn.
    pidfile = "/tmp/gunicorn_smoke.pid"
    if os.path.exists(pidfile):
        os.remove(pidfile)
    log = open(os.path.join(BASE_DIR, "gunicorn_smoke.log"), "w")
    return subprocess.Popen(
        [
            sys.executable, "-m", "gunicorn", "apuguard.wsgi:application",
            "--bind", f"127.0.0.1:{PUERTO}",
            "--workers", "1", "--threads", "2", "--timeout", "60",
            "--error-logfile", "-", "--pid", "/tmp/gunicorn_smoke.pid",
        ],
        cwd=BASE_DIR, env=env, stdout=log, stderr=subprocess.STDOUT,
    )


def _probar(manifest):
    objetivos = list(OBJETIVOS)
    hash_css = manifest.get("admin/css/base.css")
    hash_js = manifest.get("rest_framework/js/coreapi-0.1.1.js")
    if hash_css:
        objetivos.append((f"/static/{hash_css}", 200))
    if hash_js:
        objetivos.append((f"/static/{hash_js}", 200))

    fallos = 0
    for ruta, esperado in objetivos:
        try:
            resp = urllib.request.urlopen(f"http://127.0.0.1:{PUERTO}{ruta}", timeout=15)
            codigo = resp.status
        except urllib.error.HTTPError as exc:
            codigo = exc.code
        except Exception as exc:  # noqa: BLE001
            print(f"[FALLA] {ruta} -> {exc}")
            fallos += 1
            continue
        ok = codigo == esperado
        fallos += 0 if ok else 1
        print(f"[{'PASA' if ok else 'FALLA'}] {ruta} -> {codigo} (esperado {esperado})")

    print(f"\nResultado: {len(objetivos) - fallos}/{len(objetivos)} PASAN")
    return fallos


def main():
    if not _colectar_estaticos():
        print("\nVEREDICTO: FALLA")
        return 1

    try:
        manifest = _saltar_manifest()
    except Exception as exc:  # noqa: BLE001
        print(f"[FALLA] staticfiles.json ilegible: {exc}")
        print("\nVEREDICTO: FALLA")
        return 1

    if not os.path.isdir(os.path.join(STATIC_ROOT, "admin")):
        print("[FALLA] STATIC_ROOT no contiene /admin: ¿collectstatic no corrio?")
        print("\nVEREDICTO: FALLA")
        return 1
    print(f"[PASA] STATIC_ROOT poblado ({len(manifest)} entradas en el manifest)")

    proc = _arrancar_gunicorn()
    try:
        for _ in range(30):
            time.sleep(1)
            # El proceso propio debe seguir vivo: si murio es que no pudo
            # arrancar (puerto ocupado, import error, etc.)
            if proc.poll() is not None:
                print(f"[FALLA] gunicorn propio termino (codigo {proc.returncode})")
                print("\nVEREDICTO: FALLA")
                return 1
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{PUERTO}/admin/login/", timeout=3)
                break
            except urllib.error.HTTPError:
                break
            except Exception:  # noqa: BLE001
                continue
        else:
            print("[FALLA] gunicorn no respondio en 30 s")
            print("\nVEREDICTO: FALLA")
            return 1
        print(f"[PASA] gunicorn arriba en 127.0.0.1:{PUERTO} (pid {proc.pid})")

        fallos = _probar(manifest)
    finally:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()

    print("VEREDICTO: " + ("PASA" if fallos == 0 else "FALLA"))
    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
