@echo off
REM =============================================
REM APU GUARD - Re-deploy endpoint SageMaker con nuevo model.tar.gz
REM Uso: 18_redeploy_sagemaker.bat s3://BUCKET/PATH/model.tar.gz
REM =============================================

cd /d "%~dp0\.."

if "%~1"=="" (
    echo Uso: 18_redeploy_sagemaker.bat s3://BUCKET/PATH/model.tar.gz
    echo.
    echo Ejemplo:
    echo   18_redeploy_sagemaker.bat s3://apuguard-datalake-prod/models/hrnet/model.tar.gz
    exit /b 1
)

docker compose exec -it web python /app/scripts/18_redeploy_sagemaker.py %*

echo.
echo ============================================
echo   Presiona cualquier tecla para cerrar...
echo ============================================
pause >nul
