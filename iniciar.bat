@echo off
title BETANA - Servidor Local
echo ============================================
echo   Iniciando BETANA...
echo   No cierres esta ventana mientras uses la web.
echo ============================================
cd /d "%~dp0"
timeout /t 1 >nul
start http://localhost:8000
python app.py
if %ERRORLEVEL% NEQ 0 (
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" app.py
)
pause
