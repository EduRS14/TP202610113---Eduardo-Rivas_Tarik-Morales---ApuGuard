@echo off
REM =============================================
REM APU GUARD - Cargar 5 sectores de Tambopata
REM =============================================

cd /d "%~dp0\.."

docker compose exec web python /app/scripts/01_cargar_sectores.py

echo.
echo ============================================
echo   Presiona cualquier tecla para cerrar...
echo ============================================
pause >nul
