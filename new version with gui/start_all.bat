@echo off
chcp 65001 >nul
setlocal
echo ==========================================
echo CS2 Skin Trade: бот + Mini App + туннель
echo ==========================================

cd /d "%~dp0"

set XRAY=%USERPROFILE%\.capy\work\xray\xray.exe
set XRAY_CFG=%USERPROFILE%\.capy\work\xray\config.json
set CLOUDFLARED=C:\Program Files (x86)\cloudflared\cloudflared.exe

echo [1/6] Проверка зависимостей...
pip show aiogram aiosqlite aiohttp >nul 2>&1
if errorlevel 1 pip install -e .

echo [2/6] Прокси Xray (Bot API с этого компьютера доступен только через него)...
if exist "%XRAY%" (
    start "Xray" /min "%XRAY%" run -c "%XRAY_CFG%"
    timeout /t 3 >nul
) else (
    echo [!] Xray не найден: %XRAY%
)

echo [3/6] Веб-приложение на http://localhost:8080 ...
start "CS2 WebApp" cmd /c "python -m src.web_app"
timeout /t 4 >nul

echo [4/6] Туннель cloudflared...
if exist "%CLOUDFLARED%" (
    start "cloudflared" cmd /c ""%CLOUDFLARED%" tunnel --url http://localhost:8080 > cloudflare.log 2>&1"
    timeout /t 10 >nul
    python scripts\refresh_webapp_url.py --log cloudflare.log
) else (
    echo [!] cloudflared не найден — Mini App будет доступен только локально
)

echo [5/6] Перезапуск бота с новым WEB_APP_URL...
start "CS2 Bot" cmd /c "python -m src.bot.main"

echo [6/6] Готово.
echo   Mini App: кнопка «Приложение» в меню бота
echo   Логи:     cloudflare.log, консоли окон
echo   Стоп:     закройте окна
pause
