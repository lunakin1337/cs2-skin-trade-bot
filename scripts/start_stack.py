"""Поднять весь стек одной командой: веб → туннель → WEB_APP_URL → бот.

Quick-туннель Cloudflare получает новый адрес при каждом запуске, поэтому руками это
делается в три шага и легко оставить бота со мёртвой ссылкой. Скрипт делает всё сам и
печатает актуальный адрес.

    python scripts/start_stack.py             # поднять что не поднято
    python scripts/start_stack.py --restart   # перезапустить бота и туннель
    python scripts/start_stack.py --print-url # только показать текущий адрес
"""

import argparse
import json
import pathlib
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
ENV = ROOT / ".env"
LOG = ROOT / "cloudflare.log"
PY = sys.executable
URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
LOCAL_HEALTH = "http://127.0.0.1:8080/health"


def http_ok(url: str, timeout: int = 6) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.status == 200
    except (urllib.error.URLError, OSError):
        return False


def env_value(key: str) -> str:
    if not ENV.exists():
        return ""
    for line in ENV.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip()
    return ""


def set_env_value(key: str, value: str) -> None:
    text = ENV.read_text(encoding="utf-8") if ENV.exists() else ""
    if re.search(rf"^{key}=", text, flags=re.M):
        text = re.sub(rf"^{key}=.*$", f"{key}={value}", text, flags=re.M)
    else:
        text = text.rstrip("\n") + f"\n{key}={value}\n"
    ENV.write_text(text, encoding="utf-8")


def set_menu_button(token: str, url: str) -> bool:
    """Кнопка «Приложение» в меню бота: без этого она остаётся на прошлом адресе туннеля."""
    if not token or not url:
        return False
    payload = json.dumps(
        {"menu_button": {"type": "web_app", "text": "Приложение", "web_app": {"url": url}}}
    ).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/setChatMenuButton",
        data=payload,
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return bool(json.loads(response.read().decode("utf-8")).get("ok"))
    except (urllib.error.URLError, OSError, ValueError) as error:
        print(f"меню: не удалось обновить кнопку — {error}")
        return False


def spawn(args: list[str], log: pathlib.Path) -> subprocess.Popen:
    log.parent.mkdir(parents=True, exist_ok=True)
    handle = open(log, "a", encoding="utf-8")
    return subprocess.Popen(
        args,
        cwd=str(ROOT),
        stdout=handle,
        stderr=subprocess.STDOUT,
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        | getattr(subprocess, "DETACHED_PROCESS", 0),
    )


def kill_bots() -> int:
    command = (
        "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
        "Where-Object { $_.CommandLine -match 'bot.main' } | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force; $_.ProcessId }"
    )
    try:
        result = subprocess.run(["powershell", "-NoProfile", "-Command", command],
                                capture_output=True, text=True, timeout=30)
        return len([line for line in result.stdout.splitlines() if line.strip()])
    except (subprocess.SubprocessError, OSError):
        return 0


def ensure_web() -> bool:
    if http_ok(LOCAL_HEALTH):
        print("веб: уже работает")
        return True
    spawn([PY, "-m", "web_app"], ROOT / "webapp-stack.log")
    for _ in range(20):
        time.sleep(1)
        if http_ok(LOCAL_HEALTH):
            print("веб: поднят на 8080")
            return True
    print("веб: не поднялся, смотрите webapp-stack.log")
    return False


def ensure_tunnel(cloudflared: str, restart: bool) -> str | None:
    if restart and LOG.exists():
        LOG.unlink()
    spawn([cloudflared, "tunnel", "--url", "http://localhost:8080", "--logfile", str(LOG)], LOG)
    for _ in range(30):
        time.sleep(1)
        if not LOG.exists():
            continue
        matches = URL_RE.findall(LOG.read_text(encoding="utf-8", errors="ignore"))
        if matches:
            url = matches[-1]
            if http_ok(f"{url}/health"):
                print(f"туннель: {url}")
                return url
    print("туннель: адрес не получен, смотрите cloudflare.log")
    return None


def start_bot() -> None:
    spawn([PY, "-m", "bot.main"], ROOT / "bot-stack.log")
    time.sleep(6)
    print("бот: запущен, лог bot-stack.log")


def main() -> int:
    parser = argparse.ArgumentParser(description="Поднять бота, веб и туннель")
    parser.add_argument("--restart", action="store_true", help="перезапустить бота и туннель")
    parser.add_argument("--print-url", action="store_true", help="показать адрес и выйти")
    parser.add_argument(
        "--cloudflared",
        default=r"C:\Program Files (x86)\cloudflared\cloudflared.exe",
        help="путь к cloudflared",
    )
    args = parser.parse_args()

    if args.print_url:
        url = env_value("WEB_APP_URL")
        print(url or "WEB_APP_URL не задан")
        print("живой" if url and http_ok(f"{url}/health") else "не отвечает")
        return 0

    url = env_value("WEB_APP_URL")
    if args.restart or not (url and http_ok(f"{url}/health")):
        ensure_web()
        fresh = ensure_tunnel(args.cloudflared, args.restart)
        if fresh:
            set_env_value("WEB_APP_URL", fresh)
            url = fresh
            if not args.restart:
                # бот читает .env при старте, поэтому после смены адреса его надо перезапустить
                kill_bots()
    elif not http_ok(LOCAL_HEALTH):
        ensure_web()

    if args.restart or not url:
        pass
    killed = kill_bots() if args.restart or url != env_value("WEB_APP_URL") else 0
    if killed:
        print(f"бот: остановлено процессов — {killed}")
    start_bot()

    if set_menu_button(env_value("BOT_TOKEN"), env_value("WEB_APP_URL")):
        print("меню: кнопка «Приложение» обновлена")

    print()
    print(f"Mini App: {env_value('WEB_APP_URL')}")
    print(f"локально: {LOCAL_HEALTH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
