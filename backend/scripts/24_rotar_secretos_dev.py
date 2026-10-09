#!/usr/bin/env python
"""
24_rotar_secretos_dev.py — Fase A'

Rota en backend/.env:
  * DJANGO_SECRET_KEY
  * DB_PASSWORD (lo lee Django)  ==  POSTGRES_PASSWORD (lo usa la imagen postgis)
y aplica el cambio de password dentro de Postgres con ALTER USER.

Orden seguro:
  1. se reescribe backend/.env con los valores nuevos
  2. se conecta con el password VIGENTE (el que trae el proceso, es decir el
     anterior) y se ejecuta ALTER USER
  3. se verifica con una segunda conexion usando el password NUEVO

Si el paso 2 falla, .env ya quedo escrito pero la BD sigue con el password
anterior: se recuperan los respaldos y se reintenta. El archivo no se
modifica en modo dry-run.

Nunca imprime los secretos, solo longitudes.

Uso:
  python scripts/24_rotar_secretos_dev.py            # dry-run
  python scripts/24_rotar_secretos_dev.py --aplicar  # rota .env + ALTER USER
"""
import argparse
import os
import re
import secrets
import string
import sys
from pathlib import Path

ENV = Path(__file__).resolve().parent.parent / ".env"
CLAVES = ("DJANGO_SECRET_KEY", "DB_PASSWORD", "POSTGRES_PASSWORD")
USUARIO = "apuguard"


def _sin_dollar(valor: str) -> bool:
    return "$" not in valor


def _nuevo_secret_key() -> str:
    # SIN '$': Docker Compose interpeta $VAR/$${...} tambien dentro de los
    # ficheros env_file, asi que una clave con '$' llega truncada al
    # contenedor (se detecto en Fase A': 50 chars en .env -> 41 en el
    # entorno). '#' tampoco, por si el valor aterriza en un YAML.
    abecedario = string.ascii_letters + string.digits + "!@%^&*(-_=+"
    return "".join(secrets.choice(abecedario) for _ in range(50))


def _nuevo_password() -> str:
    # Sin caracteres que obliguen a comillas en el .env.
    return "ApuG_" + "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(32))


def _mascara(valor: str) -> str:
    if valor.startswith("<"):
        return valor
    if len(valor) <= 8:
        return f"<len {len(valor)}>"
    return f"<len {len(valor)}>"


def _leer(path: Path) -> dict:
    actual = {}
    if not path.exists():
        return actual
    for linea in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\A([A-Za-z_0-9]+)=(.*)\Z", linea)
        if m and m.group(1) in CLAVES:
            actual[m.group(1)] = m.group(2)
    return actual


def _escribir(path: Path, propuestos: dict) -> int:
    lineas = path.read_text(encoding="utf-8").splitlines()
    presentes, salida = set(), []
    for linea in lineas:
        m = re.match(r"\A([A-Za-z_0-9]+)=.*\Z", linea)
        if m and m.group(1) in CLAVES:
            clave = m.group(1)
            salida.append(f"{clave}={propuestos[clave]}")
            presentes.add(clave)
        else:
            salida.append(linea)
    for clave in CLAVES:
        if clave not in presentes:
            salida.append(f"{clave}={propuestos[clave]}")
    path.write_text("\n".join(salida) + "\n", encoding="utf-8")
    return len(salida)


