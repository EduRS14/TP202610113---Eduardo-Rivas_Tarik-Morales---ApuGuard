export type EstadoAlerta = 'Pendiente' | 'Validada en campo' | 'Descartada';
export type SeveridadAlerta = 'Alta' | 'Media' | 'Baja';
export type TipoCaso = 'DETECCION' | 'INCERTIDUMBRE';
export type EstadoEcologico = 'PERTURBADO' | 'RECUPERANDO' | 'RECUPERADO';
export type EstadoSms = 'ENVIADO' | 'FALLIDO' | 'PENDIENTE';

export interface RegistroSms {
  id: number;
  tecnico_nombre: string;
  tecnico_telefono: string;
  fecha_envio: string | null;
  estado: EstadoSms;
  error_detalle: string | null;
}

export interface Alerta {
  id: number;
  codigo: string;           // e.g. ALT-001
  fecha: string;            // ISO date
  zona: string;             // nombre sector
  sector_id: number;
  coordenadas: string;      // "lat, lon"
  area_ha: number;
  severidad: SeveridadAlerta;
  estado: EstadoAlerta;
  imagen_evidencia?: string;
  evidencia_url?: string;   // presigned URL o preview local
  notas?: string;
  notas_tecnico?: string;
  geojson?: object;
  // Campos del CasoAuditoria
  tipo_caso?: TipoCaso;
  score_confianza?: number;
  estado_ecologico?: EstadoEcologico;
  ciclos_limpios_consecutivos?: number;
  sms_historial?: RegistroSms[];
  // Fase G6: deduplicacion entre pasadas
  es_nueva?: boolean;                      // nacio en la ultima pasada
  fecha_nacimiento?: string | null;        // fecha_adquisicion de nacimiento
  fecha_ultima_deteccion?: string | null;  // ultima pasada en que se vio
  veces_detectado?: number;                // pasadas en las que se ha detectado
  // Visualizaciones (generadas por el backend desde el .out de SageMaker)
  url_imagen_satelital?: string | null;  // RGB del parche
  url_capa_ia?:          string | null;  // Overlay de probabilidad
}

export interface Sector {
  id: number;
  nombre: string;
  codigo?: string;
  geometry?: object;        // GeoJSON
}

export interface TecnicoCampo {
  id: number;
  nombre: string;
  telefono: string;
  email?: string;
  sector: Sector | null;
  sectores?: Sector[];
  activo?: boolean;
}

export interface Reporte {
  id: number;
  anio: number;
  mes: number;
  casos_validados: number;
  casos_recuperados: number;
  total_sms_enviados: number;
  fecha_emision: string;
  s3_presigned_url: string;
}
