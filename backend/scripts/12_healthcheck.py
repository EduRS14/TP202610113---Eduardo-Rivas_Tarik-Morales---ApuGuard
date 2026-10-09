"""
12_healthcheck.py
=================
Verifica que los endpoints REST de la API y el frontend esten respondiendo.

Uso (dentro del contenedor web):
    docker compose exec web python /app/scripts/12_healthcheck.py

Uso (desde el host, con el stack levantado):
    python backend/scripts/12_healthcheck.py

Notas:
  * `POST /api/auth/token/` con body JSON vacio debe devolver 400: demuestra
    que el enrutado, el parser JSON y el serializer JWT estan operativos.
    (Con GET devuelve 405 porque el endpoint es solo POST.)
  * Si se ejecuta DENTRO del contenedor `web`, `localhost` referiria al propio
    contenedor para el frontend; en ese caso se usa `host.docker.internal` y se
    fuerza `Host: localhost` (webpack-dev-server rechaza con 403 hosts ajenos).
"""
import os
import sys
import urllib.parse
import urllib.request
import urllib.error

EN_CONTENEDOR = os.path.exists("/.dockerenv")

API_BASE = os.environ.get("API_BASE", "http://localhost:8000/api")
FRONTEND_BASE = os.environ.get(
    "FRONTEND_BASE",
    "http://host.docker.internal:4200" if EN_CONTENEDOR else "http://localhost:4200",
)

# Host header que espera el dev-server de Angular (ignora host.docker.internal)
_FRONTEND_PUERTO = urllib.parse.urlsplit(FRONTEND_BASE).port or 80
FRONTEND_HOST = f"localhost:{_FRONTEND_PUERTO}"

# El Host solo se sobrescribe cuando el frontend es el dev-server local:
# forzarlo contra una URL publica (CloudFront) provoca 403, porque el
# distribuidor rechaza un Host que no es su dominio.
_SON_DEV_SERVER = (urllib.parse.urlsplit(FRONTEND_BASE).hostname
                   in ("localhost", "127.0.0.1", "host.docker.internal"))

BODY_JWT_VACIO = b'{"username":"","password":""}'

# En produccion SECURE_SSL_REDIRECT=True y, si la sonda pega directamente a
# gunicorn, no ve X-Forwarded-Proto: Django devuelve 301 a https:// y urllib
# intenta TLS contra el 8000. Con HEALTH_PROTO=https la peticion llega como
# si fuese HTTPS y se queda en el 200/401 esperado.
_PROTO = os.environ.get("HEALTH_PROTO", "").strip()
_HDR_PROTO = ({"X-Forwarded-Proto": _PROTO,
               "CloudFront-Forwarded-Proto": _PROTO} if _PROTO else {})


def check(name, url, expected, method="GET", body=None, headers=None):
    """Hace una peticion y compara el codigo HTTP con `expected` (int)."""
    try:
        req = urllib.request.Request(url, data=body,
                                     headers={**_HDR_PROTO, **(headers or {})},
                                     method=method)
        if body is not None:
            req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=5) as resp:
            code = resp.getcode()
    except urllib.error.HTTPError as e:
        code = e.code
    except Exception as e:
        print(f"  [FAIL] {name} ({url}) -> error: {e}")
        return False
    if code == expected:
        print(f"  [OK]   {name} ({url}) -> {code}")
        return True
    print(f"  [FAIL] {name} ({url}) -> {code} (esperado {expected})")
    return False


def main():
    print("=" * 60)
    print(" APU GUARD - Healthcheck de API")
    print("=" * 60)
    print(f"API Base:     {API_BASE}")
    print(f"Frontend:     {FRONTEND_BASE}")
    if EN_CONTENEDOR:
        det = (f"Host: {FRONTEND_HOST}" if _SON_DEV_SERVER
               else "Host del propio frontend")
        print(f"Entorno:      contenedor (frontend via host.docker.internal, {det})")
    if _PROTO:
        print(f"HEALTH_PROTO: {_PROTO}")
    print()

    results = []
    results.append(check("GET  /api/sectores/",        f"{API_BASE}/sectores/",        401))
    results.append(check("GET  /api/alertas/",         f"{API_BASE}/alertas/",         401))
    results.append(check("GET  /api/dashboard/stats/", f"{API_BASE}/dashboard/stats/", 401))
    results.append(check("GET  /api/dashboard/audit-logs/", f"{API_BASE}/dashboard/audit-logs/", 401))
    results.append(check("POST /api/auth/token/",      f"{API_BASE}/auth/token/",      400,
                         method="POST", body=BODY_JWT_VACIO))
    results.append(check("GET  /admin/",  f"{API_BASE.rsplit('/api', 1)[0]}/admin/", 200))
    results.append(check("GET  / (frontend)",          FRONTEND_BASE,                  200,
                         headers={"Host": FRONTEND_HOST} if _SON_DEV_SERVER else None))

    print()
    total = len(results)
    ok = sum(results)
    print(f"Resultado: {ok} / {total} checks OK")
    if ok == total:
        print("[OK] Todos los servicios respondiendo.")
        return 0
    print("[WARN] Hay servicios que no responden. Revisa docker compose ps")
    return 1


if __name__ == "__main__":
    sys.exit(main())
