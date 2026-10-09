@echo off
REM =============================================
REM APU GUARD - Lanzar escucha SQS 10 veces (bulk)
REM =============================================

cd /d "%~dp0\.."

docker compose exec web python /app/scripts/06_lanzar_escucha_bulk.py

echo.
echo ============================================
echo   Presiona cualquier tecla para cerrar...
echo ============================================
pause >nul
