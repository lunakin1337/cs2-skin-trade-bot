@echo off
chcp 65001 >nul
setlocal
echo ==========================================
echo CS2 Skin Trade Bot (через локальный прокси)
echo ==========================================

cd /d "%~dp0"

set XRAY=%USERPROFILE%\.capy\work\xray\xray.exe
set XRAY_CFG=%USERPROFILE%\.capy\work\xray\config.json

if not exist "%XRAY%" (
    echo [!] Не найден Xray: %XRAY%
    echo     Без прокси Bot API с этого компьютера недоступен.
    pause
    exit /b 1
)

echo [1/3] Запуск прокси Xray...
start "Xray" /min "%XRAY%" run -c "%XRAY_CFG%"
timeout /t 3 >nul

echo [2/3] Проверка зависимостей...
pip show aiogram aiosqlite aiohttp >nul 2>&1
if errorlevel 1 (
    pip install -e .
)

echo [3/3] Запуск бота...
python -m src.bot.main

pause
