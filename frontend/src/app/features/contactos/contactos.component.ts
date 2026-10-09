import { Component, OnInit, computed, signal } from '@angular/core';
import { CommonModule }                        from '@angular/common';
import { FormsModule }                         from '@angular/forms';
import { ApiService }                          from '../../core/services/api.service';
import { TecnicoCampo, Sector }               from '../../core/models/alerta.model';

@Component({
  selector: 'app-contactos',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <div class="max-w-screen-xl mx-auto px-6 py-6">

      <div class="flex items-center justify-between mb-6">
        <div>
          <h1 class="text-xl font-bold text-gray-800 flex items-center gap-2">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                d="M3 5a2 2 0 012-2h3.28a1 1 0 01.948.684l1.498 4.493a1 1 0 01-.502 1.21l-2.257 1.13a11.042 11.042 0 005.516 5.516l1.13-2.257a1 1 0 011.21-.502l4.493 1.498a1 1 0 01.684.949V19a2 2 0 01-2 2h-1C9.716 21 3 14.284 3 6V5z"/>
            </svg>
            Configuración de Contactos
          </h1>
          <p class="text-sm text-gray-500">Gestión de técnicos de campo por sector.</p>
        </div>
        <button (click)="abrirFormulario()" class="btn-primary text-sm flex items-center gap-2">
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/>
          </svg>
          Agregar Contacto
        </button>
      </div>

      <!-- Formulario inline crear/editar -->
      @if (formularioAbierto()) {
        <div class="card mb-6 border-l-4 border-primary">
          <p class="text-sm font-semibold text-gray-700 mb-4">
            {{ editandoId() ? 'Editar Contacto' : 'Nuevo Contacto' }}
          </p>
          <div class="grid grid-cols-2 gap-4">

            <div>
              <label class="block text-xs text-gray-500 mb-1">Responsable *</label>
              <input type="text" [ngModel]="formNombre()" (ngModelChange)="formNombre.set($event)"
                     class="input-field text-sm" placeholder="Nombre del técnico">
            </div>

            <div>
              <label class="block text-xs text-gray-500 mb-1">Teléfono *</label>
              <input type="text" [ngModel]="formTelefono()" (ngModelChange)="formTelefono.set($event)"
                     class="input-field text-sm" placeholder="+51 982 456 789">
            </div>

            <div class="col-span-2">
              <label class="block text-xs text-gray-500 mb-1">Sector / Área *</label>
              <select [ngModel]="formSectorId()" (ngModelChange)="formSectorId.set(+$event || '')" class="select-field text-sm">
                <option value="">Seleccionar sector...</option>
                @for (s of sectores(); track s.id) {
                  <option [value]="s.id">{{ s.nombre }} ({{ s.codigo }})</option>
                }
              </select>
              @if (sectores().length === 0 && !cargandoSectores()) {
                <p class="text-xs text-amber-600 mt-1">
                  Sin sectores en BD. Ejecuta primero <code>cargar_datos_iniciales.bat</code>.
                </p>
              }
            </div>

          </div>
          <div class="flex gap-2 mt-4">
            <button (click)="guardar()" [disabled]="!formValido()"
                    class="btn-primary text-sm disabled:opacity-50 disabled:cursor-not-allowed">
              Guardar
            </button>
            <button (click)="cerrarFormulario()" class="btn-outline text-sm">Cancelar</button>
          </div>
        </div>
      }

      <!-- Grid de tarjetas -->
      <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        @for (t of tecnicos(); track t.id) {
          <div class="card relative group hover:shadow-md transition-shadow">

            <button (click)="confirmarEliminar(t)"
                    class="absolute top-3 right-3 opacity-0 group-hover:opacity-100 transition-opacity
                           w-7 h-7 flex items-center justify-center rounded-full bg-red-100 text-red-500 hover:bg-red-200">
              <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
              </svg>
            </button>

            <div class="flex items-start gap-3">
              <div class="w-10 h-10 bg-primary/10 rounded-full flex items-center justify-center flex-shrink-0">
                <svg class="w-5 h-5 text-primary" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                    d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z"/>
                </svg>
              </div>
              <div class="flex-1 min-w-0">
                <p class="font-bold text-gray-800">{{ t.nombre }}</p>
                <p class="text-xs text-gray-400 font-mono">{{ t.sector?.codigo }}</p>
                <p class="text-xs text-gray-500 mb-3">{{ t.sector?.nombre }}</p>
                <div class="flex items-center gap-2 text-sm text-gray-700">
                  <svg class="w-4 h-4 text-primary flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                      d="M3 5a2 2 0 012-2h3.28a1 1 0 01.948.684l1.498 4.493a1 1 0 01-.502 1.21l-2.257 1.13a11.042 11.042 0 005.516 5.516l1.13-2.257a1 1 0 011.21-.502l4.493 1.498a1 1 0 01.684.949V19a2 2 0 01-2 2h-1C9.716 21 3 14.284 3 6V5z"/>
                  </svg>
                  {{ t.telefono }}
                </div>
              </div>
            </div>

            <button (click)="abrirEditar(t)"
                    class="mt-3 w-full text-xs text-gray-400 hover:text-primary text-center pt-2 border-t border-gray-50">
              Editar contacto
            </button>
          </div>
        } @empty {
          <div class="col-span-3 text-center py-12 text-gray-400">
            <p>Sin contactos registrados.</p>
            <p class="text-sm mt-1">Agrega un técnico de campo con el botón superior.</p>
          </div>
        }
      </div>
    </div>
  `
})
export class ContactosComponent implements OnInit {
  private _tecnicos          = signal<TecnicoCampo[]>([]);
  private _sectores          = signal<Sector[]>([]);
  private _formularioAbierto = signal(false);
  private _editandoId        = signal<number | null>(null);
  private _cargandoSectores  = signal(true);

  tecnicos          = this._tecnicos.asReadonly();
  sectores          = this._sectores.asReadonly();
  formularioAbierto = this._formularioAbierto.asReadonly();
  editandoId        = this._editandoId.asReadonly();
  cargandoSectores  = this._cargandoSectores.asReadonly();

  formNombre   = signal('');
  formTelefono = signal('');
  formSectorId = signal<number | ''>('' );

  formValido = computed(() =>
    !!this.formNombre().trim() && !!this.formTelefono().trim() && this.formSectorId() !== ''
  );

  constructor(private api: ApiService) {}

  ngOnInit(): void {
    this.cargarSectores();
    this.cargarTecnicos();
  }

  cargarSectores(): void {
    this._cargandoSectores.set(true);
    this.api.getSectoresSimple().subscribe({
      next: (lista) => { this._sectores.set(lista); this._cargandoSectores.set(false); },
      error: ()     => { this._cargandoSectores.set(false); }
    });
  }

  cargarTecnicos(): void {
    this.api.getTecnicos().subscribe({
      next: (data: any) => {
        // Soporta tanto array plano como respuesta paginada {results:[]}
        const lista = Array.isArray(data) ? data : (data.results ?? []);
        this._tecnicos.set(lista);
      },
      error: () => this._tecnicos.set([])
    });
  }

  abrirFormulario(): void {
    this.formNombre.set('');
    this.formTelefono.set('');
    this.formSectorId.set('');
    this._editandoId.set(null);
    this._formularioAbierto.set(true);
  }

  abrirEditar(t: TecnicoCampo): void {
    this.formNombre.set(t.nombre);
    this.formTelefono.set(t.telefono);
    this.formSectorId.set(t.sector?.id ?? '');
    this._editandoId.set(t.id);
    this._formularioAbierto.set(true);
  }

  cerrarFormulario(): void { this._formularioAbierto.set(false); }

  guardar(): void {
    const payload: any = {
      nombre:    this.formNombre(),
      telefono:  this.formTelefono(),
      sector_id: this.formSectorId()
    };
    const id  = this._editandoId();
    const obs = id ? this.api.updateTecnico(id, payload) : this.api.createTecnico(payload);
    obs.subscribe({ next: () => { this.cerrarFormulario(); this.cargarTecnicos(); } });
  }

  confirmarEliminar(t: TecnicoCampo): void {
    if (!confirm(`¿Eliminar a ${t.nombre}?`)) return;
    this.api.deleteTecnico(t.id).subscribe({ next: () => this.cargarTecnicos() });
  }
}
