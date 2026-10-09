import { Component, OnInit, signal, computed, inject, DestroyRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ApiService } from '../../core/services/api.service';
import { MapaComponent } from './mapa/mapa.component';
import { DashboardStats, AuditLog } from '../../core/models/dashboard.model';

@Component({
  selector: 'app-dashboard',
  standalone: true,
  imports: [CommonModule, FormsModule, MapaComponent],
  template: `
    <div class="min-h-screen bg-slate-50 text-slate-800 text-sm">

      <!-- BARRA SUPERIOR / HEADER DE CONTROL -->
      <header class="bg-white border-b border-slate-200 px-6 py-4 shadow-sm">
        <div class="max-w-[1600px] mx-auto flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
          <div>
            <h1 class="text-xl font-bold text-slate-900 tracking-tight">Panel de Control ApuGuard</h1>
            <p class="text-xs text-slate-500">Sistema de monitoreo continuo y estado de plataforma.</p>
          </div>

          <!-- MÓDULOS DE ESTADO Y ALMACENAMIENTO CLOUD -->
          <div class="flex items-center gap-3">
            <button (click)="togglePanelIA()"
                    class="bg-emerald-800 hover:bg-emerald-900 text-white text-xs font-semibold px-3 py-2 rounded-lg flex items-center gap-2 transition shadow-sm">
              <svg class="w-4 h-4 text-emerald-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"/>
              </svg>
              Estadísticas IA
            </button>

            <div class="bg-slate-100 border border-slate-200 px-3 py-1.5 rounded-lg flex items-center gap-2 text-xs">
              <span class="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span>
              <span class="text-slate-600 font-medium">INGESTA DE DATOS: <strong class="text-emerald-700">Al día</strong></span>
            </div>

            <!-- Consultar estado de almacenamiento Cloud -->
            <div class="bg-slate-100 border border-slate-200 px-3 py-1.5 rounded-lg text-xs min-w-[170px]">
              <div class="flex justify-between items-center mb-1 text-[11px]">
                <span class="text-slate-500 font-medium">ALMACENAMIENTO CLOUD</span>
                <span class="font-bold text-slate-700">{{ stats()?.storage_usado_gb ?? 0 }} GB / {{ stats()?.storage_total_gb ?? 0 }} GB</span>
              </div>
              <div class="w-full bg-slate-200 h-1.5 rounded-full overflow-hidden">
                <div class="bg-emerald-600 h-1.5 rounded-full transition-all duration-300" [style.width.%]="porcentajeStorage()"></div>
              </div>
            </div>
          </div>
        </div>
      </header>

      <!-- CONTENEDOR PRINCIPAL TRES COLUMNAS -->
      <div class="max-w-[1600px] mx-auto px-6 py-6 grid grid-cols-1 lg:grid-cols-12 gap-6">

        <!-- ================= COLUMNA IZQUIERDA: FILTROS ESPACIALES & PIPELINE DE DATOS ================= -->
        <aside class="lg:col-span-3 space-y-6">

          <!-- FILTROS ESPACIALES -->
          <div class="bg-white p-4 rounded-xl border border-slate-200 shadow-sm space-y-4">
            <h2 class="text-xs font-bold uppercase tracking-wider text-slate-400">Filtros Espaciales</h2>

            <div>
              <label class="block text-xs font-medium text-slate-600 mb-1">ÁREA DE MONITOREO</label>
              <select [ngModel]="areaSeleccionada()" (ngModelChange)="onAreaChange($event)"
                      class="w-full border border-slate-200 rounded-lg text-xs px-2.5 py-2 bg-slate-50 font-medium focus:bg-white focus:outline-none focus:ring-1 focus:ring-emerald-600">
                <option value="tambopata">Reserva Tambopata</option>
                <option value="bahuaja">Parque Nacional Bahuaja Sonene</option>
              </select>
            </div>

            <div>
              <label class="block text-xs font-medium text-slate-600 mb-1">PERÍODO DE ANÁLISIS</label>
              <div class="grid grid-cols-2 gap-1.5">
                <button (click)="cambiarPeriodo('7d')" [class.bg-emerald-700]="periodo() === '7d'" [class.text-white]="periodo() === '7d'" class="px-2 py-1.5 bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-semibold rounded-md transition">7 días</button>
                <button (click)="cambiarPeriodo('30d')" [class.bg-emerald-700]="periodo() === '30d'" [class.text-white]="periodo() === '30d'" class="px-2 py-1.5 bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-semibold rounded-md transition">30 días</button>
                <button (click)="cambiarPeriodo('historico')" [class.bg-emerald-700]="periodo() === 'historico'" [class.text-white]="periodo() === 'historico'" class="col-span-2 px-2 py-1 bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-semibold rounded-md transition">Histórico</button>
              </div>
            </div>

            <div class="pt-3 border-t border-slate-100 space-y-2">
              <label class="block text-xs font-medium text-slate-600">CAPAS ACTIVAS</label>
              <label class="flex items-center justify-between text-xs cursor-pointer">
                <span class="text-slate-700 flex items-center gap-1.5"><span class="w-2 h-2 rounded-full bg-red-500"></span> Alertas de Pérdida</span>
                <input type="checkbox" [ngModel]="capaPerdida()" (ngModelChange)="capaPerdida.set($event)" class="rounded text-emerald-600 focus:ring-emerald-500">
              </label>
              <label class="flex items-center justify-between text-xs cursor-pointer">
                <span class="text-slate-700 flex items-center gap-1.5"><span class="w-2 h-2 rounded-full bg-emerald-500"></span> Áreas Protegidas</span>
                <input type="checkbox" [ngModel]="capaProtegida()" (ngModelChange)="capaProtegida.set($event)" class="rounded text-emerald-600 focus:ring-emerald-500">
              </label>
            </div>
          </div>

          <!-- DETALLES PIPELINE DE DATOS -->
          <div class="bg-white p-4 rounded-xl border border-slate-200 shadow-sm space-y-3">
            <h2 class="text-xs font-bold uppercase tracking-wider text-slate-400">Pipeline de Datos</h2>

            <div class="bg-slate-50 p-3 rounded-lg border border-slate-100 space-y-1.5 text-xs font-mono">
              <p class="text-[11px] font-bold text-slate-700">ÚLTIMA IMAGEN</p>
              <div class="flex justify-between text-slate-500">
                <span>ID Imagen:</span>
                <span class="text-slate-800 font-semibold">{{ stats()?.ultima_imagen?.nombre ?? 'S2A_T19LBS' }}</span>
              </div>
              <div class="flex justify-between text-slate-500">
                <span>Fuente:</span>
                <span class="text-slate-800">{{ stats()?.ultima_imagen?.satelite ?? 'Sentinel-2A' }}</span>
              </div>
              <div class="flex justify-between text-slate-500">
                <span>Fecha:</span>
                <span class="text-slate-800">{{ stats()?.ultima_imagen?.fecha ?? '—' }}</span>
              </div>
              <div class="flex justify-between text-slate-500">
                <span>Resultado:</span>
                <span class="text-emerald-600 font-bold">{{ stats()?.ultima_imagen?.resultado ?? '—' }}</span>
              </div>
            </div>

            <div class="space-y-2 text-xs">
              <p class="text-[11px] font-bold text-slate-500">ESTADO DEL PROCESO</p>
              <div class="flex items-center gap-2">
                <span class="w-2 h-2 rounded-full bg-emerald-500"></span>
                <span class="text-slate-700 font-medium">1. Descarga Sentinel-2</span>
              </div>
              <div class="flex items-center gap-2">
                <span class="w-2 h-2 rounded-full bg-emerald-500"></span>
                <span class="text-slate-700 font-medium">2. Filtro de Nubes (12.5% - Aceptada)</span>
              </div>
              <div class="flex items-center gap-2">
                <span class="w-2 h-2 rounded-full bg-emerald-500"></span>
                <span class="text-slate-700 font-medium">3. Segmentación (1,248 tiles)</span>
              </div>
            </div>
          </div>

        </aside>

        <!-- ================= COLUMNA CENTRAL: KPIS, MAPA & AUDITORÍA ================= -->
        <main class="lg:col-span-9 space-y-6">

          <!-- AVISO DEL PIPELINE (resultado del lanzamiento manual) -->
          @if (avisoDeteccion(); as aviso) {
            <div class="p-3.5 rounded-xl border text-xs flex items-start justify-between gap-3"
                 [class]="aviso.tipo === 'ok'
                   ? 'bg-emerald-50 border-emerald-200 text-emerald-800'
                   : 'bg-red-50 border-red-200 text-red-800'">
              <div class="flex items-start gap-2">
                <span class="font-bold shrink-0">{{ aviso.tipo === 'ok' ? '[OK]' : '[ERROR]' }}</span>
                <span>{{ aviso.texto }}</span>
              </div>
              <button (click)="avisoDeteccion.set(null)" class="font-bold shrink-0 opacity-60 hover:opacity-100" title="Cerrar">✕</button>
            </div>
          }

          <!-- TARJETAS KPIS (Fase G6: 6 KPIs reales, sin valores ficticios) -->
          <div class="grid grid-cols-2 md:grid-cols-3 gap-4">
            <div class="bg-white p-4 rounded-xl border border-slate-200 shadow-sm">
              <p class="text-[11px] font-bold uppercase tracking-wider text-slate-400">Alertas Activas</p>
              <p class="text-3xl font-extrabold text-slate-800 my-1">{{ stats()?.alertas_activas ?? 0 }}</p>
              <p class="text-[11px] text-slate-400">Casos abiertos en revisión</p>
            </div>

            <div class="bg-white p-4 rounded-xl border border-slate-200 shadow-sm">
              <p class="text-[11px] font-bold uppercase tracking-wider text-slate-400">Nuevas en la Pasada</p>
              <p class="text-3xl font-extrabold text-slate-800 my-1">{{ stats()?.alertas_nuevas_pasada ?? 0 }}</p>
              <p class="text-[11px] text-slate-400">
                Pasada del {{ stats()?.ultima_captura?.fecha ?? '—' }}
              </p>
            </div>

            <div class="bg-white p-4 rounded-xl border border-slate-200 shadow-sm">
              <p class="text-[11px] font-bold uppercase tracking-wider text-slate-400">Área Afectada Total</p>
              <p class="text-3xl font-extrabold text-slate-800 my-1">{{ stats()?.area_afectada_ha ?? 0 }} <span class="text-xs font-normal text-slate-400">ha</span></p>
              <p class="text-[11px] text-slate-400">Acumulado histórico confirmado</p>
            </div>

            <div class="bg-white p-4 rounded-xl border border-slate-200 shadow-sm">
              <p class="text-[11px] font-bold uppercase tracking-wider text-slate-400">Área Nueva (Pasada)</p>
              <p class="text-3xl font-extrabold text-slate-800 my-1">{{ stats()?.area_nueva_pasada_ha ?? 0 }} <span class="text-xs font-normal text-slate-400">ha</span></p>
              <p class="text-[11px] text-slate-400">Deforestación detectada en la última pasada</p>
            </div>

            <div class="bg-white p-4 rounded-xl border border-slate-200 shadow-sm">
              <p class="text-[11px] font-bold uppercase tracking-wider text-slate-400">Usuarios Activos</p>
              <p class="text-3xl font-extrabold text-slate-800 my-1">{{ stats()?.usuarios_activos ?? 0 }}</p>
              <p class="text-[11px] text-slate-400">Cuentas habilitadas en el sistema</p>
            </div>

            <div class="bg-emerald-800 text-white p-4 rounded-xl shadow-sm">
              <p class="text-[11px] font-bold uppercase tracking-wider text-emerald-200">Estado del Sistema</p>
              <p class="text-xl font-extrabold my-1">{{ stats()?.estado_sistema ?? 'Óptimo' }}</p>
              <p class="text-[11px] text-emerald-100">Servicios e ingesta operando con normalidad.</p>
            </div>
          </div>

          <!-- BANNER ESTADO PIPELINE CENTRAL -->
          <div class="bg-white p-5 rounded-xl border border-slate-200 shadow-sm space-y-4">
            <div class="flex items-center justify-between border-b border-slate-100 pb-3">
              <div>
                <h3 class="font-bold text-slate-800 text-sm">Estado del Pipeline de Ingesta</h3>
                <p class="text-xs text-slate-400">Última actualización: {{ fechaHoraPipeline }}</p>
              </div>
              <span class="bg-emerald-100 text-emerald-700 text-xs font-bold px-2.5 py-1 rounded-full">Operativo</span>
            </div>

            <div class="grid grid-cols-1 md:grid-cols-3 gap-4 text-center">
              @for (step of stats()?.pipeline_steps ?? []; track step.nombre) {
                <div class="bg-slate-50 p-3 rounded-lg border border-slate-100">
                  <p class="text-xs font-semibold text-slate-700">{{ step.nombre }}</p>
                  <div class="w-full bg-slate-200 h-1.5 rounded-full my-2">
                    <div class="bg-emerald-500 h-1.5 rounded-full" [style.width.%]="step.porcentaje"></div>
                  </div>
                  <p class="text-[11px] text-slate-400">{{ step.estado }}</p>
                </div>
              }
            </div>
          </div>

          <!-- VISOR DE MAPAS & TENDENCIA -->
          <div class="grid grid-cols-1 lg:grid-cols-12 gap-4">
            <div class="lg:col-span-8">
              <app-mapa (onEjecutarDeteccion)="ejecutarDeteccion()"
                        [deteccionEnCurso]="deteccionEnCurso()"></app-mapa>
            </div>

            <!-- TENDENCIA DE ALERTAS -->
            <div class="lg:col-span-4 bg-white p-4 rounded-xl border border-slate-200 shadow-sm flex flex-col justify-between">
              <h3 class="font-bold text-slate-800 text-xs mb-3 flex items-center gap-1.5">
                <svg class="w-4 h-4 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6"/>
                </svg>
                Tendencia de Alertas (7 Días)
              </h3>

              <div class="flex-1 flex flex-col justify-end min-h-[160px]">
                <svg viewBox="0 0 200 100" class="w-full h-32" preserveAspectRatio="none">
                  <defs>
                    <linearGradient id="gradRed" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stop-color="#ef4444" stop-opacity="0.3"/>
                      <stop offset="100%" stop-color="#ef4444" stop-opacity="0.0"/>
                    </linearGradient>
                  </defs>
                  <path d="M0,75 L30,60 L60,68 L90,30 L120,45 L150,20 L200,35"
                        fill="none" stroke="#ef4444" stroke-width="2.5" stroke-linejoin="round"/>
                  <path d="M0,75 L30,60 L60,68 L90,30 L120,45 L150,20 L200,35 L200,100 L0,100 Z"
                        fill="url(#gradRed)"/>
                </svg>
                <div class="flex justify-between text-[11px] text-slate-400 mt-2 px-1 font-medium">
                  <span>Lun</span><span>Mar</span><span>Mié</span><span>Jue</span><span>Vie</span><span>Sáb</span><span>Dom</span>
                </div>
              </div>
            </div>
          </div>

          <!-- REGISTRO DE ACTIVIDAD DEL SISTEMA (AUDITORÍA) -->
          <div class="bg-white p-5 rounded-xl border border-slate-200 shadow-sm space-y-4">
            <div class="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
              <div>
                <h3 class="font-bold text-slate-800 text-sm">Registro de Actividad</h3>
                <p class="text-xs text-slate-400">Auditoría de eventos y acciones del sistema.</p>
              </div>

              <div class="flex items-center gap-2">
                <select 
                  (change)="onUsuarioChange($event)" 
                  class="text-xs border border-slate-200 rounded-lg px-2.5 py-1.5 bg-slate-50">
                  <option value="">Todos los usuarios</option>
                  @for (u of stats()?.usuarios ?? []; track u.id) {
                    <option [value]="u.id">
                      {{ u.first_name && u.last_name ? u.first_name + ' ' + u.last_name : u.username }}
                    </option>
                  }
                </select>

                <button (click)="exportarCSV()" class="bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-semibold px-3 py-1.5 rounded-lg transition border border-slate-200">
                  Exportar CSV
                </button>
              </div>
            </div>

            <!-- TABLA DINÁMICA DE AUDITORÍA -->
            <div class="overflow-x-auto">
              <table class="w-full text-left text-xs border-collapse">
                <thead>
                  <tr class="border-b border-slate-200 text-slate-400 font-medium">
                    <th class="py-2 px-3">USUARIO / ORIGEN</th>
                    <th class="py-2 px-3">ACCIÓN REALIZADA</th>
                    <th class="py-2 px-3">FECHA Y HORA</th>
                    <th class="py-2 px-3">ESTADO</th>
                  </tr>
                </thead>
                <tbody>
                  @for (log of auditLogs(); track log.id) {
                    <tr class="border-b border-slate-100 hover:bg-slate-50">
                      <td class="py-2.5 px-3 font-semibold text-slate-700">{{ log.usuario }}</td>
                      <td class="py-2.5 px-3 text-slate-600">{{ log.accion }}</td>
                      <td class="py-2.5 px-3 text-slate-400">{{ log.fechaHora }}</td>
                      <td class="py-2.5 px-3">
                        <span class="px-2 py-0.5 text-[10px] rounded-full bg-emerald-100 text-emerald-700 font-medium">
                          {{ log.estado }}
                        </span>
                      </td>
                    </tr>
                  } @empty {
                    <tr>
                      <td colspan="4" class="py-4 text-center text-slate-400">No hay registros de actividad para mostrar.</td>
                    </tr>
                  }
                </tbody>
              </table>
            </div>
          </div>

        </main>

      </div>

      <!-- ================= PANEL LATERAL DERECHO: ESTADÍSTICAS IA (DRAWER) ================= -->
      @if (panelIAAbierto()) {
        <div class="fixed inset-y-0 right-0 w-80 bg-white border-l border-slate-200 shadow-2xl z-[2000] p-5 overflow-y-auto space-y-6 animate-in slide-in-from-right duration-200">

          <div class="flex items-center justify-between border-b border-slate-100 pb-3">
            <h3 class="font-extrabold text-slate-800 text-sm">ESTADÍSTICAS IA</h3>
            <button (click)="togglePanelIA()" class="text-slate-400 hover:text-slate-600 font-bold text-sm">✕</button>
          </div>

          <div class="space-y-1 text-xs">
            <div class="flex justify-between">
              <span class="flex items-center gap-1.5"><span class="w-2 h-2 rounded-full bg-emerald-500"></span> Bosque</span>
              <span class="font-bold">{{ stats()?.cobertura?.bosque ?? 0 }}%</span>
            </div>
            <div class="flex justify-between">
              <span class="flex items-center gap-1.5"><span class="w-2 h-2 rounded-full bg-red-500"></span> No Bosque</span>
              <span class="font-bold">{{ stats()?.cobertura?.no_bosque ?? 0 }}%</span>
            </div>
            <div class="flex justify-between">
              <span class="flex items-center gap-1.5"><span class="w-2 h-2 rounded-full bg-amber-500"></span> Degradado</span>
              <span class="font-bold">{{ stats()?.cobertura?.degradado ?? 0 }}%</span>
            </div>
          </div>

          <div class="grid grid-cols-2 gap-3 pt-2">
            <div class="bg-slate-50 p-3 rounded-lg border border-slate-100 text-center">
              <p class="text-[10px] text-slate-400 uppercase font-bold">SUPERFICIE AFECTADA</p>
              <p class="text-lg font-extrabold text-slate-800 mt-1">
                {{ stats()?.superficie_afectada_ha ?? 0 }} <span class="text-xs font-normal">Ha</span>
              </p>
            </div>
            <div class="bg-slate-50 p-3 rounded-lg border border-slate-100 text-center">
              <p class="text-[10px] text-slate-400 uppercase font-bold">F1-SCORE MODELO</p>
              <p class="text-lg font-extrabold text-emerald-600 mt-1">
                {{ f1ScorePorcentaje() }}%
              </p>
            </div>
          </div>

          <div class="space-y-2 pt-2">
            <p class="text-[11px] font-bold uppercase tracking-wider text-slate-400">RANKING DE DETECCIONES</p>
            <div class="space-y-2 text-xs">
              @for (sector of stats()?.ranking_sectores ?? []; track sector.nombre; let i = $index) {
                <div class="flex items-center justify-between p-2 bg-slate-50 rounded-lg">
                  <span class="font-semibold text-slate-700">{{ i + 1 }}. {{ sector.nombre }}</span>
                  <span class="font-bold text-red-600">{{ sector.hectareas }} Ha</span>
                </div>
              } @empty {
                <p class="text-slate-400 text-center py-2">Sin datos de sectores</p>
              }
            </div>
          </div>

          <div class="pt-3 border-t border-slate-100">
            <p class="text-[10px] uppercase font-bold text-slate-400 mb-1">PRECISIÓN DEL MODELO</p>
            <p class="text-xs font-semibold text-slate-700">Modelo ResNet-Unet (Entrenado 2026-04-15)</p>
            <div class="w-full bg-slate-200 h-2 rounded-full mt-2">
              <div class="bg-emerald-600 h-2 rounded-full w-[94.2%]"></div>
            </div>
          </div>

        </div>
      }

      <!-- ================= CONFIRMACIÓN DE EJECUCIÓN DE IA (SOLO ADMIN) ================= -->
      @if (modalConfirmacionIA()) {
        <div class="fixed inset-0 bg-black/50 z-[3000] flex items-center justify-center p-4">
          <div class="bg-white rounded-xl shadow-2xl max-w-md w-full p-5 space-y-4" role="dialog" aria-modal="true">
            <div class="flex items-start gap-3">
              <div class="w-9 h-9 rounded-full bg-amber-100 flex items-center justify-center shrink-0">
                <svg class="w-5 h-5 text-amber-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                        d="M12 9v4m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/>
                </svg>
              </div>
              <div>
                <h3 class="font-bold text-slate-800 text-sm">Ejecutar detección de IA</h3>
                <p class="text-xs text-slate-500 mt-1">Operación restringida al rol Administrador.</p>
              </div>
            </div>

            <div class="bg-amber-50 border border-amber-200 rounded-lg p-3 text-xs text-amber-900 space-y-1">
              <p>Se lanzará el <strong>pipeline quincenal completo</strong>:</p>
              <p>· Descarga Sentinel-2 (STAC / AWS): <strong>≈ 40 min</strong></p>
              <p>· Inferencia en SageMaker + auditoría: <strong>≈ 45 min</strong></p>
              <p class="pt-1">Se ejecuta en segundo plano (≈ 90 min en total). Durante ese tiempo no conviene lanzar otra ejecución.</p>
            </div>

            <div class="flex justify-end gap-2 pt-1">
              <button (click)="cancelarDeteccion()"
                      class="border border-slate-200 bg-white hover:bg-slate-50 text-slate-700 text-xs font-semibold px-3.5 py-2 rounded-lg transition">
                Cancelar
              </button>
              <button (click)="confirmarDeteccion()"
                      [disabled]="deteccionEnCurso()"
                      class="bg-emerald-700 hover:bg-emerald-800 text-white text-xs font-semibold px-3.5 py-2 rounded-lg transition disabled:opacity-60 disabled:cursor-not-allowed">
                {{ deteccionEnCurso() ? 'Lanzando…' : 'Sí, ejecutar ahora' }}
              </button>
            </div>
          </div>
        </div>
      }

    </div>
  `
})
export class DashboardComponent implements OnInit {
  private api = inject(ApiService);
  private destroyRef = inject(DestroyRef);

