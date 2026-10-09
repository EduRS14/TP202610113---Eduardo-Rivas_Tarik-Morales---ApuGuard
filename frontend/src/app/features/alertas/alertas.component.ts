import { Component, OnInit, signal, computed } from '@angular/core';
import { CommonModule }              from '@angular/common';
import { FormsModule }               from '@angular/forms';
import { ApiService }                from '../../core/services/api.service';
import { AuthService }               from '../../core/services/auth.service';
import { Alerta, RegistroSms, TecnicoCampo } from '../../core/models/alerta.model';

@Component({
  selector: 'app-alertas',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <div class="max-w-screen-xl mx-auto px-6 py-6">

      <div class="flex items-center justify-between mb-6">
        <div>
          <h1 class="text-xl font-bold text-gray-800">Gestión de Alertas</h1>
          <p class="text-sm text-gray-500">Historial de detecciones y acciones de prevención.</p>
        </div>
        @if (alertasPendientes() > 0) {
          <span class="bg-red-100 text-red-700 text-xs font-semibold px-3 py-1.5 rounded-full">
            {{ alertasPendientes() }} alertas pendientes
          </span>
        }
      </div>

      <!-- Filtros -->
      <div class="card mb-4">
        <div class="flex flex-wrap items-center gap-3">
          <!-- Fase G6: Todas (historial completo) vs solo las nuevas de la pasada -->
          <div class="inline-flex rounded-lg border border-gray-200 overflow-hidden text-sm shrink-0">
            <button type="button" (click)="setModo('todas')"
                    class="px-3 py-1.5 font-medium transition-colors"
                    [class.bg-primary]="modo() === 'todas'"
                    [class.text-white]="modo() === 'todas'"
                    [class.hover:bg-gray-100]="modo() !== 'todas'">
              Todas
            </button>
            <button type="button" (click)="setModo('nuevas')"
                    class="px-3 py-1.5 font-medium transition-colors border-l border-gray-200"
                    [class.bg-primary]="modo() === 'nuevas'"
                    [class.text-white]="modo() === 'nuevas'"
                    [class.hover:bg-gray-100]="modo() !== 'nuevas'">
              Nuevas en esta pasada
            </button>
          </div>
          <input type="date" [(ngModel)]="filtroDesde" class="input-field w-auto text-sm">
          <span class="text-gray-400 text-sm">—</span>
          <input type="date" [(ngModel)]="filtroHasta" class="input-field w-auto text-sm">
          <input type="text" [(ngModel)]="filtroZona" placeholder="Buscar zona..."
                 class="input-field w-48 text-sm">
          <button (click)="cargarAlertas()" class="btn-primary text-sm">Filtrar</button>
        </div>
      </div>

      <!-- Tabla -->
      <div class="card overflow-x-auto">
        <table class="w-full text-sm">
          <thead>
            <tr class="border-b border-gray-100">
              <th class="text-left py-3 px-2 text-xs font-semibold text-gray-500 uppercase">ID</th>
              <th class="text-left py-3 px-2 text-xs font-semibold text-gray-500 uppercase">Fecha</th>
              <th class="text-left py-3 px-2 text-xs font-semibold text-gray-500 uppercase">Zona</th>
              <th class="text-left py-3 px-2 text-xs font-semibold text-gray-500 uppercase">Coordenadas</th>
              <th class="text-left py-3 px-2 text-xs font-semibold text-gray-500 uppercase">Estado</th>
              <th class="text-left py-3 px-2 text-xs font-semibold text-gray-500 uppercase">Acciones</th>
            </tr>
          </thead>
          <tbody>
            @for (alerta of alertas(); track alerta.id) {
              <tr class="border-b border-gray-50 hover:bg-gray-50 transition-colors">
                <td class="py-3 px-2 font-medium text-gray-800">{{ alerta.codigo }}</td>
                <td class="py-3 px-2 text-gray-600">{{ alerta.fecha | date:'yyyy-MM-dd' }}</td>
                <td class="py-3 px-2 text-gray-700 font-medium">{{ alerta.zona }}</td>
                <td class="py-3 px-2 text-gray-500 font-mono text-xs">{{ alerta.coordenadas }}</td>
                <td class="py-3 px-2">
                  <span [class]="badgeClase(alerta.estado)">{{ alerta.estado }}</span>
                  @if (alerta.es_nueva) {
                    <span class="badge-nueva ml-1" title="Detectada por primera vez en la última pasada">Nueva</span>
                  }
                </td>
                <td class="py-3 px-2">
                  <div class="flex items-center gap-2">
                    <button (click)="abrirDetalle(alerta)"
                            class="text-xs text-primary hover:underline font-medium">Detalle</button>
                    @if (isAdmin()) {
                      <button (click)="abrirNotificar(alerta)"
                              class="text-xs text-gray-500 hover:text-primary hover:underline">Notificar</button>
                    }
                    <button (click)="toggleEstado(alerta)"
                            class="text-xs text-gray-400 hover:text-green-600 hover:underline">
                      {{ alerta.estado === 'Pendiente' ? 'Validar' : 'Reabrir' }}
                    </button>
                  </div>
                </td>
              </tr>
            } @empty {
              <tr><td colspan="6" class="py-8 text-center text-gray-400">Sin alertas registradas.</td></tr>
            }
          </tbody>
        </table>

        <!-- Paginacion -->
        <div class="flex items-center justify-between mt-3 pt-3 border-t border-gray-100">
          <p class="text-xs text-gray-400">
            Mostrando {{ ((paginaActual() - 1) * 100) + 1 }}–{{ paginaActual() * 100 > totalAlertas() ? totalAlertas() : paginaActual() * 100 }} de {{ totalAlertas() }} alertas
          </p>
          @if (totalPaginas() > 1) {
            <div class="flex items-center gap-1">
              <button (click)="irAPagina(1)" [disabled]="paginaActual() === 1"
                      class="px-2 py-1 text-xs rounded hover:bg-gray-100 disabled:opacity-30">&laquo;</button>
              <button (click)="irAPagina(paginaActual() - 1)" [disabled]="paginaActual() === 1"
                      class="px-2 py-1 text-xs rounded hover:bg-gray-100 disabled:opacity-30">&lsaquo;</button>
              @for (p of [paginaActual() - 2, paginaActual() - 1, paginaActual(), paginaActual() + 1, paginaActual() + 2]; track p) {
                @if (p >= 1 && p <= totalPaginas()) {
                  <button (click)="irAPagina(p)"
                          class="px-2 py-1 text-xs rounded"
                          [class.bg-primary]="p === paginaActual()"
                          [class.text-white]="p === paginaActual()"
                          [class.hover:bg-gray-100]="p !== paginaActual()">
                    {{ p }}
                  </button>
                }
              }
              <button (click)="irAPagina(paginaActual() + 1)" [disabled]="paginaActual() === totalPaginas()"
                      class="px-2 py-1 text-xs rounded hover:bg-gray-100 disabled:opacity-30">&rsaquo;</button>
              <button (click)="irAPagina(totalPaginas())" [disabled]="paginaActual() === totalPaginas()"
                      class="px-2 py-1 text-xs rounded hover:bg-gray-100 disabled:opacity-30">&raquo;</button>
            </div>
          }
        </div>
      </div>

      <!-- Modal Detalle Alerta -->
      @if (alertaDetalle()) {
        <div class="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4">
          <div class="bg-white rounded-2xl shadow-2xl w-full max-w-2xl max-h-[90vh] flex flex-col">

            <!-- Header -->
            <div class="flex items-center justify-between p-5 border-b border-gray-100 flex-shrink-0">
              <div>
                <h3 class="font-bold text-gray-800">Detalle de Alerta — {{ alertaDetalle()!.codigo }}</h3>
                <p class="text-xs text-gray-500">{{ alertaDetalle()!.zona }} · {{ alertaDetalle()!.fecha }}</p>
              </div>
              <button (click)="cerrarModales()" class="text-gray-400 hover:text-gray-600 text-lg leading-none">✕</button>
            </div>

            <!-- Cuerpo scrollable -->
            <div class="p-5 space-y-5 overflow-y-auto flex-1">

              <!-- Coordenadas y área -->
              <div class="grid grid-cols-2 gap-3">
                <div class="bg-gray-50 rounded-xl p-3">
                  <p class="text-xs text-gray-400 uppercase font-semibold mb-1">Coordenadas GPS</p>
                  <p class="font-mono text-sm text-gray-700">{{ alertaDetalle()!.coordenadas }}</p>
                </div>
                <div class="bg-gray-50 rounded-xl p-3">
                  <p class="text-xs text-gray-400 uppercase font-semibold mb-1">Área Afectada</p>
                  <p class="text-sm font-bold text-red-600">{{ alertaDetalle()!.area_ha }} Ha</p>
                </div>
              </div>

              <!-- Metadatos de IA -->
              <div>
                <p class="text-xs font-semibold text-gray-500 uppercase mb-2">Análisis de Detección</p>
                <div class="grid grid-cols-2 gap-3">
                  <div class="bg-gray-50 rounded-xl p-3">
                    <p class="text-xs text-gray-400 mb-1">Tipo de detección</p>
                    <span [class]="tipoCasoClase(alertaDetalle()!.tipo_caso)">
                      {{ tipoCasoLabel(alertaDetalle()!.tipo_caso) }}
                    </span>
                  </div>
                  <div class="bg-gray-50 rounded-xl p-3">
                    <p class="text-xs text-gray-400 mb-1">Nivel de confianza</p>
                    <div class="flex items-center gap-2 mt-1">
                      <div class="flex-1 bg-gray-200 rounded-full h-2">
                        <div class="h-2 rounded-full transition-all"
                             [class]="confianzaBarraClase(alertaDetalle()!.score_confianza)"
                             [style.width.%]="(alertaDetalle()!.score_confianza ?? 0) * 100"></div>
                      </div>
                      <span class="text-sm font-bold text-gray-700">{{ ((alertaDetalle()!.score_confianza ?? 0) * 100).toFixed(0) }}%</span>
                    </div>
                  </div>
                  <div class="bg-gray-50 rounded-xl p-3">
                    <p class="text-xs text-gray-400 mb-1">Estado ecológico</p>
                    <span [class]="estadoEcologicoClase(alertaDetalle()!.estado_ecologico)">
                      {{ estadoEcologicoLabel(alertaDetalle()!.estado_ecologico) }}
                    </span>
                  </div>
                  <div class="bg-gray-50 rounded-xl p-3">
                    <p class="text-xs text-gray-400 mb-1">Ciclos sin actividad</p>
                    <p class="text-sm font-bold text-gray-700 mt-0.5">
                      {{ alertaDetalle()!.ciclos_limpios_consecutivos ?? 0 }}
                      <span class="text-xs font-normal text-gray-500">quincenas</span>
                    </p>
                  </div>
                  <!-- Fase G6: historial de deduplicacion entre pasadas -->
                  <div class="bg-gray-50 rounded-xl p-3 col-span-2">
                    <p class="text-xs text-gray-400 mb-1">Historial entre pasadas</p>
                    <p class="text-xs text-gray-600 leading-relaxed">
                      Detectada por primera vez el
                      <span class="font-semibold">{{ alertaDetalle()!.fecha_nacimiento ?? '—' }}</span>
                      · última detección
                      <span class="font-semibold">{{ alertaDetalle()!.fecha_ultima_deteccion ?? '—' }}</span>
                      · presente en
                      <span class="font-semibold">{{ alertaDetalle()!.veces_detectado ?? 1 }}</span>
                      pasada(s)
                      @if (alertaDetalle()!.es_nueva) {
                        <span class="badge-nueva ml-1">Nueva en esta pasada</span>
                      }
                    </p>
                  </div>
                </div>
              </div>

              <!-- Estado actual -->
              <div class="flex items-center gap-3">
                <p class="text-xs text-gray-500 uppercase font-semibold">Estado del caso:</p>
                <span [class]="badgeClase(alertaDetalle()!.estado)">{{ alertaDetalle()!.estado }}</span>
              </div>

              <!-- Visualizacion del Parche (generada por el backend desde el .out de SageMaker) -->
              <div>
                <p class="text-xs font-semibold text-gray-500 uppercase mb-2">Visualización del Parche</p>
                @if (urlImagenSatelital() || urlCapaIa()) {
                  <div class="grid grid-cols-2 gap-3">
                    @if (urlImagenSatelital()) {
                      <div class="border border-gray-200 rounded-lg overflow-hidden">
                        <p class="text-xs text-gray-500 bg-gray-50 px-2 py-1 text-center">Imagen Satelital (RGB)</p>
                        <img [src]="urlImagenSatelital()!" alt="RGB del parche"
                             class="w-full h-40 object-cover bg-black" loading="lazy">
                      </div>
                    }
                    @if (urlCapaIa()) {
                      <div class="border border-gray-200 rounded-lg overflow-hidden">
                        <p class="text-xs text-gray-500 bg-gray-50 px-2 py-1 text-center">Capa IA (Probabilidad)</p>
                        <img [src]="urlCapaIa()!" alt="Capa de IA"
                             class="w-full h-40 object-cover bg-black" loading="lazy">
                      </div>
                    }
                  </div>
                } @else {
                  <p class="text-sm text-gray-400 italic">
                    Visualización no disponible. El backend aún no generó los PNGs para este caso
                    (ocurre automáticamente al recibir el resultado de SageMaker).
                  </p>
                }
              </div>

              <!-- Historial SMS -->
              <div>
                <p class="text-xs font-semibold text-gray-500 uppercase mb-2">Historial de Notificaciones SMS</p>
                @if ((alertaDetalle()!.sms_historial ?? []).length === 0) {
                  <p class="text-sm text-gray-400 italic">Sin notificaciones enviadas para este caso.</p>
                } @else {
                  <div class="space-y-2">
                    @for (sms of alertaDetalle()!.sms_historial!; track sms.id) {
                      <div class="flex items-center justify-between bg-gray-50 rounded-lg px-3 py-2 text-sm">
                        <div>
                          <p class="font-medium text-gray-800">{{ sms.tecnico_nombre }}</p>
                          <p class="text-xs text-gray-400">
                            {{ sms.tecnico_telefono }} ·
                            {{ sms.fecha_envio ? (sms.fecha_envio | date:'dd/MM/yyyy HH:mm') : '—' }}
                          </p>
                        </div>
                        <span [class]="smsEstadoClase(sms.estado)">{{ sms.estado }}</span>
                      </div>
                    }
                  </div>
                }
              </div>

              <!-- Evidencia fotográfica -->
              <div>
                <p class="text-xs font-semibold text-gray-500 uppercase mb-2">Evidencia Fotográfica de Campo</p>
                @if (evidenciaUrl()) {
                  <div class="mb-2">
                    <img [src]="evidenciaUrl()!" alt="Evidencia" class="w-full rounded-lg max-h-40 object-cover border border-gray-200">
                    <p class="text-xs text-green-600 mt-1 flex items-center gap-1">
                      <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/>
                      </svg>
                      Evidencia guardada
                    </p>
                  </div>
                }
                <label class="flex flex-col items-center gap-2 border-2 border-dashed border-gray-200
                              rounded-lg p-4 text-center text-gray-400 text-sm cursor-pointer
                              hover:border-primary hover:bg-green-50 transition-colors"
                       [class.opacity-60]="subiendoEvidencia()">
                  <svg class="w-6 h-6 text-gray-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                      d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z"/>
                  </svg>
                  @if (subiendoEvidencia()) {
                    <span class="text-primary text-xs">Subiendo...</span>
                  } @else {
                    <span>{{ evidenciaUrl() ? 'Reemplazar foto' : 'Arrastra foto o haz clic' }}</span>
                    <span class="text-xs">(JPG, PNG, máx 5 MB)</span>
                  }
                  <input #inputEvidencia type="file" accept="image/jpeg,image/png"
                         class="hidden" (change)="subirEvidencia($event)">
                </label>
              </div>

              <!-- Notas técnicas -->
              <div>
                <p class="text-xs font-semibold text-gray-500 uppercase mb-2">Notas / Observaciones Técnicas</p>
                <textarea [(ngModel)]="notasEdicion"
                          placeholder="Informe observaciones técnicas, condiciones de campo, especies afectadas, causas identificadas..."
                          class="input-field h-24 resize-none text-sm"></textarea>
              </div>
            </div>

            <!-- Footer -->
            <div class="p-5 border-t border-gray-100 flex items-center justify-between flex-shrink-0">
              <div class="flex gap-2">
                <button (click)="descargarPdf()" [disabled]="descargandoPdf()"
                        class="btn-outline text-sm flex items-center gap-1">
                  <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                      d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/>
                  </svg>
                  {{ descargandoPdf() ? 'Generando...' : 'Descargar PDF' }}
                </button>
                <button (click)="exportarGeoJson()" class="btn-outline text-sm">Exportar GeoJSON</button>
              </div>
              <button (click)="guardarDetalle()" class="btn-primary text-sm">Guardar Cambios</button>
            </div>
          </div>
        </div>
      }

      <!-- Modal Notificar SMS -->
      @if (alertaNotificar()) {
        <div class="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4">
          <div class="bg-white rounded-2xl shadow-2xl w-full max-w-md">
            <div class="flex items-center justify-between p-5 border-b border-gray-100">
              <div>
                <h3 class="font-bold text-gray-800">Notificar por SMS</h3>
                <p class="text-xs text-gray-500">Selecciona los destinatarios</p>
              </div>
              <button (click)="cerrarModales()" class="text-gray-400 hover:text-gray-600">✕</button>
            </div>
            <div class="p-5 space-y-2 max-h-60 overflow-y-auto">
              @for (tecnico of tecnicos(); track tecnico.id) {
                <label class="flex items-center gap-3 p-3 rounded-lg hover:bg-gray-50 cursor-pointer border border-gray-100">
                  <input type="checkbox" [checked]="tecnicosSeleccionados.has(tecnico.id)"
                         (change)="toggleTecnico(tecnico.id)" class="w-4 h-4 accent-primary">
                  <div>
                    <p class="text-sm font-medium text-gray-800">{{ tecnico.nombre }}</p>
                    <p class="text-xs text-gray-500">{{ tecnico.telefono }} · {{ tecnico.sector?.nombre }}</p>
                  </div>
                </label>
              }
            </div>
            <div class="p-5 border-t border-gray-100">
              <div class="bg-gray-800 text-green-400 font-mono text-xs rounded-lg p-3 mb-4">
                🚨 ALERTA DEFORESTACIÓN - ApuGuard<br>
                Zona: {{ alertaNotificar()?.zona }}<br>
                Coord: {{ alertaNotificar()?.coordenadas }}<br>
                Área: {{ alertaNotificar()?.area_ha }} Ha
              </div>
              <div class="flex gap-2 justify-end">
                <button (click)="cerrarModales()" class="btn-outline text-sm">Cancelar</button>
                <button (click)="enviarSms()" [disabled]="enviandoSms()"
                        class="btn-danger text-sm">
                  {{ enviandoSms() ? 'Enviando...' : '🔔 Enviar Alerta SMS' }}
                </button>
              </div>
            </div>
          </div>
        </div>
      }
    </div>
  `
})
export class AlertasComponent implements OnInit {
  private _alertas  = signal<Alerta[]>([]);
  private _tecnicos = signal<TecnicoCampo[]>([]);
  private _alertaDetalle   = signal<Alerta | null>(null);
  private _alertaNotificar = signal<Alerta | null>(null);
  private _enviandoSms = signal(false);
  private _totalAlertas   = signal(0);
  private _cargandoPagina = signal(false);
  private _pagina  = 1;

  alertas          = this._alertas.asReadonly();
  tecnicos         = this._tecnicos.asReadonly();
  alertaDetalle    = this._alertaDetalle.asReadonly();
  alertaNotificar  = this._alertaNotificar.asReadonly();
  enviandoSms      = this._enviandoSms.asReadonly();
  isAdmin          = this.auth.isAdmin;
  totalAlertas     = this._totalAlertas.asReadonly();
  cargandoPagina   = this._cargandoPagina.asReadonly();
  paginaActual     = () => this._pagina;
  totalPaginas     = computed(() => Math.ceil(this._totalAlertas() / 100));

  tecnicosSeleccionados = new Set<number>();
  notasEdicion = '';
  evidenciaUrl      = signal<string | null>(null);
  subiendoEvidencia = signal(false);
  descargandoPdf    = signal(false);
  private _url_imagen_satelital = signal<string | null>(null);
  private _url_capa_ia          = signal<string | null>(null);
  urlImagenSatelital = this._url_imagen_satelital.asReadonly();
  urlCapaIa          = this._url_capa_ia.asReadonly();
  filtroDesde = '';
  filtroHasta = '';
  filtroZona  = '';
  /** Fase G6: 'todas' = historial completo, 'nuevas' = solo nacidas en la ultima pasada */
  readonly modo = signal<'todas' | 'nuevas'>('todas');

  alertasPendientes = () => this._alertas().filter(a => a.estado === 'Pendiente').length;

  setModo(m: 'todas' | 'nuevas'): void {
    if (this.modo() === m) return;
    this.modo.set(m);
    this.cargarAlertas(1);
  }

  constructor(private api: ApiService, private auth: AuthService) {}

  ngOnInit(): void {
    this.cargarAlertas();
    this.api.getTecnicos().subscribe({ next: t => this._tecnicos.set(t), error: () => {} });
  }

  cargarAlertas(pagina?: number): void {
    if (pagina !== undefined) this._pagina = pagina;
    const params: Record<string, string> = {};
    if (this.modo() === 'nuevas') params['solo_nuevas'] = 'true';
    if (this.filtroDesde) params['fecha__gte'] = this.filtroDesde;
    if (this.filtroHasta) params['fecha__lte'] = this.filtroHasta;
    if (this.filtroZona)  params['zona__icontains'] = this.filtroZona;

    this._cargandoPagina.set(true);
    this.api.getAlertas(params, this._pagina).subscribe({
      next: (r) => {
        this._alertas.set(r.results);
        this._totalAlertas.set(r.count);
        this._cargandoPagina.set(false);
      },
      error: () => { this._alertas.set([]); this._cargandoPagina.set(false); }
    });
  }

  badgeClase(estado: string): string {
    const map: Record<string, string> = {
      'Pendiente':         'badge-pendiente',
      'Validada en campo': 'badge-validado',
      'Descartada':        'badge-advertencia',
    };
    return map[estado] ?? 'badge-completado';
  }

  tipoCasoLabel(tipo?: string): string {
    if (tipo === 'DETECCION')     return 'Detección';
    if (tipo === 'INCERTIDUMBRE') return 'Incertidumbre';
    return '—';
  }

  tipoCasoClase(tipo?: string): string {
    if (tipo === 'DETECCION')     return 'badge-pendiente';
    if (tipo === 'INCERTIDUMBRE') return 'badge-advertencia';
    return 'text-gray-400 text-xs';
  }

  confianzaBarraClase(score?: number): string {
    const v = score ?? 0;
    if (v >= 0.8) return 'bg-green-500';
    if (v >= 0.5) return 'bg-yellow-400';
    return 'bg-red-400';
  }

  estadoEcologicoLabel(estado?: string): string {
    if (estado === 'PERTURBADO')  return 'Perturbado';
    if (estado === 'RECUPERANDO') return 'Recuperándose';
    if (estado === 'RECUPERADO')  return 'Recuperado';
    return '—';
  }

  estadoEcologicoClase(estado?: string): string {
    if (estado === 'PERTURBADO')  return 'badge-pendiente';
    if (estado === 'RECUPERANDO') return 'badge-advertencia';
    if (estado === 'RECUPERADO')  return 'badge-validado';
    return 'text-gray-400 text-xs';
  }

  smsEstadoClase(estado: string): string {
    if (estado === 'ENVIADO')   return 'badge-validado';
    if (estado === 'FALLIDO')   return 'badge-pendiente';
    return 'badge-advertencia';
  }

  abrirDetalle(alerta: Alerta): void {
    // Cargar detalle completo desde la API para obtener SMS historial y campos de IA
    this.api.getAuditoria(alerta.id).subscribe({
      next: (detalle) => {
        // Desanidar GeoJSON Feature: {properties: {url_imagen_satelital, ...}}
        const props = (detalle as any).properties ?? detalle;
        const alertaCompleta: Alerta = {
          ...alerta,
          ...props,
          codigo:      alerta.codigo,
          zona:        alerta.zona,
          coordenadas: alerta.coordenadas,
          area_ha:     alerta.area_ha,
          severidad:   alerta.severidad,
          estado:      alerta.estado,
        };
        this._alertaDetalle.set(alertaCompleta);
        this.notasEdicion = alertaCompleta.notas_tecnico ?? alertaCompleta.notas ?? '';
        this.evidenciaUrl.set(alertaCompleta.evidencia_url ?? null);
        this._url_imagen_satelital.set(props.url_imagen_satelital ?? null);
        this._url_capa_ia.set(props.url_capa_ia ?? null);
      },
      error: () => {
        // Fallback: usar datos del listado
        this._alertaDetalle.set(alerta);
        this.notasEdicion = alerta.notas ?? '';
        this.evidenciaUrl.set(alerta.evidencia_url ?? null);
        this._url_imagen_satelital.set(alerta.url_imagen_satelital ?? null);
        this._url_capa_ia.set(alerta.url_capa_ia ?? null);
      }
    });
  }

  abrirNotificar(alerta: Alerta): void {
    this._alertaNotificar.set(alerta);
    this.tecnicosSeleccionados.clear();
  }

  cerrarModales(): void {
    this._alertaDetalle.set(null);
    this._alertaNotificar.set(null);
    this.evidenciaUrl.set(null);
    this._url_imagen_satelital.set(null);
    this._url_capa_ia.set(null);
  }

  toggleEstado(alerta: Alerta): void {
    const nuevoEstado = alerta.estado === 'Pendiente' ? 'Validada en campo' : 'Pendiente';
    this.api.patchAlerta(alerta.id, { estado: nuevoEstado as any }).subscribe({
      next: () => this.cargarAlertas(),
      error: () => { alerta.estado = nuevoEstado as any; }
    });
  }

  irAPagina(n: number): void {
    if (n < 1 || n > this.totalPaginas()) return;
    this.cargarAlertas(n);
  }

  guardarDetalle(): void {
    const a = this._alertaDetalle();
    if (!a) return;
    this.api.patchAlerta(a.id, { notas_tecnico: this.notasEdicion } as any).subscribe({
      next: () => { this.cerrarModales(); this.cargarAlertas(); }
    });
  }

  descargarPdf(): void {
    const a = this._alertaDetalle();
    if (!a) return;
    this.descargandoPdf.set(true);
    this.api.descargarPdf(a.id).subscribe({
      next: (blob) => {
        const url  = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href     = url;
        link.download = `apuguard_${a.codigo}.pdf`;
        link.click();
        URL.revokeObjectURL(url);
        this.descargandoPdf.set(false);
      },
      error: () => this.descargandoPdf.set(false)
    });
  }

  exportarGeoJson(): void {
    const a = this._alertaDetalle();
    if (!a) return;
    this.api.exportarGeoJson(a.id).subscribe({
      next: (blob) => {
        const url  = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href     = url;
        link.download = `${a.codigo}.geojson`;
        link.click();
        URL.revokeObjectURL(url);
      }
    });
  }

  toggleTecnico(id: number): void {
    this.tecnicosSeleccionados.has(id)
      ? this.tecnicosSeleccionados.delete(id)
      : this.tecnicosSeleccionados.add(id);
  }

  subirEvidencia(event: Event): void {
    const a = this._alertaDetalle();
    if (!a) return;
    const file = (event.target as HTMLInputElement).files?.[0];
    if (!file || file.size > 5 * 1024 * 1024) {
      alert('El archivo debe ser JPG o PNG y pesar menos de 5 MB.');
      return;
    }
    this.subiendoEvidencia.set(true);
    this.api.solicitarUrlEvidencia(a.id, file.name, file.type).subscribe({
      next: ({ upload_url, s3_key }) => {
        fetch(upload_url, {
          method:  'PUT',
          body:    file,
          headers: { 'Content-Type': file.type },
        }).then(res => {
          if (!res.ok) throw new Error('Upload S3 fallido');
          return this.api.confirmarEvidencia(a.id, s3_key).toPromise();
        }).then(() => {
          const reader = new FileReader();
          reader.onload = e => this.evidenciaUrl.set(e.target?.result as string);
          reader.readAsDataURL(file);
          this.subiendoEvidencia.set(false);
        }).catch(() => {
          this.subiendoEvidencia.set(false);
          alert('Error al subir la imagen. Intenta de nuevo.');
        });
      },
      error: () => {
        this.subiendoEvidencia.set(false);
        alert('Error al solicitar URL de subida.');
      }
    });
  }

  enviarSms(): void {
    const a = this._alertaNotificar();
    if (!a || this.tecnicosSeleccionados.size === 0) return;
    this._enviandoSms.set(true);
    this.api.notificarSms(a.id, [...this.tecnicosSeleccionados]).subscribe({
      next: () => { this._enviandoSms.set(false); this.cerrarModales(); },
      error: () => this._enviandoSms.set(false)
    });
  }
}
