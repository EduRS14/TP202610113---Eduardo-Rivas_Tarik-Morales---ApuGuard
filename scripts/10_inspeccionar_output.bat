@echo off
REM =============================================
REM APU GUARD - Inspeccionar un .npz procesado
REM =============================================

cd /d "%~dp0\.."

docker compose exec web python /app/scripts/10_inspeccionar_output.py

echo.
echo ============================================
echo   Presiona cualquier tecla para cerrar...
echo ============================================
pause >nul
