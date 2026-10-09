@echo off
REM =============================================
REM APU GUARD - Lanzar escucha SQS (1 vez)
REM =============================================

cd /d "%~dp0\.."

docker compose exec web python /app/scripts/05_lanzar_escucha.py

echo.
echo ============================================
echo   Presiona cualquier tecla para cerrar...
echo ============================================
pause >nul
