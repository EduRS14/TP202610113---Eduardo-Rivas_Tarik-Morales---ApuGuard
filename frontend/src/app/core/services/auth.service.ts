import { Injectable, signal, computed } from '@angular/core';
import { HttpClient }                   from '@angular/common/http';
import { Router }                       from '@angular/router';
import { tap }                          from 'rxjs/operators';
import { Observable }                   from 'rxjs';
import { LoginRequest, TokenResponse, JwtPayload, Rol, Usuario } from '../models/user.model';

const ACCESS_KEY  = 'apuguard_access';
const REFRESH_KEY = 'apuguard_refresh';

@Injectable({ providedIn: 'root' })
export class AuthService {

  private _usuario = signal<JwtPayload | null>(null);

  /** Usuario autenticado actual (signal reactivo) */
  readonly usuario = this._usuario.asReadonly();

  /** true si hay sesión activa */
  readonly isAuthenticated = computed(() => this._usuario() !== null);

  /** true si el usuario tiene rol Administrador */
  readonly isAdmin = computed(() => this._usuario()?.rol === 'Administrador');

  constructor(private http: HttpClient, private router: Router) {
    // Restaurar sesión desde localStorage al iniciar
    this._restoreSession();
  }

  // ── Login ──────────────────────────────────────────────────────────────────

  login(credentials: LoginRequest): Observable<TokenResponse> {
    return this.http.post<TokenResponse>('/api/auth/token/', credentials).pipe(
      tap(tokens => this._saveTokens(tokens))
    );
  }

  // ── Tokens ────────────────────────────────────────────────────────────────

  getAccessToken(): string | null {
    return localStorage.getItem(ACCESS_KEY);
  }

  refreshToken(): Observable<TokenResponse> {
    const refresh = localStorage.getItem(REFRESH_KEY);
    return this.http.post<TokenResponse>('/api/auth/token/refresh/', { refresh }).pipe(
      tap(tokens => this._saveTokens(tokens))
    );
  }

  // ── Logout ────────────────────────────────────────────────────────────────

  /** Cierre de sesión desde la UI: revoca el refresh en el backend y limpia
   *  la sesión local siempre (éxito o error) para no dejar al usuario enganchado. */
  logout(): void {
    const refresh = localStorage.getItem(REFRESH_KEY);
    if (refresh) {
      this.http.post('/api/auth/logout/', { refresh }).subscribe({
        next:  () => {},
        error: () => {},
      });
    }
    this.logoutLocal();
    this.router.navigate(['/login']);
  }

  /**
   * Solo limpieza local, sin llamada al backend.
   * La usa el interceptor ante un 401: el token ya es inválido, reintentar
   * el logout solo provocaría otro error.
   */
  logoutLocal(): void {
    localStorage.removeItem(ACCESS_KEY);
    localStorage.removeItem(REFRESH_KEY);
    this._usuario.set(null);
  }

  // ── Helpers privados ──────────────────────────────────────────────────────

  private _saveTokens(tokens: TokenResponse): void {
    localStorage.setItem(ACCESS_KEY,  tokens.access);
    localStorage.setItem(REFRESH_KEY, tokens.refresh);
    const payload = this._decodeJwt(tokens.access);
    this._usuario.set(payload);
  }

  private _restoreSession(): void {
    const token = localStorage.getItem(ACCESS_KEY);
    if (!token) return;
    const payload = this._decodeJwt(token);
    if (payload && payload.exp * 1000 > Date.now()) {
      this._usuario.set(payload);
    } else {
      // Token expirado: limpiar
      localStorage.removeItem(ACCESS_KEY);
      localStorage.removeItem(REFRESH_KEY);
    }
  }

  private _decodeJwt(token: string): JwtPayload | null {
    try {
      const base64 = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
      return JSON.parse(atob(base64)) as JwtPayload;
    } catch {
      return null;
    }
  }
}
