@echo off
REM =============================================
REM APU GUARD - Generar PNGs historicos (backfill)
REM Uso: 14_generar_visualizaciones_historicas.bat [--todos] [--captura-id N] [--dry-run]
REM =============================================

cd /d "%~dp0\.."

if "%~1"=="" (
    docker compose exec web python /app/scripts/14_generar_visualizaciones_historicas.py
) else (
    docker compose exec web python /app/scripts/14_generar_visualizaciones_historicas.py %*
)

echo.
echo ============================================
echo   Presiona cualquier tecla para cerrar...
echo ============================================
pause >nul
