import { Component, computed, signal } from '@angular/core';
import { RouterLink, RouterLinkActive } from '@angular/router';
import { CommonModule }  from '@angular/common';
import { AuthService }   from '../../../core/services/auth.service';

interface NavItem {
  label: string;
  route: string;
  adminOnly?: boolean;
}

@Component({
  selector: 'app-navbar',
  standalone: true,
  imports: [CommonModule, RouterLink, RouterLinkActive],
  template: `
    <nav class="fixed top-0 left-0 right-0 z-50 bg-white border-b border-gray-200 h-16 flex items-center px-6 shadow-sm">

      <!-- Logo -->
      <a routerLink="/dashboard" class="flex items-center mr-8 flex-shrink-0">
        <img src="assets/logo.jpeg" alt="ApuGuard" class="h-9 w-auto object-contain">
      </a>

      <!-- Tabs de navegación -->
      <div class="flex items-center gap-1 flex-1">
        @for (item of navItems(); track item.route) {
          <a
            [routerLink]="item.route"
            routerLinkActive="bg-primary/10 text-primary font-semibold"
            class="px-4 py-2 rounded-lg text-sm text-gray-600 hover:bg-gray-100 transition-colors duration-150">
            {{ item.label }}
          </a>
        }
      </div>

      <!-- Acciones derecha -->
      <div class="flex items-center gap-3 ml-auto">

        <!-- Botón refresh -->
        <button class="p-2 rounded-lg hover:bg-gray-100 text-gray-500 transition-colors">
          <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round"
              d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/>
          </svg>
        </button>

        <!-- Notificación campana -->
        <button class="relative p-2 rounded-lg hover:bg-gray-100 text-gray-500 transition-colors">
          <svg class="w-5 h-5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round"
              d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9"/>
          </svg>
          <span class="absolute top-1 right-1 w-2 h-2 bg-red-500 rounded-full"></span>
        </button>

        <!-- Perfil dropdown -->
        <div class="relative">
          <button
            (click)="toggleDropdown()"
            class="flex items-center gap-2 px-3 py-1.5 rounded-lg hover:bg-gray-100 transition-colors">
            <div class="w-8 h-8 bg-primary rounded-full flex items-center justify-center text-white text-sm font-semibold">
              {{ iniciales() }}
            </div>
            <div class="text-left hidden sm:block">
              <p class="text-sm font-medium text-gray-800 leading-tight">{{ usuario()?.username }}</p>
              <p class="text-xs text-gray-500 leading-tight">{{ usuario()?.rol }}</p>
            </div>
          </button>

          @if (dropdownAbierto()) {
            <div class="absolute right-0 mt-1 w-44 bg-white rounded-xl shadow-lg border border-gray-100 py-1 z-50">
              <a routerLink="/perfil" (click)="cerrarDropdown()"
                 class="flex items-center gap-2 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round"
                    d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"/>
                </svg>
                Perfil
              </a>
              <button (click)="logout()"
                class="flex items-center gap-2 px-4 py-2 text-sm text-red-600 hover:bg-red-50 w-full text-left">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round"
                    d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1"/>
                </svg>
                Cerrar Sesión
              </button>
            </div>
          }
        </div>
      </div>
    </nav>

    <!-- Overlay para cerrar dropdown -->
    @if (dropdownAbierto()) {
      <div class="fixed inset-0 z-40" (click)="cerrarDropdown()"></div>
    }
  `
})
export class NavbarComponent {
  private _dropdownAbierto = signal(false);
  dropdownAbierto = this._dropdownAbierto.asReadonly();

  usuario  = this.auth.usuario;
  isAdmin  = this.auth.isAdmin;

  iniciales = computed(() => {
    const u = this.usuario();
    if (!u) return '?';
    return u.username.substring(0, 2).toUpperCase();
  });

  navItems = computed<NavItem[]>(() => {
    const items: NavItem[] = [
      { label: 'Dashboard',    route: '/dashboard' },
      { label: 'Alertas',      route: '/alertas' },
    ];
    if (this.isAdmin()) {
      items.push(
        { label: 'Usuarios',     route: '/usuarios',      adminOnly: true },
        { label: 'Contactos',    route: '/contactos',     adminOnly: true },
        { label: 'Configuración',route: '/configuracion', adminOnly: true },
      );
    }
    return items;
  });

  constructor(private auth: AuthService) {}

  toggleDropdown() { this._dropdownAbierto.update(v => !v); }
  cerrarDropdown() { this._dropdownAbierto.set(false); }
  logout()         { this.auth.logout(); }
}
