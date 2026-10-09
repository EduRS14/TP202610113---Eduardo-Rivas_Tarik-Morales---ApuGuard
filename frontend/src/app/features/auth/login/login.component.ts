import { Component, signal } from '@angular/core';
import { CommonModule }      from '@angular/common';
import { FormsModule }       from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { AuthService }       from '../../../core/services/auth.service';

@Component({
  selector: 'app-login',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink],
  template: `
    <div class="min-h-screen flex">
      <!-- Panel izquierdo verde -->
      <div class="hidden md:flex w-1/2 bg-primary items-center justify-center p-12">
        <div class="text-center text-white">
          <div class="bg-white rounded-2xl px-8 py-5 inline-block mb-6 shadow-lg">
            <img src="assets/logo.jpeg" alt="ApuGuard" class="h-20 w-auto object-contain">
          </div>
          <p class="text-green-200 text-sm">Plataforma de detección de deforestación<br>en la Reserva Tambopata</p>
        </div>
      </div>

      <!-- Panel derecho -->
      <div class="flex-1 flex items-center justify-center bg-amber-50 p-8">
        <div class="w-full max-w-sm">
          <button routerLink="/acerca" class="flex items-center gap-1 text-sm text-gray-500 hover:text-gray-700 mb-8">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7"/>
            </svg>
            Volver
          </button>

          <h2 class="text-2xl font-bold text-gray-800 mb-1">Iniciar Sesión</h2>
          <p class="text-sm text-gray-500 mb-6">Sistema APU GUARD — acceso institucional</p>

          <form (ngSubmit)="onSubmit()" #form="ngForm" class="space-y-4">
            <div>
              <label class="block text-xs font-semibold text-gray-600 mb-1 uppercase tracking-wide">
                Nombre de Usuario
              </label>
              <input type="text" name="username" [(ngModel)]="username" required
                     class="input-field" placeholder="usuario@institución">
            </div>
            <div>
              <label class="block text-xs font-semibold text-gray-600 mb-1 uppercase tracking-wide">
                Contraseña
              </label>
              <input type="password" name="password" [(ngModel)]="password" required
                     class="input-field" placeholder="••••••••">
            </div>

            @if (errorMsg()) {
              <p class="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
                {{ errorMsg() }}
              </p>
            }

            <button type="submit" [disabled]="cargando()"
                    class="btn-primary w-full justify-center mt-2">
              @if (cargando()) { <span>Ingresando...</span> }
              @else { <span>Iniciar Sesión</span> }
            </button>
          </form>

          <div class="mt-6 text-center space-y-2">
            <p class="text-sm text-gray-500">
              ¿No tienes cuenta?
              <a routerLink="/solicitar-acceso" class="text-primary font-medium hover:underline">
                Solicitar acceso aquí
              </a>
            </p>
            <p class="text-sm text-gray-500">
              <a href="#" class="text-primary hover:underline">¿Olvidaste tu contraseña?</a>
            </p>
          </div>
        </div>
      </div>
    </div>
  `
})
export class LoginComponent {
  username = '';
  password = '';

  private _cargando  = signal(false);
  private _errorMsg  = signal('');
  cargando  = this._cargando.asReadonly();
  errorMsg  = this._errorMsg.asReadonly();

  constructor(private auth: AuthService, private router: Router) {}

  onSubmit(): void {
    if (!this.username || !this.password) return;
    this._cargando.set(true);
    this._errorMsg.set('');

    this.auth.login({ username: this.username, password: this.password }).subscribe({
      next: () => this.router.navigate(['/dashboard']),
      error: (err) => {
        this._cargando.set(false);
        this._errorMsg.set(
          err.status === 401
            ? 'Credenciales incorrectas. Verifica tu usuario y contraseña.'
            : 'Error al conectar con el servidor. Intenta nuevamente.'
        );
      }
    });
  }
}
