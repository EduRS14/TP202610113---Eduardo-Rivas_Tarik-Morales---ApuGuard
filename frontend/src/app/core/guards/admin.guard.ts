import { inject }         from '@angular/core';
import { CanActivateFn }  from '@angular/router';
import { Router }         from '@angular/router';
import { AuthService }    from '../services/auth.service';

/** Bloquea rutas exclusivas de Administrador */
export const adminGuard: CanActivateFn = () => {
  const auth   = inject(AuthService);
  const router = inject(Router);

  if (auth.isAdmin()) return true;

  // Usuario autenticado pero sin permisos → redirigir al dashboard
  router.navigate(['/dashboard']);
  return false;
};
