@echo off
REM =============================================
REM APU GUARD - Reset (Windows)
REM =============================================

setlocal enabledelayedexpansion

cd /d "%~dp0\.."

echo =============================================
echo  APU GUARD - Reset
echo =============================================
echo.
echo   Esto eliminara:
echo     - Todos los contenedores
echo     - El volumen postgres_data (BORRARA LA BD)
echo     - Todas las imagenes locales de apuguard
echo.
set /p RESP="  Estas seguro? (s/n): "
if /i not "!RESP!"=="s" (
    echo Cancelado.
    exit /b 0
)

echo.
echo Deteniendo contenedores...
docker compose down

echo Borrando volumen postgres_data...
docker compose down -v

echo Borrando imagenes locales de apuguard...
for /f "tokens=3" %%i in ('docker images ^| findstr apuguard') do docker rmi -f %%i 2>nul

echo.
echo [OK] Reset completo. Ejecuta scripts\setup.bat para volver a inicializar.

endlocal
