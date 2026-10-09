#!/usr/bin/env python
"""
26_smoke_prod_https.py — Fase D

Comprueba la URL publica de produccion (CloudFront -> nginx -> gunicorn).

Se ejecuta desde dentro de la instancia:

    python3 backend/scripts/26_smoke_prod_https.py
    python3 backend/scripts/26_smoke_prod_https.py --url https://dxxx.cloudfront.net

Comprobaciones:
  A. GET  /api/sectores/      -> 401  (Django vivo, sin token)
  B. POST /api/auth/token/    -> 400  (el POST atraviesa CloudFront)
  C. GET  /admin/             -> 200  (WhiteNoise sirve el admin)
  D. GET  /                   -> 200 y Cache-Control: no-cache (index.html)
  E. asset con fingerprint    -> immutable y x-cache: Hit en la 2a peticion
  F. Strict-Transport-Security presente
  G. el origen no responde fuera de CloudFront (SG con prefix list)

A, B y C ademas cuentan los saltos de redirect: mas de uno significa
SECURE_SSL_REDIRECT en bucle (CloudFront llega por HTTP al origen y Django
le devolveria un 301 a https:// que el origen no puede servir).

Tambien valida que Django haya visto la peticion como HTTPS: si hubiera
redirigido, es que llego X-Forwarded-Proto=http y el map de nginx no esta
traduciendo CloudFront-Forwarded-Proto.

Sin curl en la imagen: se usa urllib de la libreria estandar.
"""
import argparse
import re
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request

UA = "apuguard-smoke/1.0"
TIMEOUT = 20
BODY_JWT_VACIO = b"{}"

resultados = {"PASA": [], "FALLA": [], "ADVERTENCIA": []}


def pasa(msg):
    resultados["PASA"].append(msg)


def falla(msg):
    resultados["FALLA"].append(msg)


def aviso(msg):
    resultados["ADVERTENCIA"].append(msg)


