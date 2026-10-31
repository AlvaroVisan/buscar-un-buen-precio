@echo off
chcp 65001 > nul
title Panel Web - Buscar un buen precio
echo ==========================================================
echo   INICIANDO PANEL WEB FIBONACCI
echo   Proyecto: Buscar un buen precio
echo ==========================================================
echo.
cd /d "%~dp0"
python app.py
pause
