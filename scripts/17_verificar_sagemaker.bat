@echo off
REM =============================================
REM APU GUARD - Verificar config del endpoint SageMaker
REM =============================================

cd /d "%~dp0\.."

docker compose exec -T web python /app/scripts/17_verificar_sagemaker.py

echo.
echo ============================================
echo   Presiona cualquier tecla para cerrar...
echo ============================================
pause >nul
