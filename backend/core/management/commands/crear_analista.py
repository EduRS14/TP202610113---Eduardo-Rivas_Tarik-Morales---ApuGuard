"""
Comando: python manage.py crear_analista

Crea un usuario Analista (is_staff=False) con un PerfilAnalista
y asignacion opcional de sectores por codigo.

Uso:
    python manage.py crear_analista --username juan --password juan123 \\
        --email juan@apuguard.org --sectores SEC-01 SEC-04
"""

from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth.models import User

from core.models import PerfilAnalista, SectorReserva


class Command(BaseCommand):
    help = "Crea un usuario Analista con sectores asignados"

    def add_arguments(self, parser):
        parser.add_argument("--username",  required=True, help="Nombre de usuario")
        parser.add_argument("--password",  required=True, help="Contrasena del usuario")
        parser.add_argument("--email",     default="",    help="Correo electronico")
        parser.add_argument("--first-name", default="",   help="Nombre")
        parser.add_argument("--last-name",  default="",   help="Apellido")
        parser.add_argument(
            "--sectores", nargs="*", default=[],
            help="Codigos de sectores a asignar (ej. SEC-01 SEC-02)"
        )

    def handle(self, *args, **options):
        username = options["username"]
        password = options["password"]
        email    = options["email"]

        if User.objects.filter(username=username).exists():
            raise CommandError(f"El usuario '{username}' ya existe.")

        user = User.objects.create_user(
            username    = username,
            password    = password,
            email       = email,
            first_name  = options["first_name"],
            last_name   = options["last_name"],
            is_staff    = False,
            is_superuser = False,
        )

        perfil, _ = PerfilAnalista.objects.get_or_create(user=user)
        asignados = []
        if options["sectores"]:
            sectores = SectorReserva.objects.filter(
                codigo__in=options["sectores"], activo=True
            )
            if not sectores.exists():
                self.stdout.write(self.style.WARNING(
                    "Ninguno de los sectores indicados existe o esta activo."
                ))
            else:
                perfil.sectores.set(sectores)
                asignados = [s.codigo for s in sectores]

        self.stdout.write(self.style.SUCCESS(
            f"\n[OK] Usuario Analista creado:"
            f"\n     Username : {user.username}"
            f"\n     Email    : {email or '(sin email)'}"
            f"\n     Rol JWT  : Analista (is_staff=False)"
            f"\n     Sectores : {', '.join(asignados) if asignados else '(sin asignar)'}"
            f"\n\nYa puede iniciar sesion en http://localhost:4200/login"
        ))
