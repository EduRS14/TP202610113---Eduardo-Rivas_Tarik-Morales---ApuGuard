import { Component, signal } from '@angular/core';
import { CommonModule }      from '@angular/common';
import { FormsModule }       from '@angular/forms';

@Component({
  selector: 'app-configuracion',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <div class="max-w-2xl mx-auto px-6 py-6">

      <h1 class="text-xl font-bold text-gray-800 flex items-center gap-2 mb-1">
        <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
            d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"/>
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/>
        </svg>
        Configuración del Sistema
      </h1>
      <p class="text-sm text-gray-500 mb-6">Gestiona la información institucional y parámetros del sistema.</p>

      <!-- Información institucional -->
      <div class="card mb-6">
        <div class="bg-primary text-white rounded-lg p-4 flex items-center gap-3 mb-4">
          <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
              d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4"/>
          </svg>
          <div>
            <p class="font-semibold">Información Institucional</p>
            <p class="text-green-200 text-xs">Datos de contacto y configuración organizacional</p>
          </div>
        </div>

        @if (!editando()) {
          <!-- Vista -->
          <div class="space-y-3">
            <div>
              <label class="text-xs text-gray-500 uppercase">Nombre de la Organización</label>
              <div class="input-field bg-gray-50 flex items-center gap-2 text-gray-700 mt-1">
                <svg class="w-4 h-4 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                    d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16"/>
                </svg>
                <span class="text-sm">{{ form.organizacion }}</span>
              </div>
            </div>
            <div class="grid grid-cols-2 gap-4">
              <div>
                <label class="text-xs text-gray-500 uppercase">Correo Institucional</label>
                <div class="input-field bg-gray-50 text-sm text-gray-700 mt-1">{{ form.email }}</div>
              </div>
              <div>
                <label class="text-xs text-gray-500 uppercase">Teléfono de Contacto</label>
                <div class="input-field bg-gray-50 text-sm text-gray-700 mt-1">{{ form.telefono }}</div>
              </div>
            </div>
            <div>
              <label class="text-xs text-gray-500 uppercase">Dirección</label>
              <div class="input-field bg-gray-50 text-sm text-gray-700 mt-1">{{ form.direccion }}</div>
            </div>
          </div>
          <button (click)="editando.set(true)" class="btn-primary text-sm mt-4">Editar Configuración</button>
        } @else {
          <!-- Edición -->
          <div class="space-y-3">
            <div>
              <label class="text-xs text-gray-500 uppercase">Nombre de la Organización</label>
              <input type="text" [(ngModel)]="form.organizacion" class="input-field mt-1 text-sm">
            </div>
            <div class="grid grid-cols-2 gap-4">
              <div>
                <label class="text-xs text-gray-500 uppercase">Correo Institucional</label>
                <input type="email" [(ngModel)]="form.email" class="input-field mt-1 text-sm">
              </div>
              <div>
                <label class="text-xs text-gray-500 uppercase">Teléfono de Contacto</label>
                <input type="text" [(ngModel)]="form.telefono" class="input-field mt-1 text-sm">
              </div>
            </div>
            <div>
              <label class="text-xs text-gray-500 uppercase">Dirección</label>
              <input type="text" [(ngModel)]="form.direccion" class="input-field mt-1 text-sm">
            </div>
          </div>
          <div class="flex gap-2 mt-4">
            <button (click)="guardar()" class="btn-primary text-sm">Guardar</button>
            <button (click)="editando.set(false)" class="btn-outline text-sm">Cancelar</button>
          </div>
        }
      </div>

      <!-- Información del sistema -->
      <div class="card">
        <p class="font-semibold text-gray-800 mb-4">Información del Sistema</p>
        <div class="space-y-3">
          <div>
            <p class="text-xs text-gray-500">Versión del Sistema</p>
            <p class="text-sm text-primary font-medium">ApuGuard Sprint 1 — v1.0.0</p>
          </div>
          <div>
            <p class="text-xs text-gray-500">Última Actualización</p>
            <p class="text-sm text-primary font-medium">2026-06-30</p>
          </div>
          <div>
            <p class="text-xs text-gray-500">Modo de Operación</p>
            <p class="text-sm text-primary font-medium">Producción</p>
          </div>
        </div>
      </div>
    </div>
  `
})
export class ConfiguracionComponent {
  editando = signal(false);

  form = {
    organizacion: 'Instituto Nacional de Recursos Naturales',
    email:        'contacto@institucion.gob.pe',
    telefono:     '+51 1 234 5678',
    direccion:    'Av. Principal 123, Lima, Perú'
  };

  guardar(): void {
    // TODO: persistir vía API cuando exista el endpoint
    this.editando.set(false);
  }
}
