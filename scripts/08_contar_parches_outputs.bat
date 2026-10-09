@echo off
REM =============================================
REM APU GUARD - Contar parches en sagemaker-outputs/
REM =============================================

cd /d "%~dp0\.."

docker compose exec web python /app/scripts/08_contar_parches_outputs.py

echo.
echo ============================================
echo   Presiona cualquier tecla para cerrar...
echo ============================================
pause >nul
