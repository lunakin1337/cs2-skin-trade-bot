@echo off
chcp 65001 >nul
setlocal
echo ==========================================
echo Запуск CS2 Skin Trade Web App
echo ==========================================

cd /d "%~dp0"

echo [1/2] Проверка зависимостей...
pip show aiogram aiosqlite aiohttp >nul 2>&1
if errorlevel 1 (
    echo Установка зависимостей...
    pip install -e .
)

echo [2/2] Запуск веб-приложения на http://localhost:8080 ...
python -m src.web_app

pause
