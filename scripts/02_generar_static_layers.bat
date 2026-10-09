@echo off
REM =============================================
REM APU GUARD - Generar static layers (mineria.tif, rios.tif)
REM =============================================

cd /d "%~dp0\.."

docker compose exec web python /app/scripts/02_generar_static_layers.py

echo.
echo ============================================
echo   Presiona cualquier tecla para cerrar...
echo ============================================
pause >nul
