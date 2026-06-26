@echo off
chcp 65001 >nul
title Retail Location Analyzer — Сборка для Windows

echo ============================================
echo  Retail Location Analyzer — Сборка для Windows
echo ============================================
echo.

:: Проверка Python
where python >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Python не найден. Установите Python с python.org
    pause
    exit /b 1
)

:: Установка PyInstaller
echo [1/3] Установка PyInstaller...
python -m pip install pyinstaller -q

:: Определяем путь к папке проекта
set ROOT=%~dp0
set DIST=%ROOT%dist

:: Очистка
echo [2/3] Очистка предыдущей сборки...
if exist "%ROOT%build" rmdir /s /q "%ROOT%build"
if exist "%DIST%" rmdir /s /q "%DIST%"

:: Сборка
echo [3/3] Сборка приложения...
python -m PyInstaller ^
    --onedir ^
    --name "RetailLocationAnalyzer" ^
    --distpath "%DIST%" ^
    --add-data "%ROOT%app.py;." ^
    --add-data "%ROOT%config.py;." ^
    --add-data "%ROOT%core;core" ^
    --add-data "%ROOT%exporters;exporters" ^
    --add-data "%ROOT%requirements.txt;." ^
    --collect-all streamlit ^
    --collect-all tornado ^
    --collect-all protobuf ^
    --collect-all markdown ^
    --collect-all gitpython ^
    --collect-submodules streamlit ^
    --hidden-import streamlit.web.bootstrap ^
    --hidden-import streamlit.runtime.scriptrunner ^
    --hidden-import tornado ^
    --hidden-import tornado.platform.asyncio ^
    --hidden-import pandas ^
    --hidden-import openpyxl ^
    --hidden-import plotly ^
    --hidden-import requests ^
    --hidden-import google.protobuf ^
    --collect-all google ^
    --windowed ^
    --icon "%ROOT%icon.ico" ^
    "%ROOT%launcher.py"

if %ERRORLEVEL% EQU 0 (
    echo.
    echo ============================================
    echo  ✅ Сборка завершена!
    echo  📁 %DIST%\RetailLocationAnalyzer\
    echo ============================================
    echo.
    echo  Чтобы создать ярлык:
    echo    - Откройте папку %DIST%\RetailLocationAnalyzer\
    echo    - Правой кнопкой на RetailLocationAnalyzer.exe
    echo    - Отправить ^> Рабочий стол (создать ярлык)
) else (
    echo.
    echo  [ERROR] Ошибка сборки
)

pause
