#!/usr/bin/env python
"""
25_bootstrap_prod_env.py — Fase D

Genera backend/.env de PRODUCCION a partir de backend/.env.example.

Lo que hace:
  * DJANGO_SECRET_KEY, DB_PASSWORD y POSTGRES_PASSWORD se generan aqui
    (nunca se copian de plantillas). DB_PASSWORD y POSTGRES_PASSWORD son
    IDENTICAS: la imagen postgis usa la segunda en el primer arranque y
    Django usa la primera.
  * Activamos el bloque SECURE_* que en desarrollo tiene que estar apagado
    (con True y HTTP puro Django entra en bucle de redireccion).
  * ALLOWED_HOSTS / CORS / CSRF reciben la URL real de CloudFront.
  * AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY quedan VACIOS: el EC2 usa
    Instance Profile (IAM Role) y boto3 resuelve las credenciales por IMDS,
    sin ningun fichero en disco.
  * El fichero se deja con permisos 600 en POSIX.

Los generadores de secretos se importan de 24_rotar_secretos_dev.py para
que la regla "ningun valor con '$'" viva en un solo sitio: Docker Compose
interpeta $VAR dentro de los env_file y truncaria el valor (bug Fase A').

Nunca imprime secretos, solo longitudes.

Rellenar placeholders (SQS / SNS / Twilio) sin tocar el resto del fichero
ni regenerar secretos: --completar copia del fichero origen SOLO las claves
de CLAVES_COMPLETAR que aqui siguen con placeholder.

Uso (dentro del contenedor web, con el proyecto ya subido al servidor):
  python scripts/25_bootstrap_prod_env.py \\
      --cloudfront-url https://dxxxxxxxxxxxx.cloudfront.net \\
      --ec2-dns ec2-3-4-5-6.compute-1.amazonaws.com          # dry-run
  ... --aplicar                                               # escribe
  python scripts/25_bootstrap_prod_env.py --verificar         # comprueba
  python scripts/25_bootstrap_prod_env.py \\
      --completar /tmp/origen.env --aplicar                  # rellena
"""
import argparse
import importlib.util
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

BASE = Path(__file__).resolve().parent.parent      # /app  (== backend/)
PLANTILLA = BASE / ".env.example"
ENV = BASE / ".env"
SCRIPTS = Path(__file__).resolve().parent

SECRETOS = ("DJANGO_SECRET_KEY", "DB_PASSWORD", "POSTGRES_PASSWORD",
            "TWILIO_AUTH_TOKEN")
MARCADOR = re.compile(r"\A([A-Za-z_0-9]+)=(.*)\Z", re.M)

# Unicas claves que --completar se permite rellenar. NADA de secretos de
# Django ni de base de datos: esos se generan y se rotan aparte (24_*).
CLAVES_COMPLETAR = ("SQS_RESULT_QUEUE_URL", "SNS_ALERT_TOPIC_ARN",
                    "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN",
                    "TWILIO_PHONE_NUMBER")

# En la salida se imprimen solo longitudes.
CLAVAS_SIN_PANTALLA = set(SECRETOS) | {"TWILIO_ACCOUNT_SID"}


def _es_placeholder(valor):
    """True si el valor sigue siendo plantilla sin resolver.

    Cubre 'CAMBIAR'/'PLACEHOLDER', <region>/<cuenta> y el telefono de la
    plantilla '+1XXXXXXXXXX' (antes no se detectaba).
    """
    if not valor:
        return True
    if "CAMBIAR" in valor or "PLACEHOLDER" in valor:
        return True
    if re.search(r"<[a-z0-9_]+>", valor):
        return True
    # '+1XXXXXXXXXX': solo si lleva X, para no marcar el telefono real.
    return bool(re.fullmatch(r"\+[0-9X]{6,}", valor) and "X" in valor)


