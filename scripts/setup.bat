@echo off
REM =============================================
REM APU GUARD - Setup inicial (Windows)
REM Encadena: crear admin -> sectores -> verificar estado
REM =============================================

cd /d "%~dp0\.."

echo =============================================
echo  APU GUARD - Setup Inicial
echo =============================================
echo.

REM 1. Verificar prerequisitos
echo [1/5] Verificando prerequisitos...

where docker >nul 2>&1
if errorlevel 1 (
    echo   [ERROR] docker no esta instalado.
    exit /b 1
)

if not exist backend\.env (
    echo   [AVISO] backend\.env no existe.
    echo           Copia .env.example a backend\.env y edita las credenciales.
    echo           Comando: copy .env.example backend\.env
    set /p RESP="  Continuar de todos modos? (s/n): "
    if /i not "%RESP%"=="s" exit /b 1
)
echo   [OK] Docker y .env disponibles.
echo.

REM 2. Levantar servicios base
echo [2/5] Levantando servicios Docker (db, redis, web)...
docker compose up -d --build db redis web
echo   Esperando a que db este healthy...
:WAIT_DB
docker compose exec -T db pg_isready -U apuguard -d apuguard_db >nul 2>&1
if errorlevel 1 (
    timeout /t 2 >nul
    goto WAIT_DB
)
echo   [OK] Base de datos lista.

REM Esperar a que Django termine las migraciones
echo   Esperando a que Django este listo...
:WAIT_DJANGO
docker compose exec -T web python manage.py showmigrations core >nul 2>&1
if errorlevel 1 (
    timeout /t 3 >nul
    goto WAIT_DJANGO
)
echo   [OK] Django listo.
echo.

REM 3. Crear superusuario admin
echo [3/5] Creando usuario administrador...
:RETRY_ADMIN
docker compose exec -T web python manage.py crear_admin
if errorlevel 1 (
    echo   [RETRY] Fallo al crear admin. Reintentando en 3s...
    timeout /t 3 >nul
    goto RETRY_ADMIN
)
echo.

REM 4. Cargar sectores
echo [4/5] Cargando sectores de la Reserva Tambopata...
:RETRY_SECTORES
docker compose exec -T web python /app/scripts/01_cargar_sectores.py
if errorlevel 1 (
    echo   [RETRY] Fallo al cargar sectores. Reintentando en 3s...
    timeout /t 3 >nul
    goto RETRY_SECTORES
)
echo.

REM 5. Generar static layers (omitido)
echo [5/5] Generando static layers (mineria.tif, rios.tif)...
echo   [SKIP] Omitido. El usuario genera los static layers aparte.
echo          Para generarlos manualmente: scripts\02_generar_static_layers.bat
echo.

REM 6. Verificar estado
echo =============================================
echo  Estado final del sistema
echo =============================================
docker compose exec -T web python /app/scripts/03_verificar_estado.py

echo.
echo =============================================
echo  [OK] Setup completado.
echo =============================================
echo.
echo   Frontend : http://localhost:4200
echo   API      : http://localhost:8000/api/
echo   Admin    : http://localhost:8000/admin/
echo   Login    : admin / apuguard123
echo.
echo   Siguiente paso: levantar celery y frontend:
echo     docker compose up -d celery_worker celery_beat frontend
echo.