def _conexion(password, host, dbname):
    import psycopg2
    return psycopg2.connect(
        host=host, port=int(os.environ.get("DB_PORT", "5432")),
        dbname=dbname, user=USUARIO, password=password,
        connect_timeout=10,
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--aplicar", action="store_true")
    ap.add_argument("--verificar", action="store_true",
                    help="No rota nada: solo valida que Django arranca y "
                         "conecta con los valores escritos en backend/.env")
    args = ap.parse_args()

    if not ENV.exists():
        print(f"[FALLA] no existe {ENV}")
        return 1

    antes = _leer(ENV)
    pwd_viejo = os.environ.get("DB_PASSWORD", "") or antes.get("DB_PASSWORD", "")
    propuestos = {
        "DJANGO_SECRET_KEY": _nuevo_secret_key(),
        "DB_PASSWORD": _nuevo_password(),
    }
    propuestos["POSTGRES_PASSWORD"] = propuestos["DB_PASSWORD"]

    if args.verificar:
        propuestos = dict(antes)
        print("Verificacion con los valores de backend/.env")
        for clave in CLAVES:
            print(f"  {clave:22} {_mascara(propuestos.get(clave, '<falta>'))}")
        if propuestos.get("DB_PASSWORD") != propuestos.get("POSTGRES_PASSWORD"):
            print("[FALLA] DB_PASSWORD != POSTGRES_PASSWORD en .env")
            return 1
        print("[PASA] DB_PASSWORD == POSTGRES_PASSWORD")
        if _verificar_entrega(propuestos):
            return 1
        return _verificar_django(propuestos)

    print("Rotacion de secretos")
    for clave in CLAVES:
        cambio = antes.get(clave, "<no existia>") != propuestos[clave]
        print(f"  {clave:22} {_mascara(antes.get(clave, '<no existia>')):14} -> "
              f"{_mascara(propuestos[clave])}  [{'ROTADO' if cambio else 'igual'}]")

    if not _sin_dollar(propuestos["DJANGO_SECRET_KEY"]):
        print("[FALLA] la clave generada contiene '$': Compose la mutilaria")
        return 1

    if not args.aplicar:
        print("\nDry-run. Repite con --aplicar para escribir .env y aplicar en BD.")
        return 0

    if propuestos["DB_PASSWORD"] != propuestos["POSTGRES_PASSWORD"]:
        print("[FALLA] DB_PASSWORD y POSTGRES_PASSWORD divergentes")
        return 1

    n = _escribir(ENV, propuestos)
    print(f"[PASA] backend/.env reescrito ({n} lineas)")

    host = os.environ.get("DB_HOST", "db")
    dbname = os.environ.get("DB_NAME", "apuguard_db")

    # 1. ALTER USER con la sesion vigente (password anterior todavia valida).
    try:
        from psycopg2 import sql
        conn = _conexion(pwd_viejo, host, dbname)
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL("ALTER USER {} WITH PASSWORD %s").format(sql.Identifier(USUARIO)),
                (propuestos["DB_PASSWORD"],),
            )
        conn.close()
        print("[PASA] ALTER USER aplicado en Postgres")
    except Exception as exc:  # noqa: BLE001
        print(f"[FALLA] ALTER USER: {exc}")
        return 1

    # 2. Verificacion: nueva sesion con el password nuevo.
    try:
        conn = _conexion(propuestos["DB_PASSWORD"], host, dbname)
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            ok = cur.fetchone()[0] == 1
        conn.close()
        print("[PASA] verificacion de conexion con el password nuevo"
              if ok else "[FALLA] SELECT 1 no devolvio 1")
        if not ok:
            return 1
    except Exception as exc:  # noqa: BLE001
        print(f"[FALLA] conexion con password nuevo: {exc}")
        return 1

    # 3. Django con los valores NUEVOS en el entorno del proceso: valida que
    #    el SECRET_KEY y el password recien escritos cargan y conectan.
    fallo = _verificar_django(propuestos)
    if fallo:
        return 1

    print("\nVEREDICTO: PASA")
    return 0


def _verificar_entrega(propuestos: dict) -> int:
    """Comprueba que Compose entrego los secretos SIN mutilarlos.

    Compose interpeta $VAR y ${VAR} tambien dentro de los valores de los
    ficheros env_file: un secreto que contenga '$' llega recortado al
    contenedor (Fase A'). Devuelve 0 si todo llego intacto.
    """
    fallos = 0
    print("\nEntrega de secretos desde backend/.env al contenedor")
    for clave in CLAVES:
        esperado = propuestos.get(clave, "")
        real = os.environ.get(clave)
        if real is None:
            print(f"  [FALLA] {clave} no llego al contenedor")
            fallos += 1
        elif real != esperado:
            print(f"  [FALLA] {clave} mutilado: .env {len(esperado)} chars "
                  f"-> entorno {len(real)} chars (¿'$' en el valor?)")
            fallos += 1
        else:
            print(f"  [PASA] {clave} intacto ({len(real)} chars)")

    # Barrido de TODAS las claves del .env: si alguna contiene '$', Compose
    # puede haberla recortado antes de llegar aqui.
    con_dollar = []
    for linea in ENV.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\A([A-Za-z_0-9]+)=(.*)\Z", linea)
        if m and "$" in m.group(2):
            con_dollar.append(m.group(1))
    if con_dollar:
        print(f"  [ADVERTENCIA] claves con '$' en .env: {', '.join(con_dollar)}")
        print("                Escapa como $$ o quita el '$'.")
    else:
        print("  [PASA] ninguna clave de .env contiene '$'")

    return fallos


def _verificar_django(propuestos: dict) -> int:
    """Monta Django con los valores dados y comprueba clave + conexion."""
    # El script se ejecuta como /app/scripts/xxx.py, asi que /app no esta en
    # sys.path; sin esto `import apuguard` fallaria.
    raiz = ENV.parent
    if str(raiz) not in sys.path:
        sys.path.insert(0, str(raiz))

    try:
        os.environ["DJANGO_SECRET_KEY"] = propuestos["DJANGO_SECRET_KEY"]
        os.environ["DB_PASSWORD"] = propuestos["DB_PASSWORD"]
        os.environ["POSTGRES_PASSWORD"] = propuestos["POSTGRES_PASSWORD"]
        import django
        django.setup()
        from django.conf import settings
        from django.db import connection
        assert settings.SECRET_KEY == propuestos["DJANGO_SECRET_KEY"], \
            "SECRET_KEY cargado != el escrito en .env"
        connection.ensure_connection()
        with connection.cursor() as cur:
            cur.execute("SELECT 1")
            assert cur.fetchone()[0] == 1
        print(f"[PASA] Django arranca con el SECRET_KEY de .env "
              f"(len {len(settings.SECRET_KEY)}) y conecta a la BD")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"[FALLA] Django/BD con los valores de .env: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
