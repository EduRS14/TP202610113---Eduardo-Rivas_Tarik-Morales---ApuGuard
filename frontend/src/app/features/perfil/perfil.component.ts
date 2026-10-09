import { Component, OnInit, signal } from '@angular/core';
import { CommonModule }              from '@angular/common';
import { FormsModule }               from '@angular/forms';
import { ApiService }                from '../../core/services/api.service';
import { AuthService }               from '../../core/services/auth.service';
import { Usuario }                   from '../../core/models/user.model';

@Component({
  selector: 'app-perfil',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <div class="max-w-2xl mx-auto px-6 py-6">

      <h1 class="text-xl font-bold text-gray-800 flex items-center gap-2 mb-1">
        <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
            d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"/>
        </svg>
        Mi Perfil
      </h1>
      <p class="text-sm text-gray-500 mb-6">Gestiona tu información personal y preferencias.</p>

      <!-- Card header -->
      <div class="rounded-xl bg-primary text-white p-6 flex items-center gap-4 mb-6">
        <div class="w-16 h-16 bg-white/20 rounded-full flex items-center justify-center text-2xl font-bold">
          {{ iniciales() }}
        </div>
        <div>
          <p class="font-bold text-lg">{{ perfil()?.first_name }} {{ perfil()?.last_name }}</p>
          <p class="text-green-200 text-sm">{{ perfil()?.rol }}</p>
        </div>
      </div>

      <!-- Formulario -->
      <div class="card mb-6">
        <p class="font-semibold text-gray-800 mb-4">Información Personal</p>
        <div class="grid grid-cols-2 gap-4">
          <div>
            <label class="block text-xs text-gray-500 mb-1 uppercase">Nombre Completo</label>
            <div class="input-field bg-gray-50 flex items-center gap-2 text-gray-700">
              <svg class="w-4 h-4 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                  d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"/>
              </svg>
              <input type="text" [(ngModel)]="form.nombre" class="bg-transparent outline-none flex-1 text-sm"
                     [placeholder]="(perfil()?.first_name || '') + ' ' + (perfil()?.last_name || '')">
            </div>
          </div>
          <div>
            <label class="block text-xs text-gray-500 mb-1 uppercase">Correo Institucional</label>
            <div class="input-field bg-gray-50 flex items-center gap-2 text-gray-500">
              <svg class="w-4 h-4 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                  d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"/>
              </svg>
              <span class="text-sm">{{ perfil()?.email }}</span>
            </div>
          </div>
          <div>
            <label class="block text-xs text-gray-500 mb-1 uppercase">Teléfono</label>
            <input type="text" [(ngModel)]="form.telefono" class="input-field text-sm"
                   [placeholder]="perfil()?.telefono || '+51 ...'">
          </div>
          <div>
            <label class="block text-xs text-gray-500 mb-1 uppercase">Rol</label>
            <div class="input-field bg-gray-50 text-gray-500 text-sm">
              {{ perfil()?.rol }}
              <p class="text-xs text-gray-400 mt-0.5">Consulta al administrador para cambio de rol.</p>
            </div>
          </div>
        </div>
        <div class="flex gap-2 mt-4">
          <button (click)="guardar()" [disabled]="guardando()" class="btn-primary text-sm flex items-center gap-2">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/>
            </svg>
            {{ guardando() ? 'Guardando...' : 'Guardar Cambios' }}
          </button>
          <button (click)="resetForm()" class="btn-outline text-sm">Cancelar</button>
        </div>
      </div>

      <!-- Actividad reciente -->
      <div class="card">
        <div class="flex items-center gap-2 mb-4">
          <svg class="w-5 h-5 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
              d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/>
          </svg>
          <p class="font-semibold text-gray-800">Actividad Reciente</p>
        </div>
        <div class="space-y-3">
          <div>
            <p class="text-xs text-gray-500">Último acceso</p>
            <p class="text-sm text-primary font-medium">{{ perfil()?.fecha_ultimo_acceso ?? '—' }}</p>
          </div>
          <div>
            <p class="text-xs text-gray-500">Miembro desde</p>
            <p class="text-sm text-primary font-medium">{{ perfil()?.fecha_registro ?? '—' }}</p>
          </div>
        </div>
      </div>
    </div>
  `
})
export class PerfilComponent implements OnInit {
  private _perfil   = signal<Usuario | null>(null);
  private _guardando = signal(false);

  perfil    = this._perfil.asReadonly();
  guardando = this._guardando.asReadonly();

  form = { nombre: '', telefono: '' };

  iniciales = () => {
    const p = this._perfil();
    if (!p) return '?';
    return `${p.first_name?.[0] ?? ''}${p.last_name?.[0] ?? ''}`.toUpperCase();
  };

  constructor(private api: ApiService, private auth: AuthService) {}

  ngOnInit(): void {
    this.api.getMiPerfil().subscribe({
      next: (u) => { this._perfil.set(u); this.resetForm(); },
      error: () => {
        const jwt = this.auth.usuario();
        if (jwt) {
          const mock: Usuario = {
            id: jwt.user_id, username: jwt.username, email: `${jwt.username}@institucion.gob.pe`,
            first_name: jwt.username, last_name: '', rol: jwt.rol, estado: 'Activo',
            telefono: '', fecha_ultimo_acceso: new Date().toLocaleString('es-PE'),
            fecha_registro: 'Enero 2026'
          };
          this._perfil.set(mock);
          this.resetForm();
        }
      }
    });
  }

  resetForm(): void {
    const p = this._perfil();
    this.form.nombre   = p ? `${p.first_name} ${p.last_name}`.trim() : '';
    this.form.telefono = p?.telefono ?? '';
  }

  guardar(): void {
    this._guardando.set(true);
    const [first_name, ...rest] = this.form.nombre.split(' ');
    this.api.updateMiPerfil({ first_name, last_name: rest.join(' '), telefono: this.form.telefono }).subscribe({
      next: (u) => { this._perfil.set(u); this._guardando.set(false); },
      error: () => this._guardando.set(false)
    });
  }
}
