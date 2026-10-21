@echo off
title Suso Demonic Consultation - Servidor + Link Publico
cd /d "%~dp0"
echo Iniciando servidor Flask en segundo plano...
start "Servidor Flask MTG" "%LOCALAPPDATA%\Python\pythoncore-3.15-64\python.exe" app.py
timeout /t 2 /nobreak >nul
echo.
echo ============================================================================
echo   Generando tu LINK PUBLICO (busca la linea https://....trycloudflare.com)
echo ============================================================================
echo.
"%LOCALAPPDATA%\Programs\cloudflared.exe" tunnel --url http://127.0.0.1:5000
pause
