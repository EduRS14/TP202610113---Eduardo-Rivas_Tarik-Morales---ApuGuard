import { Component, computed, signal } from '@angular/core';
import { RouterOutlet, Router, NavigationEnd } from '@angular/router';
import { CommonModule }   from '@angular/common';
import { filter }         from 'rxjs/operators';
import { AuthService }    from './core/services/auth.service';
import { NavbarComponent } from './shared/components/navbar/navbar.component';

/** Rutas donde NO se muestra la navbar */
const RUTAS_SIN_NAVBAR = ['/login', '/acerca', '/'];

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [RouterOutlet, CommonModule, NavbarComponent],
  template: `
    <app-navbar *ngIf="mostrarNavbar()" />
    <main [class.pt-16]="mostrarNavbar()">
      <router-outlet />
    </main>
  `
})
export class AppComponent {
  // Convertido a Signal para garantizar reactividad en el computed
  private rutaActual = signal<string>(window.location.pathname);

  mostrarNavbar = computed(() => {
    const autenticado = this.auth.isAuthenticated();
    const ruta = this.rutaActual();
    return autenticado && !RUTAS_SIN_NAVBAR.some(r => ruta === r);
  });

  constructor(private auth: AuthService, private router: Router) {
    this.router.events.pipe(
      filter((e): e is NavigationEnd => e instanceof NavigationEnd)
    ).subscribe((e) => {
      // Actualiza la señal reactiva en cada cambio de ruta
      this.rutaActual.set(e.urlAfterRedirects.split('?')[0]);
    });
  }
}