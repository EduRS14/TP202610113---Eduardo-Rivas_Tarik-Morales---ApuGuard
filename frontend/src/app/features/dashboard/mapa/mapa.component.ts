import {
  Component, OnDestroy, AfterViewInit,
  ElementRef, ViewChild, Output, EventEmitter,
  Input, signal, inject
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import * as L from 'leaflet';
import { ApiService } from '../../../core/services/api.service';
import { Alerta, Sector } from '../../../core/models/alerta.model';
import { AuthService } from '../../../core/services/auth.service';

// Corrección de assets para marcadores Leaflet
delete (L.Icon.Default.prototype as any)._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png',
  iconUrl:       'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png',
  shadowUrl:     'https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png',
});

function crearIcono(color: string, size: number): L.DivIcon {
  return L.divIcon({
    className: 'apuguard-marker',
    html: `<span style="display:block;width:${size}px;height:${size}px;background:${color};border:2px solid #fff;border-radius:50%;box-shadow:0 2px 5px rgba(0,0,0,0.4)"></span>`,
    iconSize:   [size, size],
    iconAnchor: [size / 2, size / 2],
  });
}

const iconoCritico    = crearIcono('#ef4444', 14);
const iconoAdvertencia = crearIcono('#f59e0b', 14);
const iconoProtegido  = crearIcono('#10b981', 12);

export interface AlertaSeleccionadaInfo {
  id: number;
  codigo: string;
  lat: string;
  lon: string;
  area_ha: number;
  zona: string;
}

