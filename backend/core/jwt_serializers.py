"""
jwt_serializers.py — Serializers custom de SimpleJWT para APU GUARD.

Añade al payload del token:
  * username : nombre de usuario
  * rol      : "Administrador" (is_staff=True) | "Analista"

y registra el inicio de sesión en la tabla de auditoría
(POST /api/auth/token/ → fila "Inició sesión").
"""

from django.contrib.admin.models import ADDITION
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from core.audit import registrar_actividad


class ApuGuardTokenSerializer(TokenObtainPairSerializer):

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)

        # Campos extra en el payload JWT
        token["username"] = user.username
        token["rol"] = "Administrador" if user.is_staff else "Analista"
        token["email"] = user.email

        return token

    def validate(self, attrs):
        data = super().validate(attrs)

        # super().validate() autentica y deja el usuario en self.user;
        # si el login falla ya lanzó excepción antes de llegar aquí.
        usuario = getattr(self, "user", None)
        if usuario is not None:
            registrar_actividad(usuario, "Inició sesión", usuario, ADDITION)
        return data
