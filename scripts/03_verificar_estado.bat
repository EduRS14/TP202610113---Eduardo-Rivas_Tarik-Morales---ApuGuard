@echo off
REM =============================================
REM APU GUARD - Verificar estado del sistema (BD)
REM =============================================

cd /d "%~dp0\.."

docker compose exec web python /app/scripts/03_verificar_estado.py

echo.
echo ============================================
echo   Presiona cualquier tecla para cerrar...
echo ============================================
pause >nul
