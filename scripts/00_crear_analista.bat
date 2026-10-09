@echo off
REM =============================================
REM APU GUARD - Crear usuario Analista
REM Uso: 00_crear_analista.bat --username juan --password juan123 --sectores SEC-01 SEC-04
REM =============================================

cd /d "%~dp0\.."

if "%~1"=="" (
    echo Uso: 00_crear_analista.bat --username USER --password PASS [--email EMAIL] [--sectores SEC-01 SEC-02]
    echo.
    echo Ejemplo:
    echo   00_crear_analista.bat --username juan --password juan123 --sectores SEC-01 SEC-04
    exit /b 1
)

docker compose exec web python manage.py crear_analista %*

echo.
echo ============================================
echo   Presiona cualquier tecla para cerrar...
echo ============================================
pause >nul