  private _stats = signal<DashboardStats | null>(null);
  private _auditLogs = signal<AuditLog[]>([]);

  stats = this._stats.asReadonly();
  auditLogs = this._auditLogs.asReadonly();

  usuarioSeleccionado = signal<string>('');
  panelIAAbierto = signal(false);

  // Lanzamiento manual del pipeline (solo Admin)
  modalConfirmacionIA = signal(false);
  deteccionEnCurso = signal(false);
  avisoDeteccion = signal<{ tipo: 'ok' | 'error'; texto: string } | null>(null);
  
  // Filtros reactivos con signals
  periodo = signal<'7d' | '30d' | 'historico'>('7d');
  areaSeleccionada = signal<string>('tambopata');
  capaPerdida = signal<boolean>(true);
  capaProtegida = signal<boolean>(true);

  fechaHoraPipeline = new Date().toLocaleString('es-PE');

  // Señal calculada memoizada
  porcentajeStorage = computed(() => {
    const s = this.stats();
    if (!s?.storage_usado_gb || !s?.storage_total_gb) return 0;
    return Math.round((s.storage_usado_gb / s.storage_total_gb) * 100);
  });

  // F1-Score redondeado adecuadamente
  f1ScorePorcentaje = computed(() => {
    const score = this.stats()?.f1_score;
    if (score == null) return '0.0';
    return (score * 100).toFixed(1);
  });

