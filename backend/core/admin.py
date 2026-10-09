from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from django.contrib.gis import admin as gis_admin

from .models import (
    ConfiguracionGlobal, SectorReserva, TecnicoCampo, PerfilAnalista,
    CapturaSatelital, ParcheProcesamiento, CasoAuditoria, RegistroSMS,
)


# ── PerfilAnalista inline dentro del usuario ───────────────────────────────
class PerfilAnalistaInline(admin.StackedInline):
    model  = PerfilAnalista
    filter_horizontal = ('sectores',)
    verbose_name = "Perfil Analista (sectores asignados)"
    can_delete = False
    extra = 1


class UsuarioAdmin(BaseUserAdmin):
    """
    Extiende el admin de User para mostrar:
    - Columna 'Rol' (Administrador / Analista)
    - Inline de PerfilAnalista con selector de sectores
    """
    list_display  = ('username', 'email', 'first_name', 'last_name', 'get_rol', 'is_active')
    list_filter   = ('is_staff', 'is_active')
    inlines       = [PerfilAnalistaInline]

    @admin.display(description='Rol', boolean=False)
    def get_rol(self, obj):
        return 'Administrador' if obj.is_staff else 'Analista'


# Re-registrar User con el admin extendido
admin.site.unregister(User)
admin.site.register(User, UsuarioAdmin)


# ── Resto de modelos ───────────────────────────────────────────────────────
admin.site.register(ConfiguracionGlobal)
admin.site.register(SectorReserva,       gis_admin.GISModelAdmin)
admin.site.register(TecnicoCampo)
admin.site.register(PerfilAnalista)
admin.site.register(CapturaSatelital)
admin.site.register(ParcheProcesamiento, gis_admin.GISModelAdmin)
admin.site.register(CasoAuditoria,       gis_admin.GISModelAdmin)
admin.site.register(RegistroSMS)
