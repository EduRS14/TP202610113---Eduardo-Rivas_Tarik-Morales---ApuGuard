@echo off
REM =============================================
REM APU GUARD - Verificar consistencia BD vs S3 (parches procesados)
REM =============================================

cd /d "%~dp0\.."

docker compose exec web python /app/scripts/09_parches_procesados.py

echo.
echo ============================================
echo   Presiona cualquier tecla para cerrar...
echo ============================================
pause >nul