def _importar_rotador():
    """Carga 24_rotar_secretos_dev.py (el nombre empieza por digito)."""
    ruta = SCRIPTS / "24_rotar_secretos_dev.py"
    spec = importlib.util.spec_from_file_location("rotar_secretos", ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def _pares(texto):
    out = {}
    for linea in texto.splitlines():
        m = re.match(r"\A([A-Za-z_0-9]+)=(.*)\Z", linea)
        if m:
            out[m.group(1)] = m.group(2)
    return out


def _valores_produccion(rotador, args):
    cloudfront_url = (args.cloudfront_url or "").rstrip("/")
    if not cloudfront_url.startswith("https://"):
        raise SystemExit("[FALLA] --cloudfront-url debe empezar por https://")
    dominio = urlparse(cloudfront_url).netloc
    if not dominio:
        raise SystemExit("[FALLA] --cloudfront-url sin dominio valido")

    password = rotador._nuevo_password()

    hosts = [dominio, "web", "localhost", "127.0.0.1"]
    if args.ec2_dns:
        hosts.append(args.ec2_dns)

    valores = {
        # -- Django --
        "DJANGO_SECRET_KEY": rotador._nuevo_secret_key(),
        "DEBUG": "False",
        "ALLOWED_HOSTS": ",".join(hosts),
        "CORS_ALLOWED_ORIGINS": cloudfront_url,
        "CSRF_TRUSTED_ORIGINS": cloudfront_url,
        # -- Seguridad TLS: SOLO en produccion --
        "SECURE_SSL_REDIRECT": "True",
        "SESSION_COOKIE_SECURE": "True",
        "CSRF_COOKIE_SECURE": "True",
        "SECURE_HSTS_SECONDS": "31536000",
        # includeSubDomains y preload se dejan apagados a proposito: HSTS
        # con preload no se puede deshacer y el origen es un
        # *.cloudfront.net que no controlamos del todo.
        "SECURE_HSTS_INCLUDE_SUBDOMAINS": "False",
        "SECURE_HSTS_PRELOAD": "False",
        "SECURE_PROXY_SSL_HEADER": "True",
        # -- Base de datos --
        "DB_PASSWORD": password,
        "POSTGRES_PASSWORD": password,
        "DB_HOST": "db",
        "DB_PORT": "5432",
        # -- AWS: Instance Profile, sin credenciales en disco --
        "AWS_ACCESS_KEY_ID": "",
        "AWS_SECRET_ACCESS_KEY": "",
        # -- Imagenes: STAC no necesita credenciales --
        "IMAGERY_SOURCE": "stac",
    }
    if args.twilio_sid:
        valores["TWILIO_ACCOUNT_SID"] = args.twilio_sid
    if args.twilio_token:
        valores["TWILIO_AUTH_TOKEN"] = args.twilio_token
    if args.twilio_from:
        valores["TWILIO_PHONE_NUMBER"] = args.twilio_from
    return valores


def _escribir(destino: Path, valores) -> int:
    """Sobreescribe los valores indicados y conserva el resto de la
    plantilla, manteniendo su orden y sus comentarios."""
    lineas = []
    for linea in PLANTILLA.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\A([A-Za-z_0-9]+)=(.*)\Z", linea)
        if m:
            clave = m.group(1)
            lineas.append(f"{clave}={valores.get(clave, m.group(2))}")
        else:
            lineas.append(linea)
    destino.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    if os.name == "posix":
        os.chmod(destino, 0o600)
    return len(lineas)


def _escribir_en_sitio(destino: Path, valores):
    """Sobreescribe SOLO las claves indicadas del .env existente:
    conserva el resto del fichero tal cual (a diferencia de _escribir,
    que reconstruye todo desde la plantilla y borraria cambios previos)."""
    if any("$" in v for v in valores.values()):
        malas = [c for c, v in valores.items() if "$" in v]
        raise SystemExit(f"[FALLA] claves con '$': {', '.join(malas)}")
    lineas, aplicadas = [], []
    for linea in destino.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\A([A-Za-z_0-9]+)=(.*)\Z", linea)
        if m and m.group(1) in valores:
            lineas.append(f"{m.group(1)}={valores[m.group(1)]}")
            aplicadas.append(m.group(1))
        else:
            lineas.append(linea)
    faltantes = [c for c in valores if c not in aplicadas]
    if faltantes:
        raise SystemExit(f"[FALLA] no estan en {destino}: "
                         f"{', '.join(faltantes)}")
    destino.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    if os.name == "posix":
        os.chmod(destino, 0o600)
    return aplicadas


def _completar(args) -> int:
    """Rellena desde un fichero origen SOLO las claves de CLAVES_COMPLETAR
    que aqui siguen con placeholder. Jamas toca DJANGO_SECRET_KEY/DB_*."""
    origen = Path(args.completar).expanduser()
    if not origen.exists():
        print(f"[FALLA] no existe el fichero origen: {origen}")
        return 1
    if not ENV.exists():
        print(f"[FALLA] no existe {ENV}")
        return 1

    fuente = _pares(origen.read_text(encoding="utf-8"))
    actual = _pares(ENV.read_text(encoding="utf-8"))

    valores = {}
    for clave in CLAVES_COMPLETAR:
        if clave not in actual:
            print(f"[FALLA] {clave} no esta definida en {ENV}")
            return 1
        if not _es_placeholder(actual[clave]):
            print(f"  {clave:26} ya rellenada, no se toca")
            continue
        nuevo = fuente.get(clave, "")
        if not nuevo or _es_placeholder(nuevo):
            print(f"[FALLA] {clave}: el origen tampoco trae valor real")
            return 1
        valores[clave] = nuevo

    if not valores:
        print("[PASA] nada que rellenar: los 5 valores ya estaban puestos")
        return 0

    print(f"Claves a rellenar (solo longitud): {', '.join(valores)}")
    for clave in sorted(valores):
        marca = ("<len N>" if clave in CLAVAS_SIN_PANTALLA
                 else f"<len {len(valores[clave])}>")
        print(f"  {clave:26} {marca}")

    if not args.aplicar:
        print(f"\nDry-run. Repite con --aplicar para escribir {ENV}.")
        return 0

    _escribir_en_sitio(ENV, valores)
    permisos = ", permisos 600" if os.name == "posix" else ""
    print(f"[PASA] {ENV} actualizado ({len(valores)} claves{permisos})")
    print("Reinicia web/celery_worker/celery_beat para que tomen el env.")
    print("\nVEREDICTO: PASA")
    return 0


def _verificar() -> int:
    if not ENV.exists():
        print(f"[FALLA] no existe {ENV}")
        return 1
    valores = _pares(ENV.read_text(encoding="utf-8"))
    print(f"Verificacion de {ENV}")
    fallos = 0

    for clave in SECRETOS:
        v = valores.get(clave, "")
        etiqueta = v if clave in ("ALLOWED_HOSTS",) else f"<len {len(v)}>"
        print(f"  {clave:26} {etiqueta if v else '<falta>'}")
        if not v:
            fallos += 1

    def check(condicion, ok, malo):
        nonlocal fallos
        if condicion:
            print(f"[PASA] {ok}")
        else:
            print(f"[FALLA] {malo}")
            fallos += 1

    check(valores.get("DB_PASSWORD") == valores.get("POSTGRES_PASSWORD"),
          "DB_PASSWORD == POSTGRES_PASSWORD",
          "DB_PASSWORD != POSTGRES_PASSWORD")

    con_dollar = [c for c, v in valores.items() if "$" in v]
    check(not con_dollar, "ninguna clave contiene '$'",
          f"claves con '$': {', '.join(con_dollar)}")

    check(valores.get("DEBUG") == "False", "DEBUG=False",
          f"DEBUG={valores.get('DEBUG')} (debe ser False)")

    check(valores.get("SECURE_SSL_REDIRECT") == "True"
          and valores.get("SECURE_PROXY_SSL_HEADER") == "True",
          "SECURE_SSL_REDIRECT y SECURE_PROXY_SSL_HEADER en True",
          f"SSL_REDIRECT={valores.get('SECURE_SSL_REDIRECT')} "
          f"PROXY_SSL={valores.get('SECURE_PROXY_SSL_HEADER')}")

    aws_vacio = (not valores.get("AWS_ACCESS_KEY_ID")
                 and not valores.get("AWS_SECRET_ACCESS_KEY"))
    check(aws_vacio, "AWS_* vacios (Instance Profile / IMDS)",
          "AWS_* con valor: no debe haber credenciales en prod")

    if os.name == "posix":
        modo = oct(ENV.stat().st_mode & 0o777)
        check(modo == "0o600", "permisos 600", f"permisos {modo} (debe ser 600)")

    # AWS_* quedan vacios a proposito: Instance Profile, sin credenciales.
    vacios_admitidos = {"AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"}
    placeholders = [c for c, v in valores.items()
                    if c not in vacios_admitidos and _es_placeholder(v)]
    if placeholders:
        print(f"[ADVERTENCIA] claves aun con placeholder: "
              f"{', '.join(placeholders)}")

    print("\nVEREDICTO: " + ("FALLA" if fallos else "PASA"))
    return 1 if fallos else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cloudfront-url", help="https://dxxxxxxxxxxxx.cloudfront.net")
    ap.add_argument("--ec2-dns", help="ec2-xx-xx-xx-xx.compute-1.amazonaws.com")
    ap.add_argument("--twilio-sid")
    ap.add_argument("--twilio-token")
    ap.add_argument("--twilio-from")
    ap.add_argument("--aplicar", action="store_true",
                    help="Escribe backend/.env (por defecto es dry-run)")
    ap.add_argument("--forzar", action="store_true",
                    help="Sobreescribe un backend/.env existente")
    ap.add_argument("--completar", metavar="FICHERO",
                    help="Rellena SOLO los placeholders (SQS/SNS/Twilio) "
                         "desde FICHERO, sin tocar el resto")
    ap.add_argument("--verificar", action="store_true",
                    help="Solo valida el backend/.env ya escrito")
    args = ap.parse_args()

    if args.verificar:
        return _verificar()

    if args.completar:
        return _completar(args)

    if not args.cloudfront_url:
        ap.error("--cloudfront-url es obligatorio "
                 "(o usa --verificar / --completar)")

    rotador = _importar_rotador()
    valores = _valores_produccion(rotador, args)

    for clave in ("DJANGO_SECRET_KEY", "DB_PASSWORD"):
        if not rotador._sin_dollar(valores[clave]):
            print(f"[FALLA] {clave} generada con '$': Compose la mutilaria")
            return 1
    if valores["DB_PASSWORD"] != valores["POSTGRES_PASSWORD"]:
        print("[FALLA] DB_PASSWORD y POSTGRES_PASSWORD divergentes")
        return 1

    plantilla = _pares(PLANTILLA.read_text(encoding="utf-8"))
    print("Valores de produccion (secretos solo con longitud)")
    for clave in sorted(valores):
        v = valores[clave]
        if clave in SECRETOS:
            print(f"  {clave:26} <len {len(v)}>")
        elif v:
            print(f"  {clave:26} {v}")
        else:
            print(f"  {clave:26} <vacio>")

    pendientes = [c for c, v in plantilla.items()
                  if valores.get(c, v)
                  and _es_placeholder(valores.get(c, v))]
    print("\nSin rellenar (Twilio se puede pasar por argumento):")
    print(f"  {', '.join(pendientes) if pendientes else 'ninguno'}")

    if not args.aplicar:
        print(f"\nDry-run. Repite con --aplicar para escribir {ENV}.")
        return 0

    if ENV.exists() and not args.forzar:
        print(f"[FALLA] {ENV} ya existe; usa --forzar para sobreescribirlo")
        return 1

    n = _escribir(ENV, valores)
    permisos = ", permisos 600" if os.name == "posix" else ""
    print(f"[PASA] {ENV} escrito ({n} lineas{permisos})")
    print("\nVEREDICTO: PASA")
    return 0


if __name__ == "__main__":
    sys.exit(main())
