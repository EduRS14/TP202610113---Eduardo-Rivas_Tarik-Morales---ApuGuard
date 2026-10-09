@echo off
REM =============================================
REM APU GUARD - Lanzar tarea quincenal (STAC + SageMaker)
REM =============================================

cd /d "%~dp0\.."

docker compose exec web python /app/scripts/04_lanzar_quincena.py

echo.
echo ============================================
echo   Presiona cualquier tecla para cerrar...
echo ============================================
pause >nul
