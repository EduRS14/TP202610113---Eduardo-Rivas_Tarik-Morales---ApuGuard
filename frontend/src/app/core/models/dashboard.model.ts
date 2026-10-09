// Define e exporta la interfaz antes de usarla en DashboardStats
export interface SectorRanking {
  nombre: string;
  hectareas: number;
}

export interface CoberturaStats {
  bosque: number;
  no_bosque: number;
  degradado: number;
}

export interface UltimaImagen {
  nombre?: string;
  satelite?: string;
  fecha?: string;
  resultado?: string;
}

export interface PipelineStep {
  nombre: string;
  porcentaje: number;
  estado: string;
}

export interface UsuarioOp {
  id: number | string;
  first_name?: string;
  last_name?: string;
  username: string;
}

export interface AuditLog {
  id: number | string;
  usuario: string;
  accion: string;
  fechaHora: string;
  estado: string;
}

export interface UltimaCaptura {
  id: number;
  fecha: string;
  estado: string;
}

export interface DashboardStats {
  // Fase G6: KPIs reales de alertas
  alertas_activas?: number;       // casos abiertos (PENDIENTE + MONITOREO)
  alertas_nuevas_pasada?: number; // de esos, los que nacieron en la ultima pasada
  alertas_totales?: number;
  area_afectada_ha?: number;      // acumulado (solo DETECCION)
  area_nueva_pasada_ha?: number;  // area que nacio en la ultima pasada
  usuarios_activos?: number;
  ultima_captura?: UltimaCaptura | null;

  // Legacy (alias de alertas_activas)
  nuevas_alertas_hoy?: number;
  estado_sistema?: string;
  storage_usado_gb?: number;
  storage_total_gb?: number;

  // Propiedades requeridas por DashboardComponent:
  ultima_imagen?: UltimaImagen;
  pipeline_steps?: PipelineStep[];
  usuarios?: UsuarioOp[];

  // Propiedades de Estadísticas IA:
  cobertura?: CoberturaStats;
  superficie_afectada_ha?: number;
  f1_score?: number;
  ranking_sectores?: SectorRanking[];
}