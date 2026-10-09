@echo off
REM =============================================
REM APU GUARD - Ver logs en tiempo real (Windows)
REM Uso: logs.bat [servicio]
REM =============================================

cd /d "%~dp0\.."

if "%~1"=="" (
    echo Mostrando logs de todos los servicios (Ctrl+C para salir)
    docker compose logs -f
) else (
    echo Mostrando logs de: %~1 (Ctrl+C para salir)
    docker compose logs -f %~1
)
