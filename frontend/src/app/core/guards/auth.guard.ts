import { inject }         from '@angular/core';
import { CanActivateFn }  from '@angular/router';
import { Router }         from '@angular/router';
import { AuthService }    from '../services/auth.service';

export const authGuard: CanActivateFn = () => {
  const auth   = inject(AuthService);
  const router = inject(Router);

  if (auth.isAuthenticated()) return true;

  router.navigate(['/login']);
  return false;
};
