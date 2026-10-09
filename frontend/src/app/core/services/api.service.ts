import { Injectable }   from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable }   from 'rxjs';
import { map }          from 'rxjs/operators';
import { Alerta, TecnicoCampo, Reporte, Sector } from '../models/alerta.model';
import { Usuario }      from '../models/user.model';
import { UsuarioOp, AuditLog, DashboardStats } from '../models/dashboard.model'; // Ajusta la ruta a tu modelo

export interface PaginatedResponse<T> {
  count:    number;
  next:     string | null;
  previous: string | null;
  results:  T[];
}

@Injectable({ providedIn: 'root' })
export class ApiService {

  constructor(private http: HttpClient) {}

  // ── Alertas ───────────────────────────────────────────────────────────────

  getAlertas(params?: Record<string, string>, page?: number): Observable<PaginatedResponse<Alerta>> {
    let url = '/api/alertas/';
    const queryParams = new URLSearchParams();
    if (params) {
      for (const [k, v] of Object.entries(params)) {
        if (v) queryParams.set(k, v);
      }
    }
    if (page && page > 1) queryParams.set('page', String(page));
    const qs = queryParams.toString();
    if (qs) url += '?' + qs;
    return this.http.get<PaginatedResponse<Alerta>>(url);
  }

  getAlerta(id: number): Observable<Alerta> {
    return this.http.get<Alerta>(`/api/alertas/${id}/`);
  }

  getAuditoria(id: number): Observable<Alerta> {
    return this.http.get<Alerta>(`/api/auditoria/${id}/`);
  }

  patchAlerta(id: number, data: Partial<Alerta>): Observable<Alerta> {
    return this.http.patch<Alerta>(`/api/alertas/${id}/`, data);
  }

  notificarSms(alertaId: number, tecnicoIds: number[]): Observable<{ enviados: number }> {
    return this.http.post<{ enviados: number }>(`/api/alertas/${alertaId}/notificar/`, { tecnico_ids: tecnicoIds });
  }

  solicitarUrlEvidencia(alertaId: number, filename: string, contentType: string): Observable<{ upload_url: string; s3_key: string }> {
    return this.http.post<{ upload_url: string; s3_key: string }>(
      `/api/alertas/${alertaId}/evidencia/`,
      { filename, content_type: contentType }
    );
  }

  confirmarEvidencia(alertaId: number, s3Key: string): Observable<{ status: string }> {
    return this.http.post<{ status: string }>(`/api/alertas/${alertaId}/evidencia/`, { s3_key: s3Key });
  }

  exportarGeoJson(alertaId: number): Observable<Blob> {
    return this.http.get(`/api/alertas/${alertaId}/geojson/`, { responseType: 'blob' });
  }

  descargarPdf(alertaId: number): Observable<Blob> {
    return this.http.get(`/api/alertas/${alertaId}/pdf/`, { responseType: 'blob' });
  }

  // ── Sectores ──────────────────────────────────────────────────────────────

  getSectores(): Observable<any> {
    // rest_framework_gis con paginacion devuelve {count, results: FeatureCollection}
    // Extraemos siempre el FeatureCollection real.
    return this.http.get<any>('/api/sectores/').pipe(
      map((r: any) => r?.results ?? r)
    );
  }

  getSectoresSimple(): Observable<Sector[]> {
    return this.http.get<any>('/api/sectores/simple/').pipe(
      map((r: any) => Array.isArray(r) ? r : (r.results ?? []))
    );
  }

  getSectoresGeoJson(): Observable<object> {
    return this.http.get<object>('/api/sectores/geojson/');
  }

  // ── Técnicos de campo (Contactos) ─────────────────────────────────────────

  getTecnicos(): Observable<TecnicoCampo[]> {
    return this.http.get<any>('/api/tecnicos/').pipe(
      map((r: any) => Array.isArray(r) ? r : (r.results ?? []))
    );
  }

  createTecnico(data: Partial<TecnicoCampo>): Observable<TecnicoCampo> {
    return this.http.post<TecnicoCampo>('/api/tecnicos/', data);
  }

  updateTecnico(id: number, data: Partial<TecnicoCampo>): Observable<TecnicoCampo> {
    return this.http.patch<TecnicoCampo>(`/api/tecnicos/${id}/`, data);
  }

  deleteTecnico(id: number): Observable<void> {
    return this.http.delete<void>(`/api/tecnicos/${id}/`);
  }

  // ── Usuarios ──────────────────────────────────────────────────────────────

  getUsuarios(): Observable<PaginatedResponse<Usuario>> {
    return this.http.get<PaginatedResponse<Usuario>>('/api/usuarios/');
  }

  createUsuario(data: Partial<Usuario> & { password: string }): Observable<Usuario> {
    return this.http.post<Usuario>('/api/usuarios/', data);
  }

  updateUsuario(id: number, data: Partial<Usuario>): Observable<Usuario> {
    return this.http.patch<Usuario>(`/api/usuarios/${id}/`, data);
  }

  deleteUsuario(id: number): Observable<void> {
    return this.http.delete<void>(`/api/usuarios/${id}/`);
  }

  getMiPerfil(): Observable<Usuario> {
    return this.http.get<Usuario>('/api/usuarios/me/');
  }

  updateMiPerfil(data: Partial<Usuario>): Observable<Usuario> {
    return this.http.patch<Usuario>('/api/usuarios/me/', data);
  }

  // ── Reportes ──────────────────────────────────────────────────────────────

  getReportes(): Observable<Reporte[]> {
    return this.http.get<Reporte[]>('/api/reportes/');
  }

  // ── Pipeline / Dashboard ──────────────────────────────────────────────────

  getDashboardStats(params?: { periodo?: string; area?: string }): Observable<DashboardStats> {
    let httpParams = new HttpParams();
    if (params?.periodo) {
      httpParams = httpParams.set('periodo', params.periodo);
    }
    if (params?.area) {
      httpParams = httpParams.set('area', params.area);
    }
    return this.http.get<DashboardStats>('/api/dashboard/stats/', { params: httpParams });
  }

  getAuditLogs(usuarioId?: string): Observable<AuditLog[]> {
    let params = new HttpParams();
    if (usuarioId) {
      params = params.set('usuario_id', usuarioId);
    }
    // El backend pagina por defecto: puede llegar como array o como
    // {count, next, previous, results}. Normalizamos siempre a array.
    return this.http.get<any>('/api/dashboard/audit-logs/', { params }).pipe(
      map((r: any) => Array.isArray(r) ? r : (r?.results ?? []))
    );
  }

  // ── Trigger manual detección (solo Admin) ────────────────────────────────

  triggerDeteccion(): Observable<{ task_id: string }> {
    return this.http.post<{ task_id: string }>('/api/pipeline/trigger/', {});
  }
}