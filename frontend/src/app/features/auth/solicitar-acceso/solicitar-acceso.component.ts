import { Component, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';

@Component({
  selector: 'app-solicitar-acceso',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink],
  template: `
    <div class="min-h-screen bg-amber-50 flex items-center justify-center p-4 md:p-8">
      <div class="w-full max-w-5xl bg-white rounded-2xl shadow-md border border-gray-100 p-6 md:p-10 relative">
        
        <!-- Botón Volver -->
        <a routerLink="/login" 
           class="inline-flex items-center gap-2 text-sm text-primary font-semibold hover:text-primary-light transition-colors mb-6">
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7"/>
          </svg>
          Volver
        </a>

        <!-- Encabezado -->
        <div class="text-center mb-8">
          <h1 class="text-2xl md:text-4xl font-bold text-primary leading-tight">
            Solicitud de Acceso - Registro Institucional
          </h1>
          <p class="text-sm text-gray-500 mt-2">
            Plataforma de detección de deforestación en la Reserva Tambopata
          </p>
        </div>

        <!-- Formulario -->
        <form (ngSubmit)="onSubmit()" #form="ngForm" class="grid grid-cols-1 md:grid-cols-3 gap-x-6 gap-y-5">
          
          <!-- Fila 1 -->
          <div>
            <label class="block text-xs font-semibold text-primary mb-1 uppercase tracking-wide">
              Nombre Completo
            </label>
            <input type="text" name="nombreCompleto" [(ngModel)]="formData.nombreCompleto" required
                   class="input-field" placeholder="Ej. Juan Pérez">
          </div>

          <div>
            <label class="block text-xs font-semibold text-primary mb-1 uppercase tracking-wide">
              Correo Institucional
            </label>
            <input type="email" name="correo" [(ngModel)]="formData.correo" required
                   class="input-field" placeholder="usuario@institucion.gob.pe">
          </div>

          <div>
            <label class="block text-xs font-semibold text-primary mb-1 uppercase tracking-wide">
              Teléfono
            </label>
            <input type="tel" name="telefono" [(ngModel)]="formData.telefono" required
                   class="input-field" placeholder="+51 987 654 321">
          </div>

          <!-- Fila 2 -->
          <div>
            <label class="block text-xs font-semibold text-primary mb-1 uppercase tracking-wide">
              Institución
            </label>
            <input type="text" name="institucion" [(ngModel)]="formData.institucion" required
                   class="input-field" placeholder="Nombre de la entidad">
          </div>

          <div>
            <label class="block text-xs font-semibold text-primary mb-1 uppercase tracking-wide">
              Tipo de institución
            </label>
            <select name="tipoInstitucion" [(ngModel)]="formData.tipoInstitucion" required class="select-field">
              <option value="gobierno">Gobierno</option>
              <option value="ong">ONG</option>
              <option value="investigacion">Investigación</option>
              <option value="otro">Otro</option>
            </select>
          </div>

          <div>
            <label class="block text-xs font-semibold text-primary mb-1 uppercase tracking-wide">
              Rol Solicitado
            </label>
            <select name="rolSolicitado" [(ngModel)]="formData.rolSolicitado" required class="select-field">
              <option value="analista">Analista de monitoreo</option>
              <option value="tecnico">Técnico / Ingeniero</option>
              <option value="administrador">Administrador</option>
            </select>
          </div>

          <!-- Fila 3 -->
          <div>
            <label class="block text-xs font-semibold text-primary mb-1 uppercase tracking-wide">
              Área de trabajo
            </label>
            <input type="text" name="areaTrabajo" [(ngModel)]="formData.areaTrabajo"
                   class="input-field" placeholder="Ej. Gestión Ambiental">
          </div>

          <div class="md:col-span-2">
            <label class="block text-xs font-semibold text-primary mb-1 uppercase tracking-wide">
              Justificación
            </label>
            <input type="text" name="justificacion" [(ngModel)]="formData.justificacion" required
                   class="input-field" placeholder="Explique brevemente el uso que le dará al sistema">
          </div>

          <!-- Fila 4: Contraseñas -->
          <div class="md:col-start-2">
            <label class="block text-xs font-semibold text-primary mb-1 uppercase tracking-wide">
              Contraseña
            </label>
            <input type="password" name="password" [(ngModel)]="formData.password" required
                   class="input-field" placeholder="••••••••">
          </div>

          <div>
            <label class="block text-xs font-semibold text-primary mb-1 uppercase tracking-wide">
              Confirmar Contraseña
            </label>
            <input type="password" name="confirmPassword" [(ngModel)]="formData.confirmPassword" required
                   class="input-field" placeholder="••••••••">
          </div>

          <!-- Botón de Envío y Mensajes -->
          <div class="md:col-span-3 flex flex-col items-center gap-4 mt-6">
            
            <label class="flex items-center gap-2 cursor-pointer text-sm text-gray-700">
              <input type="checkbox" name="aceptaDatos" [(ngModel)]="formData.aceptaDatos" required
                     class="w-4 h-4 rounded text-primary focus:ring-primary border-gray-300">
              <span class="text-primary font-medium">Aceptar uso de datos</span>
            </label>

            @if (errorMsg()) {
              <p class="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-4 py-2 w-full max-w-md text-center">
                {{ errorMsg() }}
              </p>
            }

            @if (exitoMsg()) {
              <p class="text-sm text-green-700 bg-green-50 border border-green-200 rounded-lg px-4 py-2 w-full max-w-md text-center">
                {{ exitoMsg() }}
              </p>
            }

            <button type="submit" [disabled]="cargando() || !formData.aceptaDatos" 
                    class="btn-primary w-full max-w-xs py-3 text-base justify-center font-bold">
              @if (cargando()) {
                <span>Enviando...</span>
              } @else {
                <span>Enviar Solicitud</span>
              }
            </button>

            <p class="text-sm text-gray-600 mt-2">
              ¿Ya tienes cuenta? 
              <a routerLink="/login" class="text-primary font-semibold hover:underline">Inicia sesión aquí</a>
            </p>
          </div>

        </form>
      </div>
    </div>
  `
})
export class SolicitarAccesoComponent {
  formData = {
    nombreCompleto: '',
    correo: '',
    telefono: '',
    institucion: '',
    tipoInstitucion: '',
    rolSolicitado: '',
    areaTrabajo: '',
    justificacion: '',
    password: '',
    confirmPassword: '',
    aceptaDatos: false
  };

  private _cargando = signal(false);
  private _errorMsg = signal('');
  private _exitoMsg = signal('');

  cargando = this._cargando.asReadonly();
  errorMsg = this._errorMsg.asReadonly();
  exitoMsg = this._exitoMsg.asReadonly();

  constructor(private router: Router) {}

  onSubmit(): void {
    this._errorMsg.set('');
    this._exitoMsg.set('');

    if (this.formData.password !== this.formData.confirmPassword) {
      this._errorMsg.set('Las contraseñas no coinciden.');
      return;
    }

    this._cargando.set(true);

    // Simulación de envío o llamada al servicio
    setTimeout(() => {
      this._cargando.set(false);
      this._exitoMsg.set('Solicitud enviada con éxito. Un administrador revisará tu petición.');
    }, 1500);
  }
}