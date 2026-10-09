import { Component, OnInit, signal, computed } from '@angular/core';
import { CommonModule }   from '@angular/common';
import { FormsModule }    from '@angular/forms';
import { ApiService }     from '../../core/services/api.service';
import { Usuario, Rol, EstadoUsuario } from '../../core/models/user.model';
import { Sector }         from '../../core/models/alerta.model';

@Component({
  selector: 'app-usuarios',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <div class="max-w-screen-xl mx-auto px-6 py-6">

      <div class="flex items-center justify-between mb-6">
        <div>
          <h1 class="text-xl font-bold text-gray-800 flex items-center gap-2">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z"/>
            </svg>
            Gestión de Usuarios
          </h1>
          <p class="text-sm text-gray-500">Administración de acceso y roles del sistema.</p>
        </div>
        <button (click)="abrirCrear()" class="btn-primary text-sm flex items-center gap-2">
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/>
          </svg>
          Agregar Usuario
        </button>
      </div>

      <!-- Filtros -->
      <div class="flex flex-wrap gap-3 mb-4">
        <input type="text" [(ngModel)]="busqueda" placeholder="Buscar por nombre o correo..."
               class="input-field flex-1 min-w-48 text-sm">
        <select [(ngModel)]="filtroRol" class="select-field w-40 text-sm">
          <option value="">Todos los roles</option>
          <option value="Administrador">Administrador</option>
          <option value="Analista">Analista</option>
        </select>
        <select [(ngModel)]="filtroEstado" class="select-field w-40 text-sm">
          <option value="">Todos los estados</option>
          <option value="Activo">Activo</option>
          <option value="Inactivo">Inactivo</option>
        </select>
      </div>

      <!-- Lista -->
      <div class="card">
        <p class="text-sm text-gray-500 mb-4">Lista de Usuarios ({{ usuariosFiltrados().length }})</p>
        <table class="w-full text-sm">
          <thead>
            <tr class="border-b border-gray-100">
              <th class="text-left py-2 px-2 text-xs font-semibold text-gray-500 uppercase">Nombre</th>
              <th class="text-left py-2 px-2 text-xs font-semibold text-gray-500 uppercase">Correo</th>
              <th class="text-left py-2 px-2 text-xs font-semibold text-gray-500 uppercase">Rol</th>
              <th class="text-left py-2 px-2 text-xs font-semibold text-gray-500 uppercase">Sectores</th>
              <th class="text-left py-2 px-2 text-xs font-semibold text-gray-500 uppercase">Estado</th>
              <th class="text-left py-2 px-2 text-xs font-semibold text-gray-500 uppercase">Último Acceso</th>
              <th class="text-left py-2 px-2 text-xs font-semibold text-gray-500 uppercase">Acciones</th>
            </tr>
          </thead>
          <tbody>
            @for (u of usuariosFiltrados(); track u.id) {
              <tr class="border-b border-gray-50 hover:bg-gray-50">
                <td class="py-3 px-2 font-semibold text-gray-800">{{ u.first_name }} {{ u.last_name }}</td>
                <td class="py-3 px-2 text-gray-600">{{ u.email }}</td>
                <td class="py-3 px-2">
                  <span class="text-xs font-semibold px-2 py-0.5 rounded-full"
                        [class]="u.rol === 'Administrador' ? 'bg-purple-100 text-purple-700' : 'bg-blue-100 text-blue-700'">
                    {{ u.rol }}
                  </span>
                </td>
                <td class="py-3 px-2 text-gray-500 text-xs">
                  @if (u.rol === 'Analista') {
                    @if (u.sectores_ids?.length) {
                      {{ nombresSectores(u.sectores_ids!) }}
                    } @else {
                      <span class="text-amber-500">Sin sectores</span>
                    }
                  } @else {
                    <span class="text-gray-400">Todos</span>
                  }
                </td>
                <td class="py-3 px-2">
                  <span class="text-xs font-semibold px-2 py-0.5 rounded-full"
                        [class]="u.estado === 'Activo' ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'">
                    {{ u.estado }}
                  </span>
                </td>
                <td class="py-3 px-2 text-gray-500 text-xs">{{ u.fecha_ultimo_acceso ? (u.fecha_ultimo_acceso | date:'dd/MM/yyyy HH:mm') : '—' }}</td>
                <td class="py-3 px-2">
                  <div class="flex gap-3">
                    <button (click)="abrirEditar(u)" class="text-xs text-primary hover:underline font-medium">Editar</button>
                    <button (click)="confirmarEliminar(u)" class="text-xs text-red-500 hover:underline">Eliminar</button>
                  </div>
                </td>
              </tr>
            } @empty {
              <tr><td colspan="7" class="py-8 text-center text-gray-400">Sin usuarios.</td></tr>
            }
          </tbody>
        </table>
      </div>

      <!-- Modal Crear / Editar -->
      @if (modalAbierto()) {
        <div class="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4">
          <div class="bg-white rounded-2xl shadow-2xl w-full max-w-md">
            <div class="p-5 border-b border-gray-100">
              <h3 class="font-bold text-gray-800">{{ editandoId() ? 'Editar Usuario' : 'Crear Nuevo Usuario' }}</h3>
              <p class="text-xs text-gray-500">Completa la información para {{ editandoId() ? 'actualizar' : 'agregar un nuevo usuario al' }} sistema.</p>
            </div>
            <div class="p-5 space-y-4">

              <div>
                <label class="block text-xs font-semibold text-gray-600 mb-1 uppercase">Nombre Completo *</label>
                <input type="text" [(ngModel)]="form.nombre" class="input-field" placeholder="Ej: Juan Perez">
              </div>

              <div>
                <label class="block text-xs font-semibold text-gray-600 mb-1 uppercase">Correo Institucional *</label>
                <input type="email" [(ngModel)]="form.email" class="input-field" placeholder="ejemplo@institucion.gob.pe">
              </div>

              <div class="grid grid-cols-2 gap-3">
                <div>
                  <label class="block text-xs font-semibold text-gray-600 mb-1 uppercase">Rol</label>
                  <select [(ngModel)]="form.rol" class="select-field">
                    <option value="Analista">Analista</option>
                    <option value="Administrador">Administrador</option>
                  </select>
                </div>
                <div>
                  <label class="block text-xs font-semibold text-gray-600 mb-1 uppercase">Estado</label>
                  <select [(ngModel)]="form.estado" class="select-field">
                    <option value="Activo">Activo</option>
                    <option value="Inactivo">Inactivo</option>
                  </select>
                </div>
              </div>

              <!-- Sectores — solo visible para Analistas -->
              @if (form.rol === 'Analista') {
                <div>
                  <label class="block text-xs font-semibold text-gray-600 mb-1 uppercase">
                    Sectores asignados
                    <span class="text-gray-400 font-normal normal-case ml-1">(el analista solo verá alertas de estos sectores)</span>
                  </label>
                  @if (sectores().length === 0) {
                    <p class="text-xs text-amber-500">Cargando sectores...</p>
                  } @else {
                    <div class="border border-gray-200 rounded-lg divide-y divide-gray-100 max-h-40 overflow-y-auto">
                      @for (s of sectores(); track s.id) {
                        <label class="flex items-center gap-3 px-3 py-2 hover:bg-gray-50 cursor-pointer">
                          <input type="checkbox"
                                 [checked]="form.sectoresIds.includes(s.id)"
                                 (change)="toggleSector(s.id)"
                                 class="w-4 h-4 accent-primary">
                          <span class="text-sm text-gray-700">{{ s.nombre }}</span>
                        </label>
                      }
                    </div>
                    @if (form.sectoresIds.length === 0) {
                      <p class="text-xs text-amber-500 mt-1">Sin sectores asignados — el analista no verá ninguna alerta.</p>
                    }
                  }
                </div>
              }

              @if (!editandoId()) {
                <div>
                  <label class="block text-xs font-semibold text-gray-600 mb-1 uppercase">Contraseña *</label>
                  <input type="password" [(ngModel)]="form.password" class="input-field" placeholder="Mínimo 8 caracteres">
                </div>
              }
            </div>
            <div class="p-5 border-t border-gray-100 flex justify-end gap-2">
              <button (click)="cerrarModal()" class="btn-outline text-sm">Cancelar</button>
              <button (click)="guardar()" class="btn-primary text-sm">
                {{ editandoId() ? 'Guardar Cambios' : 'Crear Usuario' }}
              </button>
            </div>
          </div>
        </div>
      }
    </div>
  `
})
export class UsuariosComponent implements OnInit {
  private _usuarios   = signal<Usuario[]>([]);
  private _sectores   = signal<Sector[]>([]);
  private _modalAbierto = signal(false);
  private _editandoId   = signal<number | null>(null);

  usuarios     = this._usuarios.asReadonly();
  sectores     = this._sectores.asReadonly();
  modalAbierto = this._modalAbierto.asReadonly();
  editandoId   = this._editandoId.asReadonly();

  busqueda     = '';
  filtroRol    = '';
  filtroEstado = '';

  form: {
    nombre: string;
    email: string;
    rol: Rol;
    estado: EstadoUsuario;
    password: string;
    sectoresIds: number[];
  } = { nombre: '', email: '', rol: 'Analista', estado: 'Activo', password: '', sectoresIds: [] };

  usuariosFiltrados = () => this._usuarios().filter(u => {
    const texto = `${u.first_name} ${u.last_name} ${u.email}`.toLowerCase();
    return (
      (!this.busqueda    || texto.includes(this.busqueda.toLowerCase())) &&
      (!this.filtroRol   || u.rol    === this.filtroRol) &&
      (!this.filtroEstado || u.estado === this.filtroEstado)
    );
  });

  nombresSectores(ids: number[]): string {
    return ids
      .map(id => this._sectores().find(s => s.id === id)?.nombre ?? `S${id}`)
      .join(', ');
  }

  constructor(private api: ApiService) {}

  ngOnInit(): void {
    this.cargar();
    this.api.getSectoresSimple().subscribe({
      next: (s) => this._sectores.set(s),
      error: () => {}
    });
  }

  cargar(): void {
    this.api.getUsuarios().subscribe({
      next: (r) => this._usuarios.set(r.results),
      error: () => this._usuarios.set([])
    });
  }

  abrirCrear(): void {
    this.form = { nombre: '', email: '', rol: 'Analista', estado: 'Activo', password: '', sectoresIds: [] };
    this._editandoId.set(null);
    this._modalAbierto.set(true);
  }

  abrirEditar(u: Usuario): void {
    this.form = {
      nombre:      `${u.first_name} ${u.last_name}`.trim(),
      email:       u.email,
      rol:         u.rol,
      estado:      u.estado,
      password:    '',
      sectoresIds: u.sectores_ids ? [...u.sectores_ids] : [],
    };
    this._editandoId.set(u.id);
    this._modalAbierto.set(true);
  }

  toggleSector(id: number): void {
    const idx = this.form.sectoresIds.indexOf(id);
    if (idx >= 0) {
      this.form.sectoresIds.splice(idx, 1);
    } else {
      this.form.sectoresIds.push(id);
    }
  }

  cerrarModal(): void { this._modalAbierto.set(false); }

  guardar(): void {
    const [first_name, ...rest] = this.form.nombre.trim().split(' ');
    const last_name = rest.join(' ');

    const payload: any = {
      first_name,
      last_name,
      email:  this.form.email,
      rol:    this.form.rol,
      estado: this.form.estado,
    };

    // Sectores solo se envían para Analistas
    if (this.form.rol === 'Analista') {
      payload['sectores_ids'] = this.form.sectoresIds;
    }

    const id  = this._editandoId();
    const obs = id
      ? this.api.updateUsuario(id, payload)
      : this.api.createUsuario({
          ...payload,
          password: this.form.password,
          username: this.form.email.split('@')[0],
        });

    obs.subscribe({ next: () => { this.cerrarModal(); this.cargar(); } });
  }

  confirmarEliminar(u: Usuario): void {
    if (!confirm(`¿Eliminar a ${u.first_name} ${u.last_name}?`)) return;
    this.api.deleteUsuario(u.id).subscribe({ next: () => this.cargar() });
  }
}
