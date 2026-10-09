"""
00_crear_analista.py
=====================
Crea un usuario Analista con sectores asignados.

Uso (dentro del contenedor web):
    docker compose exec web python /app/scripts/00_crear_analista.py \\
        --username juan --password juan123 --email juan@apuguard.org \\
        --sectores SEC-01 SEC-04

Uso (como management command):
    docker compose exec web python manage.py crear_analista \\
        --username juan --password juan123 --sectores SEC-01 SEC-04
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

from django.contrib.auth.models import User
from core.models import PerfilAnalista, SectorReserva


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Crea un usuario Analista con sectores asignados.")
    parser.add_argument("--username",  required=True, help="Nombre de usuario")
    parser.add_argument("--password",  required=True, help="Contrasena")
    parser.add_argument("--email",     default="",    help="Correo electronico")
    parser.add_argument("--first-name", default="",   help="Nombre")
    parser.add_argument("--last-name",  default="",   help="Apellido")
    parser.add_argument("--sectores",   nargs="*", default=[], help="Codigos de sectores (ej. SEC-01 SEC-02)")
    args = parser.parse_args()

    if User.objects.filter(username=args.username).exists():
        print(f"[AVISO] El usuario '{args.username}' ya existe. No se creo uno nuevo.")
        return 1

    user = User.objects.create_user(
        username   = args.username,
        password   = args.password,
        email      = args.email,
        first_name = args.first_name,
        last_name  = args.last_name,
        is_staff   = False,
        is_superuser = False,
    )

    perfil, _ = PerfilAnalista.objects.get_or_create(user=user)
    if args.sectores:
        sectores = SectorReserva.objects.filter(codigo__in=args.sectores, activo=True)
        perfil.sectores.set(sectores)
        asignados = [s.codigo for s in sectores]
    else:
        asignados = []

    print(f"\n[OK] Usuario Analista creado:")
    print(f"     Username : {user.username}")
    print(f"     Email    : {user.email or '(sin email)'}")
    print(f"     Rol JWT  : Analista (is_staff=False)")
    print(f"     Sectores : {', '.join(asignados) if asignados else '(sin asignar)'}")
    print(f"\nYa puede iniciar sesion en http://localhost:4200/login")
    return 0


if __name__ == "__main__":
    sys.exit(main())
