@echo off
REM =============================================
REM APU GUARD - Revocar tarea Celery por ID
REM Uso: 11_revocar_tarea.bat <TASK_ID> [--terminar]
REM =============================================

cd /d "%~dp0\.."

if "%~1"=="" (
    echo Uso: 11_revocar_tarea.bat TASK_ID [--terminar]
    echo.
    echo Ejemplo:
    echo   11_revocar_tarea.bat 5abd0500-c68b-440e-9995-95b2582e2e58
    exit /b 1
)

docker compose exec web python /app/scripts/11_revocar_tarea.py %*

echo.
echo ============================================
echo   Presiona cualquier tecla para cerrar...
echo ============================================
pause >nul
