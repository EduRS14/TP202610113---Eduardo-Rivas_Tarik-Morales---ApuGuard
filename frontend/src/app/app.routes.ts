import { Routes }     from '@angular/router';
import { authGuard }  from './core/guards/auth.guard';
import { adminGuard } from './core/guards/admin.guard';

export const routes: Routes = [

  // ── Públicas ────────────────────────────────────────────────────────────
  {
    path: '',
    redirectTo: 'acerca',
    pathMatch: 'full'
  },
  {
    path: 'acerca',
    loadComponent: () => import('./features/auth/acerca/acerca.component').then(m => m.AcercaComponent)
  },
  {
    path: 'login',
    loadComponent: () => import('./features/auth/login/login.component').then(m => m.LoginComponent)
  },
  {
  path: 'solicitar-acceso',
    loadComponent: () => import('./features/auth/solicitar-acceso/solicitar-acceso.component').then(m => m.SolicitarAccesoComponent)
  },

  // ── Protegidas (requieren JWT) ───────────────────────────────────────────
  {
    path: 'dashboard',
    canActivate: [authGuard],
    loadComponent: () => import('./features/dashboard/dashboard.component').then(m => m.DashboardComponent)
  },
  {
    path: 'alertas',
    canActivate: [authGuard],
    loadComponent: () => import('./features/alertas/alertas.component').then(m => m.AlertasComponent)
  },
  {
    path: 'perfil',
    canActivate: [authGuard],
    loadComponent: () => import('./features/perfil/perfil.component').then(m => m.PerfilComponent)
  },

  // ── Solo Administrador ───────────────────────────────────────────────────
  {
    path: 'usuarios',
    canActivate: [authGuard, adminGuard],
    loadComponent: () => import('./features/usuarios/usuarios.component').then(m => m.UsuariosComponent)
  },
  {
    path: 'contactos',
    canActivate: [authGuard, adminGuard],
    loadComponent: () => import('./features/contactos/contactos.component').then(m => m.ContactosComponent)
  },
  {
    path: 'configuracion',
    canActivate: [authGuard, adminGuard],
    loadComponent: () => import('./features/configuracion/configuracion.component').then(m => m.ConfiguracionComponent)
  },

  // ── Fallback ─────────────────────────────────────────────────────────────
  {
    path: '**',
    redirectTo: 'dashboard'
  }
];
