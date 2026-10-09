export type Rol = 'Administrador' | 'Analista';
export type EstadoUsuario = 'Activo' | 'Inactivo';

export interface Usuario {
  id: number;
  username: string;
  email: string;
  first_name: string;
  last_name: string;
  rol: Rol;
  estado: EstadoUsuario;
  sectores_ids?: number[];   // IDs de sectores asignados (solo Analistas)
  telefono?: string;
  fecha_ultimo_acceso?: string;
  fecha_registro?: string;
}

export interface LoginRequest {
  username: string;
  password: string;
}

export interface TokenResponse {
  access: string;
  refresh: string;
}

export interface JwtPayload {
  user_id: number;
  username: string;
  rol: Rol;
  exp: number;
  iat: number;
}
