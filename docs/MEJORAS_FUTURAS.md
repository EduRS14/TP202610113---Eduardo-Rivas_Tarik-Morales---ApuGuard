# APU GUARD — Mejoras y Cambios Pendientes a Futuro

Registro de funcionalidades identificadas durante el desarrollo que quedaron fuera del alcance actual por tiempo. Organizadas por prioridad y área.

---

## ✅ Bugs corregidos durante el desarrollo

| Fecha | Componente | Bug | Solución aplicada |
|-------|-----------|-----|-------------------|
| Jun 2026 | `ml_engine/tasks.py` | **Doble-conteo en `ciclos_limpios_consecutivos`** — Con stride=64 y ventana=256px, cada zona es cubierta por hasta 16 parches solapados. Un mismo `CasoAuditoria` histórico era encontrado por múltiples parches adyacentes en una sola ejecución del pipeline, llamando a `incrementar_ciclo_limpio()` N veces en vez de una. Generaba valores inflados (ej. ciclos=9 en primera captura). | Se agregó `_aplicar_logica_ecologica._procesados` (set de PKs) que garantiza que cada caso histórico reciba máximo un incremento por parche procesado. El set se limpia al inicio de cada `_procesar_mensaje_sqs`. |
| Jun 2026 | `core/serializers.py` | **`getTecnicos()` devolvía lista vacía en el modal SMS** — La paginación global de DRF envolvía la respuesta en `{count, results:[...]}` pero el frontend esperaba array plano, causando que el modal de Notificar no mostrara destinatarios. | Se agregó `map((r) => Array.isArray(r) ? r : r.results ?? [])` en `ApiService.getTecnicos()`. |
| Jun 2026 | `core/views.py` | **Área afectada en Dashboard no sumaba alertas Pendientes** — Solo contaba casos `MONITOREO_ACTIVO` y `VALIDADO_POSITIVO`, excluyendo `PENDIENTE_REVISION`. | Se agregó `PENDIENTE_REVISION` al filtro de estados activos en `DashboardStatsView`. |
| Jun 2026 | `apuguard/settings.py` | **`last_login` no se actualizaba con JWT** — SimpleJWT no actualiza `last_login` por defecto, por lo que la columna "Último acceso" siempre mostraba `—`. | Se agregó `"UPDATE_LAST_LOGIN": True` en `SIMPLE_JWT`. |

---

## 🔴 Alta prioridad (afectan correctitud o experiencia directa)

### Backend

- **Unificar formato de mensaje SMS** — El SMS automático (pipeline) y el SMS manual (modal Notificar) tienen formatos distintos. Unificarlos para consistencia: incluir código ALT-XXX, sector, confianza y fecha en ambos.

- **CORS en bucket S3 para evidencia fotográfica** — El upload directo de fotos de campo a S3 mediante presigned PUT URL puede fallar si el bucket no tiene configurada la política CORS. Configurar en AWS S3 → Permisos → CORS:
  ```json
  [{"AllowedOrigins": ["http://localhost:4200"], "AllowedMethods": ["PUT"], "AllowedHeaders": ["*"]}]
  ```

- **Rotar credenciales AWS expuestas** — Se expuso una clave de acceso AWS
  (`AKIA********`) en contexto de conversación. Invalidar en AWS IAM y
  generar nuevas credenciales antes de cualquier despliegue a producción.

- **Endpoint GET `/api/alertas/<id>/` no devuelve `evidencia_url`** — Al abrir el detalle de una alerta, si ya tiene evidencia subida a S3, el campo `evidencia_url` no se genera como presigned GET URL. Añadir al `AlertaSerializer` o a la vista de detalle la generación de presigned GET URL desde `evidencia_s3_key`.

### Frontend

- **Botón "Descargar PDF" no tiene feedback de error** — Si el backend falla al generar el PDF, el botón vuelve a su estado normal sin notificar al usuario. Añadir `alert()` o toast en el `error` handler.

- **Exportar GeoJSON cuando no hay geometría** — Si `geom_afectada` es null, el backend devuelve 404 pero el frontend no maneja ese caso. Mostrar mensaje "Esta alerta no tiene geometría registrada" en vez de silencio.

---

## 🟡 Media prioridad (mejoras de funcionalidad)

### Backend

- **Paginación en `/api/tecnicos/`** — Actualmente devuelve respuesta paginada por la configuración global de DRF pero el frontend espera array plano. Se resolvió con un `map()` en el frontend, pero la solución correcta es desactivar paginación para ese endpoint específico con `pagination_class = None`.