@Component({
  selector: 'app-mapa',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <div class="card bg-white p-0 overflow-hidden rounded-xl shadow-sm border border-gray-100">

      <!-- Cabecera del Mapa -->
      <div class="flex items-center justify-between px-4 py-3 border-b border-gray-100 bg-gray-50/50">
        <div class="flex items-center gap-2">
          <svg class="w-4 h-4 text-emerald-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                  d="M9 20l-5.447-2.724A1 1 0 013 16.382V5.618a1 1 0 011.447-.894L9 7m0 13l6-3m-6 3V7m6 10l4.553 2.276A1 1 0 0021 18.382V7.618a1 1 0 00-.553-.894L15 4m0 13V4m0 0L9 7"/>
          </svg>
          <span class="font-semibold text-gray-800 text-sm">Visualización Cartográfica (Tambopata)</span>
        </div>

        <div class="flex items-center gap-2">
          @if (isAdmin()) {
            <button (click)="onEjecutarDeteccion.emit()"
                    [disabled]="deteccionEnCurso"
                    [attr.title]="deteccionEnCurso ? 'Ya hay un pipeline en ejecución' : 'Lanzar el pipeline de detección (solo Admin)'"
                    class="bg-emerald-600 hover:bg-emerald-700 text-white font-medium text-xs px-3 py-1.5 rounded-lg transition-colors flex items-center gap-1.5 shadow-sm disabled:opacity-60 disabled:cursor-not-allowed">
              <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                      d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707M12 9v6"/>
              </svg>
              {{ deteccionEnCurso ? 'Ejecutando…' : 'Ejecutar IA' }}
            </button>
          }
          <button (click)="togglePantallaCompleta()"
                  title="Cambiar vista"
                  class="p-1.5 rounded-lg hover:bg-gray-200/60 text-gray-500 transition-colors">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                    d="M4 8V4m0 0h4M4 4l5 5m11-1V4m0 0h-4m4 0l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5l-5-5m5 5v-4m0 4h-4"/>
            </svg>
          </button>
        </div>
      </div>

      <!-- Contenedor Mapa -->
      <div class="relative" [style.height]="alturaContenedor">

        <!-- DIV Canvas Leaflet -->
        <div #mapaContainer class="w-full h-full z-0"></div>

        <!-- Panel Control de Capas -->
        <div class="absolute top-3 right-3 z-[1000] bg-white rounded-xl shadow-lg border border-gray-100 w-56 text-sm overflow-hidden">
          <button (click)="panelAbierto.set(!panelAbierto())"
                  class="w-full flex items-center justify-between px-3 py-2.5 font-semibold text-gray-700 hover:bg-gray-50 transition-colors">
            <div class="flex items-center gap-2">
              <svg class="w-4 h-4 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                      d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10"/>
              </svg>
              Control de Capas
            </div>
            <svg class="w-4 h-4 text-gray-400 transition-transform duration-200"
                 [class.rotate-180]="panelAbierto()"
                 fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
            </svg>
          </button>

          @if (panelAbierto()) {
            <div class="border-t border-gray-100 px-3 py-2.5 space-y-2.5">
              <!-- Toggle Alertas -->
              <label class="flex items-center justify-between cursor-pointer">
                <span class="text-gray-600 text-xs font-medium">Marcadores de Alerta</span>
                <input type="checkbox" class="rounded text-emerald-600 focus:ring-emerald-500 h-4 w-4"
                       [(ngModel)]="mostrarMascara" (change)="toggleCapaAlertas()">
              </label>

              <!-- Toggle Sectores GeoJSON -->
              <label class="flex items-center justify-between cursor-pointer">
                <span class="text-gray-600 text-xs font-medium">Límites de Sectores</span>
                <input type="checkbox" class="rounded text-emerald-600 focus:ring-emerald-500 h-4 w-4"
                       [(ngModel)]="mostrarSectores" (change)="toggleCapaSectores()">
              </label>

              <!-- Filtro Sector -->
              <div class="pt-2 border-t border-gray-100">
                <p class="text-[10px] font-semibold text-gray-400 uppercase tracking-wider mb-1">Filtrar por Sector</p>
                <select [(ngModel)]="sectorFiltro" (change)="filtrarPorSector()"
                        class="w-full text-xs border border-gray-200 rounded-lg px-2 py-1.5 bg-gray-50 focus:bg-white focus:outline-none focus:ring-1 focus:ring-emerald-500">
                  <option value="">Todos los sectores</option>
                  @for (s of sectores(); track s.id) {
                    <option [value]="s.id">{{ s.nombre }}</option>
                  }
                </select>
              </div>
            </div>
          }
        </div>

        <!-- Popup / Card de Alerta Seleccionada -->
        @if (alertaSeleccionada()) {
          <div class="absolute bottom-4 left-1/2 -translate-x-1/2 z-[1000] bg-white rounded-xl shadow-2xl border border-gray-100 w-72 p-4 animate-in fade-in slide-in-from-bottom-2 duration-200">
            <div class="flex items-center justify-between mb-2 pb-2 border-b border-gray-100">
              <div class="flex items-center gap-1.5 text-sm font-bold text-gray-800">
                <span class="w-2.5 h-2.5 bg-red-500 rounded-full animate-pulse"></span>
                {{ alertaSeleccionada()!.codigo }}
              </div>
              <button (click)="alertaSeleccionada.set(null)"
                      class="text-gray-400 hover:text-gray-600 p-1 rounded-md text-sm font-bold">✕</button>
            </div>

            <div class="space-y-1 text-xs mb-3 text-gray-600">
              <div class="flex justify-between">
                <span>Coordenadas:</span>
                <span class="font-mono text-gray-800">{{ alertaSeleccionada()!.lat }}, {{ alertaSeleccionada()!.lon }}</span>
              </div>
              <div class="flex justify-between">
                <span>Superficie:</span>
                <span class="font-bold text-red-600">{{ alertaSeleccionada()!.area_ha }} Ha</span>
              </div>
              <div class="flex justify-between">
                <span>Sector/Zona:</span>
                <span class="text-gray-800 font-medium">{{ alertaSeleccionada()!.zona }}</span>
              </div>
            </div>

            <button (click)="irAAlerta(alertaSeleccionada()!.id)"
                    class="w-full bg-red-600 hover:bg-red-700 text-white text-xs font-semibold py-2 rounded-lg transition-colors flex items-center justify-center gap-1.5 shadow-sm">
              <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/>
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"/>
              </svg>
              Gestionar en Alertas
            </button>
          </div>
        }

        <!-- Leyenda -->
        <div class="absolute bottom-3 left-3 z-[1000] bg-white/90 backdrop-blur-sm rounded-lg shadow-md border border-gray-100 px-3 py-2 text-[11px]">
          <p class="font-semibold text-gray-700 mb-1">Leyenda</p>
          <div class="space-y-1">
            <div class="flex items-center gap-1.5">
              <span class="w-2.5 h-2.5 bg-red-500 rounded-full"></span>
              <span class="text-gray-600">Alerta Crítica</span>
            </div>
            <div class="flex items-center gap-1.5">
              <span class="w-2.5 h-2.5 bg-amber-500 rounded-full"></span>
              <span class="text-gray-600">Advertencia</span>
            </div>
            <div class="flex items-center gap-1.5">
              <span class="w-2.5 h-2.5 bg-emerald-500 rounded-full"></span>
              <span class="text-gray-600">Área Protegida</span>
            </div>
          </div>
        </div>

        <!-- Indicator Carga -->
        @if (cargando()) {
          <div class="absolute inset-0 z-[1001] bg-white/70 backdrop-blur-[1px] flex items-center justify-center">
            <div class="flex items-center gap-2 bg-white px-4 py-2 rounded-xl shadow-md border border-gray-100">
              <div class="w-4 h-4 border-2 border-emerald-600 border-t-transparent rounded-full animate-spin"></div>
              <span class="text-xs font-medium text-gray-700">Cargando capas...</span>
            </div>
          </div>
        }
      </div>
    </div>
  `
})
export class MapaComponent implements AfterViewInit, OnDestroy {
  @ViewChild('mapaContainer', { static: true }) mapaContainer!: ElementRef<HTMLDivElement>;
  @Output() onEjecutarDeteccion = new EventEmitter<void>();
  @Input()  deteccionEnCurso = false;

  private api = inject(ApiService);
  private auth = inject(AuthService);
  private router = inject(Router);

  private mapa!: L.Map;
  private capaAlertas = L.layerGroup();
  private capaSectores = L.layerGroup();
  private todosLosMarkers: Array<{ marker: L.Marker; alerta: Alerta }> = [];

  // Signals
  private _alertas  = signal<Alerta[]>([]);
  private _sectores = signal<Sector[]>([]);
  private _cargando = signal(true);

  alertaSeleccionada = signal<AlertaSeleccionadaInfo | null>(null);
  panelAbierto       = signal(true);

  alertas  = this._alertas.asReadonly();
  sectores = this._sectores.asReadonly();
  cargando = this._cargando.asReadonly();
  isAdmin  = this.auth.isAdmin;

  mostrarMascara   = true;
  mostrarSectores  = false;
  sectorFiltro     = '';
  pantallaCompleta = false;

  get alturaContenedor(): string {
    return this.pantallaCompleta ? '78vh' : '440px';
  }

  ngAfterViewInit(): void {
    this._inicializarMapa();
    this._cargarDatos();
  }

  ngOnDestroy(): void {
    if (this.mapa) {
      this.mapa.remove();
    }
  }

  private _inicializarMapa(): void {
    // Coordenadas centradas en la Reserva Nacional Tambopata (-13.1, -69.35)
    this.mapa = L.map(this.mapaContainer.nativeElement, {
      center: [-13.1, -69.35],
      zoom: 9,
      zoomControl: false,
    });

    L.control.zoom({ position: 'bottomright' }).addTo(this.mapa);

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '© OpenStreetMap',
      maxZoom: 18,
    }).addTo(this.mapa);

    this.capaAlertas.addTo(this.mapa);
    this.mapa.on('click', () => this.alertaSeleccionada.set(null));
  }

  private _cargarDatos(): void {
    this._cargando.set(true);

    this.api.getAlertas().subscribe({
      next: (r) => {
        const lista = r.results || [];
        this._alertas.set(lista);
        this._renderizarAlertas(lista);
        this._cargando.set(false);
      },
      error: (err) => {
        console.error('[MAPA] Error al obtener alertas:', err);
        this._alertas.set([]);
        this._cargando.set(false);
      }
    });

    this.api.getSectores().subscribe({
      next: (geojson: any) => {
        const features = geojson?.features ?? [];
        this._sectores.set(
          features.map((f: any) => ({
            id:     f.properties?.id ?? f.id,
            nombre: f.properties?.nombre ?? 'Sector',
            region: f.properties?.region ?? '',
          }))
        );
        this._renderizarSectores(geojson);
      },
      error: (err) => console.warn('[MAPA] Error al cargar sectores:', err)
    });
  }

  private _renderizarAlertas(alertas: Alerta[]): void {
    this.capaAlertas.clearLayers();
    this.todosLosMarkers = [];

    for (const alerta of alertas) {
      const coords = alerta.coordenadas?.split(',').map(Number);
      if (!coords || coords.length < 2 || isNaN(coords[0]) || isNaN(coords[1])) continue;

      const [lat, lon] = coords;
      const icono = alerta.severidad === 'Alta'
        ? iconoCritico
        : alerta.severidad === 'Media'
          ? iconoAdvertencia
          : iconoProtegido;

      const marker = L.marker([lat, lon], { icon: icono });

      marker.on('click', (e) => {
        L.DomEvent.stopPropagation(e);
        this.alertaSeleccionada.set({
          id:      alerta.id,
          codigo:  alerta.codigo,
          lat:     lat.toFixed(4),
          lon:     lon.toFixed(4),
          area_ha: alerta.area_ha,
          zona:    alerta.zona || 'Tambopata',
        });
      });

      this.capaAlertas.addLayer(marker);
      this.todosLosMarkers.push({ marker, alerta });
    }
  }

  private _renderizarSectores(geojsonData: any): void {
    this.capaSectores.clearLayers();
    if (!geojsonData?.features?.length) return;

    L.geoJSON(geojsonData, {
      style: {
        color:       '#059669',
        weight:      2,
        opacity:     0.8,
        fillColor:   '#10b981',
        fillOpacity: 0.12,
      },
      onEachFeature: (feature, layer) => {
        const nombre = feature.properties?.nombre ?? 'Sector';
        layer.bindTooltip(nombre, { permanent: false, direction: 'center', className: 'text-xs font-semibold' });
      }
    }).addTo(this.capaSectores);

    if (this.mostrarSectores) {
      this.capaSectores.addTo(this.mapa);
    }
  }

  toggleCapaAlertas(): void {
    if (this.mostrarMascara) {
      this.capaAlertas.addTo(this.mapa);
    } else {
      this.capaAlertas.remove();
    }
  }

  toggleCapaSectores(): void {
    if (this.mostrarSectores) {
      this.capaSectores.addTo(this.mapa);
    } else {
      this.capaSectores.remove();
    }
  }

  filtrarPorSector(): void {
    this.capaAlertas.clearLayers();
    const id = this.sectorFiltro ? Number(this.sectorFiltro) : null;

    for (const { marker, alerta } of this.todosLosMarkers) {
      if (!id || alerta.sector_id === id) {
        this.capaAlertas.addLayer(marker);
      }
    }
  }

  irAAlerta(id: number): void {
    this.alertaSeleccionada.set(null);
    this.router.navigate(['/alertas'], { queryParams: { id } });
  }

  togglePantallaCompleta(): void {
    this.pantallaCompleta = !this.pantallaCompleta;
    setTimeout(() => this.mapa?.invalidateSize(), 150);
  }
}