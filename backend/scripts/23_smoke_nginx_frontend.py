#!/usr/bin/env python
"""
23_smoke_nginx_frontend.py — Fase C

Verifica el frontend de produccion servido por nginx:
  * SPA: / y /login devuelven index.html con Cache-Control: no-cache
  * bundle con fingerprint -> 200 + Cache-Control: public, immutable
  * /assets/logo.jpeg     -> 200 + Cache-Control: public (sin immutable)
  * favicon.ico           -> 200 y NO immutable
  * gzip negociado
  * reverse proxy hacia Django: /api/auth/token/ -> 405, /admin/login/ -> 200

Uso (contenedor suelto en la red de compose):
  docker run -d --name nginx_test --network apuguard_stac_default \\
             -p 8080:80 apuguard-frontend:prod
  python scripts/23_smoke_nginx_frontend.py --base http://localhost:8080

Uso (servicio ya levantado):
  python scripts/23_smoke_nginx_frontend.py --base http://localhost
"""
import argparse
import re
import urllib.error
import urllib.request

UA = "apuguard-smoke/1.0"
_HOST = {"value": ""}


def _get(base, ruta, gzip=False):
    req = urllib.request.Request(base + ruta, headers={"User-Agent": UA})
    if _HOST["value"]:
        # Django valida el header Host contra ALLOWED_HOSTS; al entrar por
        # host.docker.internal o por la IP del contenedor no coincidiria.
        req.add_header("Host", _HOST["value"])
    if gzip:
        req.add_header("Accept-Encoding", "gzip")
    try:
        resp = urllib.request.urlopen(req, timeout=20)
        return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), b""
    except Exception as exc:  # noqa: BLE001
        return None, {"error": str(exc)}, b""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8080")
    ap.add_argument("--admin", default="/admin/login/")
    ap.add_argument(
        "--host-header", default="",
        help="Fuerza el header Host (p.ej. localhost). Necesario cuando se "
             "entra por host.docker.internal o por una IP y Django rechaza "
             "el Host por ALLOWED_HOSTS.",
    )
    args = ap.parse_args()
    _HOST["value"] = args.host_header
    base = args.base.rstrip("/")

    pruebas = []   # (etiqueta, condicion)

    # 1. Raiz -> index.html sin cache
    cod, hdr, body = _get(base, "/")
    html = body.decode("utf-8", "replace")
    pruebas.append(("GET / -> 200", cod == 200))
    pruebas.append(("GET / es HTML", "text/html" in hdr.get("Content-Type", "")))
    pruebas.append(
        ("index.html con no-cache", "no-cache" in hdr.get("Cache-Control", "")),
    )

    # 2. Ruta de Angular -> fallback a index.html
    cod2, hdr2, body2 = _get(base, "/login")
    pruebas.append(("GET /login -> 200 (SPA)", cod2 == 200))
    pruebas.append(
        ("SPA devuelve index.html", b"<base href=\"/\">" in body2),
    )

    # 3. Bundle con fingerprint -> immutable
    m = re.search(r'(?:src|href)="(main-[\w]{8}\.js)"', html)
    pruebas.append(("index.html referencia main-<hash>.js", m is not None))
    if m:
        cod3, hdr3, _ = _get(base, "/" + m.group(1))
        pruebas.append((f"GET /{m.group(1)} -> 200", cod3 == 200))
        pruebas.append(
            (f"/{m.group(1)} immutable",
             "immutable" in hdr3.get("Cache-Control", "")),
        )

    # 4. Asset sin fingerprint -> cache corta, no immutable
    cod4, hdr4, _ = _get(base, "/assets/logo.jpeg")
    pruebas.append(("GET /assets/logo.jpeg -> 200", cod4 == 200))
    pruebas.append(
        ("/assets/logo.jpeg sin immutable",
         "immutable" not in hdr4.get("Cache-Control", "")),
    )

    # 5. favicon -> 200 y no cae en el patron de hash
    cod5, hdr5, _ = _get(base, "/favicon.ico")
    pruebas.append(("GET /favicon.ico -> 200", cod5 == 200))
    pruebas.append(
        ("/favicon.ico sin immutable",
         "immutable" not in hdr5.get("Cache-Control", "")),
    )

    # 6. gzip
    cod6, hdr6, _ = _get(base, "/", gzip=True)
    pruebas.append(("gzip negociado", hdr6.get("Content-Encoding") == "gzip"))

    # 7. Reverse proxy a Django (gunicorn)
    cod7, _, _ = _get(base, "/api/auth/token/")
    pruebas.append(("proxy /api/auth/token/ -> 405 (Django)", cod7 == 405))
    cod8, hdr8, _ = _get(base, args.admin)
    pruebas.append((f"proxy {args.admin} -> 200 (Django)", cod8 == 200))
    pruebas.append(
        ("admin respuesta de Django",
         "text/html" in hdr8.get("Content-Type", "")),
    )

    fallos = 0
    for etiqueta, ok in pruebas:
        if not ok:
            fallos += 1
        print(f"[{'PASA' if ok else 'FALLA'}] {etiqueta}")

    print(f"\nResultado: {len(pruebas) - fallos}/{len(pruebas)} PASAN")
    print("VEREDICTO: " + ("PASA" if fallos == 0 else "FALLA"))
    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
