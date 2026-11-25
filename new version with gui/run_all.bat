@echo off
chcp 65001 >nul
setlocal
echo ==========================================
echo CS2 Skin Trade Bot + Cloudflare Tunnel
echo ==========================================

cd /d "%~dp0"

findstr "WEB_APP_URL" .env >nul 2>&1
if errorlevel 1 (
    echo [!] WEB_APP_URL не найден в .env — кнопка Mini App не появится.
)

echo.
echo [1/4] Проверка зависимостей...
pip show aiogram aiosqlite aiohttp >nul 2>&1
if errorlevel 1 (
    echo Установка зависимостей...
    pip install -e .
)

echo.
echo [2/4] Запуск веб-приложения на http://localhost:8080 ...
start "CS2 WebApp" cmd /c "python -m src.web_app"
timeout /t 3 >nul

echo.
echo [3/4] Запуск Cloudflare Tunnel...
if exist "C:\Program Files (x86)\cloudflared\cloudflared.exe" (
    start "cloudflared" cmd /c ""C:\Program Files (x86)\cloudflared\cloudflared.exe" tunnel --url http://localhost:8080 > cloudflare.log 2>&1"
    echo Ожидание URL туннеля...
    timeout /t 10 >nul
    findstr /c:"trycloudflare.com" cloudflare.log
    echo.
    echo Скопируйте https-адрес выше в WEB_APP_URL в .env и перезапустите бота.
) else (
    echo [!] cloudflared не найден — туннель пропущен, приложение доступно только локально.
)

echo.
echo [4/4] Запуск бота...
start "CS2 Bot" cmd /c "python -m src.bot.main"

echo.
echo ==========================================
echo Web App: http://localhost:8080
echo Bot:     python -m src.bot.main
echo Стоп:     закройте окна консоли
echo ==========================================

pause
