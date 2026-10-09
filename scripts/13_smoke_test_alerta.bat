@echo off
REM =============================================
REM APU GUARD - Crear alerta de smoke test
REM =============================================

cd /d "%~dp0\.."

docker compose exec web python /app/scripts/13_smoke_test_alerta.py

echo.
echo ============================================
echo   Presiona cualquier tecla para cerrar...
echo ============================================
pause >nul