- **Filtro de alertas por zona (`zona__icontains`)** — El filtro existe en el frontend pero la vista backend no lo implementa. Añadir filtro por nombre de sector en `AlertaListView.get_queryset()`.

- **`RegistroSMS.sns_message_id` mal nombrado** — El campo se llama `sns_message_id` pero el sistema usa Twilio (no AWS SNS). Renombrar a `twilio_message_sid` en el modelo y migración correspondiente.

- **Validación de número telefónico E.164** — `TecnicoCampo.telefono` acepta cualquier string. Añadir validador que fuerce formato `+51XXXXXXXXX` para evitar fallos silenciosos en Twilio.

- **Caso sin parche (`parche=None`)** — `CasoAuditoria` permite `parche=None` pero `AuditoriaDetalleView` llama `caso.parche` sin verificar nulidad, lo que lanzaría `AttributeError`. Añadir guard antes de llamar `_generar_presigned_urls`.

### Frontend

- **Sin manejo de token expirado (401 automático)** — Si el access token expira durante la sesión, las peticiones fallan con 401 pero el usuario no es redirigido al login. Implementar interceptor HTTP que detecte 401 y llame a `/api/auth/token/refresh/` automáticamente.

- **Mapa no refresca alertas en tiempo real** — El mapa carga los casos al iniciar el Dashboard pero no se actualiza si llega una nueva alerta. Añadir polling cada N minutos o WebSocket.

- **Tabla de alertas sin paginación en frontend** — La API devuelve datos paginados (`count`, `next`, `previous`) pero el componente solo muestra la primera página. Añadir controles de paginación o scroll infinito.

- **Sin confirmación antes de cambiar estado de alerta** — El botón "Validar" / "Reabrir" cambia el estado inmediatamente sin modal de confirmación. Añadir diálogo de confirmación.

- **Pantalla de Configuración sin persistencia real** — El campo `umbral_recuperacion_quincenas` se muestra pero no está conectado a un endpoint PATCH. Implementar `GET /api/configuracion/` y `PATCH /api/configuracion/` para leer y guardar `ConfiguracionGlobal`.

---

## 🟢 Baja prioridad (mejoras de UX / polish)

- **Notificación push en navegador** — Cuando llega una nueva alerta (detección automática), mostrar notificación del navegador usando la Web Notifications API además del badge en el navbar.

- **Modo oscuro** — Tailwind soporta `dark:` class variants. Añadir toggle y persistencia en localStorage.

- **Internacionalización (i18n)** — Todos los textos están en español hardcodeado en el template. Preparar para eventual soporte multiidioma con Angular i18n.

- **Selector de período en Dashboard** — Los KPIs muestran totales históricos. Añadir selector "Último mes / Últimos 3 meses / Todo" que filtre `nuevas_alertas_hoy` y `area_afectada_ha`.

- **Vista de detalle de reporte mensual** — La pantalla de Configuración lista los reportes con link de descarga pero no muestra un resumen visual de las métricas (gráfico de barras de casos por mes).

- **Log de actividad de usuarios** — Registrar qué usuario cambió el estado de qué alerta y cuándo. Actualmente `CasoAuditoria` no guarda quién hizo el PATCH.

- **Tests unitarios backend** — No hay tests escritos para los serializers, views ni la lógica del pipeline. Añadir suite con `pytest-django`.

- **Tests e2e frontend** — No hay tests Cypress o Playwright para los flujos críticos (login, ver alerta, notificar).

---

## 🔵 Infraestructura / Producción

- **Docker Compose para producción** — El `docker-compose.yml` actual usa `runserver` (solo desarrollo). Para producción: reemplazar con Gunicorn + Nginx, añadir `DEBUG=False`, configurar `ALLOWED_HOSTS` y `STATIC_ROOT`.

- **HTTPS y certificado SSL** — El despliegue productivo requiere certificado TLS. Configurar con Let's Encrypt + Certbot o AWS ACM.

- **Variables de entorno en producción** — El `.env` actual tiene credenciales en texto plano. Migrar a AWS Secrets Manager o similar.

- **Health checks del pipeline** — No hay alertas si Celery Worker cae o si SageMaker devuelve error sistemáticamente. Añadir monitoreo con CloudWatch o Sentry.

---

*Última actualización: Junio 2026*
