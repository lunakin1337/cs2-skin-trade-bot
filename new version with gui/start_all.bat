@echo off
chcp 65001 >nul
setlocal
echo ==========================================
echo CS2 Skin Trade: веб-приложение + туннель + бот
echo ==========================================

cd /d "%~dp0"

echo [1/5] Проверка зависимостей...
pip show aiogram aiosqlite aiohttp >nul 2>&1
if errorlevel 1 pip install -e .

echo [2/5] Прокси для Bot API...
rem Провайдер режет api.telegram.org напрямую. Рабочий вариант — WARP в proxy-режиме.
netstat -ano | findstr ":40000" >nul
if errorlevel 1 (
    echo Включаю WARP в режиме прокси...
    "C:\Program Files\Cloudflare\Cloudflare WARP\warp-cli.exe" mode proxy
    timeout /t 8 >nul
)

echo [3/5] Веб-приложение на http://localhost:8080 ...
start "CS2 WebApp" cmd /c "python -m src.web_app"
timeout /t 5 >nul

echo [4/5] Туннель и бот под присмотром супервизора...
echo   (cloudflared у провайдера режется, поэтому SSH-туннель localhost.run)
start "CS2 Supervisor" cmd /c "python scripts\supervise.py"

echo [5/5] Готово.
echo   Mini App: кнопка «Приложение» в меню бота (адрес в .env, обновляется сам)
echo   Логи:     tunnel_ssh.log, bot.log
echo   Стоп:     закройте окна
pause
