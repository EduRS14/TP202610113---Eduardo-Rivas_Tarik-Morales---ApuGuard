"""
permissions.py - APU GUARD
===========================
Roles de usuario:

  Administrador (is_staff=True)  : acceso total, lectura y escritura
  Analista      (is_staff=False, analista_perfil)  : solo lectura, solo sus sectores
  TecnicoCampo  : entidad de contacto SMS, NO inicia sesión en la app
"""

from rest_framework.permissions import BasePermission, SAFE_METHODS


class IsAdministrador(BasePermission):
    """Acceso total para usuarios staff/superuser."""
    message = "Se requiere perfil de Administrador."

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return request.user.is_staff or request.user.is_superuser


class IsAnalista(BasePermission):
    """Solo lectura para usuarios con PerfilAnalista."""
    message = "Se requiere perfil de Analista."

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.method not in SAFE_METHODS:
            return False
        return hasattr(request.user, "analista_perfil")


class IsTecnicoOAdministrador(BasePermission):
    """
    Permite acceso a Administradores (lectura+escritura)
    y Analistas (solo lectura).
    Usado en todos los endpoints que ambos roles deben ver.
    """
    message = "Se requiere perfil de Analista o Administrador."

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        es_admin   = request.user.is_staff or request.user.is_superuser
        es_analista = hasattr(request.user, "analista_perfil")

        if request.method in SAFE_METHODS:
            return es_admin or es_analista
        return es_admin   # escritura solo para admin


# Alias mantenido por compatibilidad (por si queda alguna referencia)
IsTecnicoCampo = IsAnalista
