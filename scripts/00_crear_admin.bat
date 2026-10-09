@echo off
REM =============================================
REM APU GUARD - Crear superusuario admin
REM =============================================

cd /d "%~dp0\.."

docker compose exec web python manage.py crear_admin %*

echo.
echo ============================================
echo   Presiona cualquier tecla para cerrar...
echo ============================================
pause >nul