class SinRedirect(urllib.request.HTTPRedirectHandler):
    """Devolvemos None para que urllib NO siga la redireccion y podamos
    contar los saltos a mano."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


OPENER = urllib.request.build_opener(SinRedirect)


def pedir(url, saltos_max=3, metodo=None, cuerpo=None, extra=None):
    """Sigue la cadena de redirects contandolos.

    Devuelve (status, headers, cuerpo, saltos, url_final, error).
    """
    actual = url
    saltos = 0
    while True:
        req = urllib.request.Request(
            actual, data=cuerpo, method=metodo,
            headers={"User-Agent": UA, **(extra or {})})
        try:
            with OPENER.open(req, timeout=TIMEOUT) as resp:
                return resp.status, dict(resp.headers), resp.read(), saltos, actual, ""
        except urllib.error.HTTPError as exc:
            if exc.code in (301, 302, 303, 307, 308):
                loc = exc.headers.get("Location")
                saltos += 1
                if not loc:
                    return exc.code, dict(exc.headers), b"", saltos, actual, "sin Location"
                if saltos > saltos_max:
                    return exc.code, dict(exc.headers), b"", saltos, actual, \
                        f"mas de {saltos_max} saltos (bucle)"
                actual = urllib.parse.urljoin(actual, loc)
                continue
            return exc.code, dict(exc.headers), b"", saltos, actual, ""
        except Exception as exc:  # noqa: BLE001
            return None, {}, b"", saltos, actual, f"{type(exc).__name__}: {exc}"


def _imds(ruta, token=None):
    req = urllib.request.Request("http://169.254.169.254/latest" + ruta)
    if token:
        req.add_header("X-aws-ec2-metadata-token", token)
    with urllib.request.urlopen(req, timeout=3) as resp:
        return resp.read().decode().strip()


def ip_publica_instancia():
    try:
        req = urllib.request.Request(
            "http://169.254.169.254/latest/api/token", method="PUT")
        req.add_header("X-aws-ec2-metadata-token-ttl-seconds", "60")
        with urllib.request.urlopen(req, timeout=3) as resp:
            token = resp.read().decode().strip()
        return _imds("/meta-data/public-ipv4", token)
    except Exception:  # noqa: BLE001
        return None


def comprobar(nombre, url, esperado, saltos_max=3, **kw):
    """GET/POST con conteo de saltos. esperado es un int o una tupla."""
    st, hd, _c, saltos, final, err = pedir(url, saltos_max=saltos_max, **kw)
    esperados = esperado if isinstance(esperado, tuple) else (esperado,)
    etiqueta = f"{nombre} -> {st}"
    if err:
        falla(f"{nombre} -> {err} (status={st})")
    elif st in esperados:
        pasa(f"{etiqueta} en {saltos} salto(s)")
    else:
        falla(f"{etiqueta} (esperaba {esperados})")
    if saltos > 1:
        falla(f"{nombre}: {saltos} saltos de redirect -> "
              "SECURE_SSL_REDIRECT en bucle")
    return st, hd, saltos, err


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="",
                    help="https://dxxxxxxxxxxxx.cloudfront.net")
    args = ap.parse_args()

    url = (args.url or "").rstrip("/")
    if not url:
        print("[FALLA] falta --url <https://...cloudfront.net>")
        return 1

    es_cloudfront = url.startswith("https://") and ".cloudfront.net" in url
    print(f"URL bajo prueba: {url}")
    if not es_cloudfront:
        print("[ADVERTENCIA] no es una URL de CloudFront: se omiten las")
        print("              comprobaciones de TLS/HSTS/cache/origen.")
    print()

    # --- A. Django contesta ------------------------------------------------
    st, hd, saltos, err = comprobar("GET  /api/sectores/", f"{url}/api/sectores/", 401)

    # --- B. El POST atraviesa CloudFront -----------------------------------
    comprobar("POST /api/auth/token/", f"{url}/api/auth/token/", 400,
              metodo="POST", cuerpo=BODY_JWT_VACIO,
              extra={"Content-Type": "application/json"})

    # --- C. Admin (estaticos via WhiteNoise) -------------------------------
    comprobar("GET  /admin/", f"{url}/admin/", 200)

    if es_cloudfront and st is not None and saltos == 0:
        pasa("Django vio la peticion como HTTPS (X-Forwarded-Proto ok)")
    elif es_cloudfront and saltos:
        falla("Django la vio como HTTP: revisa el map de nginx "
              "($http_cloudfront_forwarded_proto)")

    # --- D. index.html no cacheado ----------------------------------------
    st_i, hd_i, cuerpo_i, _s_i, _f_i, err_i = pedir(f"{url}/", saltos_max=3)
    cc = (hd_i.get("Cache-Control") or hd_i.get("cache-control") or "")
    if err_i:
        aviso(f"GET / -> {err_i}")
    elif st_i == 200 and "no-cache" in cc:
        pasa(f"GET / -> 200 con Cache-Control: {cc}")
    elif es_cloudfront:
        falla(f"GET / -> HTTP {st_i}, Cache-Control={cc or '<vacio>'} "
              "(esperaba 200 + no-cache)")
    else:
        aviso(f"GET / -> HTTP {st_i} (esperado solo con CloudFront)")

    # --- E. Asset con fingerprint cacheado en el borde ---------------------
    if es_cloudfront and not err_i:
        m = re.search(r'(?:src|href)="([^"]*-\w{8}\.(?:js|css))"',
                      cuerpo_i.decode("utf-8", "replace"))
        if not m:
            aviso("no se encontro ningun asset con fingerprint en index.html")
        else:
            asset = urllib.parse.urljoin(url, m.group(1))
            st_a, hd_a, _c_a, _s_a, _f_a, err_a = pedir(asset, saltos_max=1)
            cc_a = (hd_a.get("Cache-Control") or "")
            if err_a or st_a != 200:
                falla(f"asset -> HTTP {st_a} {err_a}")
            else:
                if "immutable" in cc_a:
                    pasa(f"asset con Cache-Control: {cc_a}")
                else:
                    falla(f"asset sin immutable: {cc_a or '<vacio>'}")
                _st2, hd2, _c2, _s2, _f2, _e2 = pedir(asset, saltos_max=1)
                xc2 = (hd2.get("X-Cache") or hd2.get("x-cache") or "")
                if xc2.lower().startswith("hit"):
                    pasa(f"2a peticion x-cache: {xc2}")
                else:
                    falla(f"2a peticion x-cache={xc2 or '<vacio>'} (esperaba Hit)")

        # --- F. HSTS -------------------------------------------------------
        _st_h, hd_h, _, _, _, _ = pedir(f"{url}/api/sectores/", saltos_max=1)
        hsts = (hd_h.get("Strict-Transport-Security")
                or hd_h.get("strict-transport-security") or "")
        if hsts:
            pasa(f"Strict-Transport-Security: {hsts}")
        else:
            falla("falta Strict-Transport-Security (SECURE_HSTS_SECONDS?)")

        # --- G. Origen directo bloqueado -----------------------------------
        ip = ip_publica_instancia()
        if not ip:
            aviso("no se pudo leer la IP publica (IMDS); se omite la "
                  "comprobacion de bloqueo del origen")
        else:
            try:
                with socket.create_connection((ip, 80), timeout=5) as s:
                    s.sendall(b"GET / HTTP/1.0\r\nHost: origin\r\n\r\n")
                    s.recv(64)
                falla(f"el origen http://{ip}:80 contesta: cualquiera puede "
                      "saltarse CloudFront (revisa el prefix list del SG)")
            except Exception:  # noqa: BLE001
                pasa(f"origen {ip}:80 inaccesible fuera de CloudFront (SG ok)")

    print()
    for nivel in ("PASA", "ADVERTENCIA", "FALLA"):
        for msg in resultados[nivel]:
            print(f"[{nivel}] {msg}")
    fallos = len(resultados["FALLA"])
    print(f"\n{len(resultados['PASA'])} PASAN, "
          f"{len(resultados['ADVERTENCIA'])} advertencias, {fallos} FALLAN")
    print("VEREDICTO: " + ("FALLA" if fallos else "PASA"))
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
