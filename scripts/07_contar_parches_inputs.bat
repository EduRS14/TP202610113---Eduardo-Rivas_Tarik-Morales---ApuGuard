@echo off
REM =============================================
REM APU GUARD - Contar parches en sagemaker-inputs/
REM Uso: 07_contar_parches_inputs.bat [captura_id]
REM =============================================

cd /d "%~dp0\.."

if "%~1"=="" (
    docker compose exec web python /app/scripts/07_contar_parches_inputs.py
) else (
    docker compose exec web python /app/scripts/07_contar_parches_inputs.py %~1
)

echo.
echo ============================================
echo   Presiona cualquier tecla para cerrar...
echo ============================================
pause >nul
