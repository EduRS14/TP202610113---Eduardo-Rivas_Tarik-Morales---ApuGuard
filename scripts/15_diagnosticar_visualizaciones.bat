@echo off
REM =============================================
REM APU GUARD - Diagnosticar visualizaciones (PNGs en S3)
REM =============================================

cd /d "%~dp0\.."

docker compose exec web python /app/scripts/15_diagnosticar_visualizaciones.py

echo.
echo ============================================
echo   Presiona cualquier tecla para cerrar...
echo ============================================
pause >nul