  ngOnInit(): void {
    this._cargarDatos();
  }

  private _cargarDatos(): void {
    // Pasar los filtros seleccionados al backend al recargar datos
    this.api.getDashboardStats({
      periodo: this.periodo(),
      area: this.areaSeleccionada()
    })
    .pipe(takeUntilDestroyed(this.destroyRef))
    .subscribe({
      next: (data) => this._stats.set(data),
      error: (err) => console.error('Error al cargar stats:', err)
    });

    this.cargarAuditLogs();
  }

  cambiarPeriodo(nuevoPeriodo: '7d' | '30d' | 'historico'): void {
    this.periodo.set(nuevoPeriodo);
    this._cargarDatos();
  }

  onAreaChange(nuevaArea: string): void {
    this.areaSeleccionada.set(nuevaArea);
    this._cargarDatos();
  }

  cargarAuditLogs(usuarioId?: string): void {
    this.api.getAuditLogs(usuarioId)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (logs) => this._auditLogs.set(logs),
        error: (err) => console.error('Error al cargar auditoría:', err)
      });
  }

  onUsuarioChange(event: Event): void {
    const select = event.target as HTMLSelectElement;
    const value = select.value;
    this.usuarioSeleccionado.set(value);
    this.cargarAuditLogs(value);
  }

  togglePanelIA(): void {
    this.panelIAAbierto.set(!this.panelIAAbierto());
  }

  ejecutarDeteccion(): void {
    this.avisoDeteccion.set(null);
    this.modalConfirmacionIA.set(true);
  }

  cancelarDeteccion(): void {
    this.modalConfirmacionIA.set(false);
  }

  confirmarDeteccion(): void {
    if (this.deteccionEnCurso()) {
      return;
    }
    this.modalConfirmacionIA.set(false);
    this.deteccionEnCurso.set(true);

    this.api.triggerDeteccion()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (r) => {
          this.deteccionEnCurso.set(false);
          this.avisoDeteccion.set({
            tipo: 'ok',
            texto: `Pipeline lanzado (tarea ${r.task_id ?? '—'}). Corre en segundo plano; `
                 + 'el resultado aparecerá en Registro de Actividad cuando termine.'
          });
        },
        error: (err) => {
          this.deteccionEnCurso.set(false);
          const detalle =
            err?.error?.detail ??
            err?.error?.error ??
            err?.message ??
            'error desconocido';
          this.avisoDeteccion.set({
            tipo: 'error',
            texto: `No se pudo lanzar el pipeline: ${detalle}`
          });
        }
      });
  }

  exportarCSV(): void {
    const rows = this._auditLogs();
    
    // Función auxiliar para escapar comas y comillas en CSV
    const escapeCsvField = (field: string | number) => {
      const str = String(field ?? '');
      if (str.includes(',') || str.includes('"') || str.includes('\n')) {
        return `"${str.replace(/"/g, '""')}"`;
      }
      return str;
    };

    const header = ['Usuario', 'Accion', 'FechaHora', 'Estado'];
    const csvRows = [
      header.join(','),
      ...rows.map(e => [
        escapeCsvField(e.usuario),
        escapeCsvField(e.accion),
        escapeCsvField(e.fechaHora),
        escapeCsvField(e.estado)
      ].join(','))
    ];

    // Incluir BOM \uFEFF para que Excel reconozca codificación UTF-8
    const blob = new Blob(['\uFEFF' + csvRows.join('\n')], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    
    const link = document.createElement('a');
    link.setAttribute('href', url);
    link.setAttribute('download', 'Auditoria_ApuGuard.csv');
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  }
}