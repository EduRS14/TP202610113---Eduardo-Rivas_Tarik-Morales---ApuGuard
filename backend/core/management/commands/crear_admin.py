"""
Comando: python manage.py crear_admin

Crea el primer usuario Administrador de APU GUARD.
Usa is_staff=True para que el JWT lo reconozca como "Administrador".
"""

from django.core.management.base import BaseCommand
from django.contrib.auth.models import User


class Command(BaseCommand):
    help = "Crea el usuario administrador inicial de APU GUARD"

    def add_arguments(self, parser):
        parser.add_argument("--username", default="admin",      help="Nombre de usuario")
        parser.add_argument("--email",    default="",           help="Correo electronico")
        parser.add_argument("--password", default="apuguard123", help="Contrasena")

    def handle(self, *args, **options):
        username = options["username"]
        email    = options["email"]
        password = options["password"]

        if User.objects.filter(username=username).exists():
            self.stdout.write(self.style.WARNING(
                f"El usuario '{username}' ya existe. No se creo uno nuevo."
            ))
            return

        User.objects.create_superuser(
            username=username,
            email=email,
            password=password,
        )

        self.stdout.write(self.style.SUCCESS(
            f"\n[OK] Usuario administrador creado:"
            f"\n     Usuario  : {username}"
            f"\n     Password : {password}"
            f"\n     Rol JWT  : Administrador (is_staff=True)"
            f"\n\nYa puedes hacer login en http://localhost:4200/login\n"
        ))
