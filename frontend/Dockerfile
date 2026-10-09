# =====================================================================
# APU GUARD — frontend de PRODUCCION (Fase C)
# Multi-stage: node compila -> nginx sirve. No hay node en la imagen final.
#
# El build usa rutas relativas (/api/...), asi que NO hay environments ni
# fileReplacements: el mismo bundle sirve en dev y en prod, y el cambio de
# destino lo resuelve el reverse proxy (proxy.conf.json en dev,
# nginx.conf aqui).
# =====================================================================

# ---- Etapa 1: build ---------------------------------------------------
FROM node:20-alpine AS build

WORKDIR /app

COPY package*.json ./
# npm ci instala exactamente el package-lock.json (reproducible)
RUN npm ci

COPY . .

# Angular: builder "application" -> dist/apuguard-frontend/browser
RUN npx ng build --configuration production

# ---- Etapa 2: serve ---------------------------------------------------
FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist/apuguard-frontend/browser /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -qO- http://127.0.0.1/ >/dev/null 2>&1 || exit 1

CMD ["nginx", "-g", "daemon off;"]
