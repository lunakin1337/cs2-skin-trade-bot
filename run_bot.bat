@echo off
chcp 65001 >nul
echo ==========================================
echo Запуск CS2 Skin Trade Bot
echo ==========================================

cd /d "%~dp0"

echo.
echo [1/2] Проверка зависимостей...
pip show aiogram aiosqlite aiohttp >nul 2>&1
if errorlevel 1 (
    echo Установка зависимостей...
    pip install -e .
)

echo.
echo [2/2] Запуск бота...
set PYTHONPATH=src
python -m src.bot.main

pause