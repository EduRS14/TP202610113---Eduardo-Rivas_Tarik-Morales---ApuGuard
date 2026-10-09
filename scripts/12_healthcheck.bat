@echo off
REM =============================================
REM APU GUARD - Healthcheck de endpoints REST (Windows)
REM =============================================

setlocal enabledelayedexpansion

cd /d "%~dp0\.."

set API_BASE=http://localhost:8000/api
set FRONTEND_BASE=http://localhost:4200
set TOTAL=0
set OK=0

echo =============================================
echo  APU GUARD - Healthcheck de API
echo =============================================
echo.
echo API Base: %API_BASE%
echo Frontend: %FRONTEND_BASE%
echo.

REM El texto del nombre no puede contener parentesis: `%~1` se sustituye
REM dentro del bloque `if (...)` de las subrutinas y un `)` lo cerraria a destiempo.
call :check "GET  /api/sectores/"           "%API_BASE%/sectores/"           "401"
call :check "GET  /api/alertas/"            "%API_BASE%/alertas/"            "401"
call :check "GET  /api/dashboard/stats/"    "%API_BASE%/dashboard/stats/"    "401"
call :check "GET  /api/dashboard/audit-logs/" "%API_BASE%/dashboard/audit-logs/" "401"
call :check_post "POST /api/auth/token/"    "%API_BASE%/auth/token/"         "400"
call :check "GET  /admin/"                  "http://localhost:8000/admin/"   "302"
call :check "GET  / frontend"               "%FRONTEND_BASE%"                "200"

echo.
echo Resultado: !OK! / !TOTAL! checks OK
if "!OK!"=="!TOTAL!" (
    echo [OK] Todos los servicios respondiendo.
) else (
    echo [WARN] Hay servicios que no responden. Revisa docker compose ps
)

echo.
echo ============================================
echo   Presiona cualquier tecla para cerrar...
echo ============================================
pause >nul
goto :fin

REM ---------------------------------------------------------------
REM Subrutinas. Deben quedar despues del `goto :fin` del bloque
REM principal: si no, al terminar `pause` el flujo caeria aqui con
REM los argumentos vacios y curl recibiria una URL en blanco.
REM ---------------------------------------------------------------

:check
    set /a TOTAL+=1
    curl -s -o nul -w "%%{http_code}" --max-time 5 "%~2" > "%TEMP%\hc_code.txt"
    set /p CODE=<"%TEMP%\hc_code.txt"
    if "!CODE!"=="%~3" (
        echo   [OK]   %~1 -^> !CODE!
        set /a OK+=1
    ) else (
        echo   [FAIL] %~1 -^> !CODE! ^(esperado %~3^)
    )
    goto :eof

:check_post
    REM El endpoint es solo POST: con body JSON vacio devuelve 400.
    set /a TOTAL+=1
    curl -s -o nul -w "%%{http_code}" --max-time 5 -X POST -H "Content-Type: application/json" -d "{}" "%~2" > "%TEMP%\hc_code.txt"
    set /p CODE=<"%TEMP%\hc_code.txt"
    if "!CODE!"=="%~3" (
        echo   [OK]   %~1 -^> !CODE!
        set /a OK+=1
    ) else (
        echo   [FAIL] %~1 -^> !CODE! ^(esperado %~3^)
    )
    goto :eof

:fin
endlocal
