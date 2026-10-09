FROM python:3.12-slim

# Dependencias del sistema para PostGIS / GDAL / rasterio
RUN apt-get update && apt-get install -y --no-install-recommends \
    gdal-bin \
    libgdal-dev \
    libgeos-dev \
    libproj-dev \
    libpq-dev \
    gcc \
    g++ \
    python3-gdal \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
# Instalar GDAL usando la version exacta del sistema para evitar compilacion
RUN GDAL_VERSION=$(gdal-config --version) && \
    pip install --no-cache-dir GDAL==${GDAL_VERSION} && \
    pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1
ENV DJANGO_SETTINGS_MODULE=apuguard.settings

EXPOSE 8000

# Arranque de produccion (Fase B):
#   1. migrate   --noinput  -> esquema al dia
#   2. collectstatic        -> WhiteNoise sirve Admin/DRF desde STATIC_ROOT
#   3. gunicorn             -> WSGI real, NO django runserver
# Tunable por entorno: PORT, WEB_CONCURRENCY, WEB_THREADS, WEB_TIMEOUT.
# El compose de desarrollo sobrescribe `command`, asi que esto solo se
# ejecuta cuando el contenedor arranca con el CMD de la imagen.
CMD ["sh", "-c", "python manage.py migrate --noinput && python manage.py collectstatic --noinput && gunicorn apuguard.wsgi:application --bind 0.0.0.0:${PORT:-8000} --workers ${WEB_CONCURRENCY:-2} --threads ${WEB_THREADS:-4} --timeout ${WEB_TIMEOUT:-120} --access-logfile -"]
