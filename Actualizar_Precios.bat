@echo off
chcp 65001 > nul
title Actualizar Precios y Fibonacci - Buscar un buen precio
echo ==========================================================
echo   SINCRONIZADOR DE MERCADO Y RETROCESOS FIBONACCI
echo   Proyecto: Buscar un buen precio
echo ==========================================================
echo.
cd /d "%~dp0"
python market_updater.py
echo.
echo Presiona cualquier tecla para cerrar esta ventana...
pause > nul
