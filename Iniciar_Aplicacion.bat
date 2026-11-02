@echo off
setlocal
set "PYTHONUTF8=1"
chcp 65001 > nul
title Buscar un buen precio
echo ==========================================================
echo   BUSCAR UN BUEN PRECIO
echo   Panel, precios automaticos y Telegram
echo ==========================================================
echo.
cd /d "%~dp0"
if errorlevel 1 goto folder_error

rem Preferir el lanzador oficial de Python; admitir tambien python.exe.
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" > nul 2>&1
if errorlevel 1 goto try_python
py -3 launcher.py
set "APP_EXIT_CODE=%ERRORLEVEL%"
goto finished

:try_python
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" > nul 2>&1
if errorlevel 1 goto python_error
python launcher.py
set "APP_EXIT_CODE=%ERRORLEVEL%"
goto finished

:python_error
echo No se encuentra Python 3.10 o superior.
echo Instala Python desde https://www.python.org/downloads/windows/
echo Activa la opcion de anadir Python al PATH y vuelve a abrir este archivo.
set "APP_EXIT_CODE=1"
goto finished

:folder_error
echo No se puede acceder a la carpeta del proyecto.
set "APP_EXIT_CODE=1"

:finished
if "%APP_EXIT_CODE%"=="0" exit /b 0
echo.
echo No se ha podido iniciar la aplicacion. Revisa el mensaje anterior.
pause
exit /b %APP_EXIT_CODE%
