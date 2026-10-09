import { HttpInterceptorFn, HttpRequest, HttpHandlerFn, HttpErrorResponse } from '@angular/common/http';
import { inject }       from '@angular/core';
import { Router }       from '@angular/router';
import { catchError }   from 'rxjs/operators';
import { throwError }   from 'rxjs';
import { AuthService }  from '../services/auth.service';

/** Rutas que NO necesitan token */
const PUBLIC_URLS = ['/api/auth/token/', '/api/auth/token/refresh/'];

export const authInterceptor: HttpInterceptorFn = (
  req: HttpRequest<unknown>,
  next: HttpHandlerFn
) => {
  const authService = inject(AuthService);
  const router      = inject(Router);

  const isPublic = PUBLIC_URLS.some(url => req.url.includes(url));

  if (!isPublic) {
    const token = authService.getAccessToken();
    if (token) {
      req = req.clone({
        setHeaders: { Authorization: `Bearer ${token}` }
      });
    }
  }

  return next(req).pipe(
    catchError((error: HttpErrorResponse) => {
      if (error.status === 401 && !isPublic) {
        // Token expirado o inválido → limpiar sesión local y redirigir.
        // No se llama a logout(): el token ya no sirve, reintentarlo daría 401.
        authService.logoutLocal();
        router.navigate(['/login']);
      }
      return throwError(() => error);
    })
  );
};
