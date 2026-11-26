"""Держит SSH-туннель и бота живыми: следит за здоровьем и обновляет WEB_APP_URL.

Запускается в фоне (`python scripts/supervise.py`). Полезно, когда провайдер режет
`cloudflared`: туннель на localhost.run живёт, пока жива SSH-сессия, а адрес
меняется при переподключении — супервизор сам подхватывает новый адрес, правит
`.env` и перезапускает бота, чтобы кнопка Mini App оставалась рабочей.
"""

import os
import pathlib
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
TUNNEL_LOG = ROOT / "tunnel_ssh.log"
BOT_LOG = ROOT / "bot.log"

URL_RE = re.compile(r"https://[a-z0-9]+\.app\.lhr\.life")
SSH_CMD = [
    "ssh",
    "-o", "StrictHostKeyChecking=no",
    "-o", "UserKnownHostsFile=/dev/null",
    "-o", "ServerAliveInterval=30",
    "-o", "ServerAliveCountMax=3",
    "-o", "ExitOnForwardFailure=yes",
    "-R", "80:127.0.0.1:8080",
    "nokey@localhost.run",
]
HEALTH_INTERVAL = 15
BOT_PATTERN = "*bot.main*"


def log(message: str) -> None:
    stamp = time.strftime("%H:%M:%S")
    print(f"[{stamp}] {message}", flush=True)


def env_url() -> str | None:
    if not ENV_PATH.exists():
        return None
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        if line.startswith("WEB_APP_URL="):
            return line.split("=", 1)[1].strip() or None
    return None


def set_env_url(url: str) -> None:
    text = ENV_PATH.read_text(encoding="utf-8")
    if re.search(r"^WEB_APP_URL=", text, flags=re.M):
        text = re.sub(r"^WEB_APP_URL=.*$", f"WEB_APP_URL={url}", text, flags=re.M)
    else:
        text = text.rstrip("\n") + f"\nWEB_APP_URL={url}\n"
    ENV_PATH.write_text(text, encoding="utf-8")


def kill_bots() -> None:
    command = (
        "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
        f"Where-Object {{ $_.CommandLine -like '{BOT_PATTERN}' }} | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", command], capture_output=True)


def start_bot() -> None:
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    with open(BOT_LOG, "a", encoding="utf-8") as log_file:
        subprocess.Popen(
            [sys.executable, "-m", "src.bot.main"],
            cwd=str(ROOT),
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )
    log("бот запущен")


def start_tunnel() -> subprocess.Popen:
    log_file = open(TUNNEL_LOG, "w", encoding="utf-8", errors="ignore")
    process = subprocess.Popen(SSH_CMD, stdout=log_file, stderr=subprocess.STDOUT)
    log("туннель запускается")
    return process


def wait_url(timeout: float = 40) -> str | None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if TUNNEL_LOG.exists():
            text = TUNNEL_LOG.read_text(encoding="utf-8", errors="ignore")
            match = URL_RE.search(text)
            if match:
                return match.group(0)
        time.sleep(1)
    return None


def healthy(url: str) -> bool:
    try:
        with urllib.request.urlopen(f"{url}/health", timeout=12) as response:
            return response.status == 200
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
        return False


def main() -> None:
    kill_bots()
    start_bot()

    tunnel: subprocess.Popen | None = None
    current = env_url()

    while True:
        if tunnel is None or tunnel.poll() is not None:
            tunnel = start_tunnel()

        url = wait_url()
        if not url:
            log("адрес туннеля не появился, перезапускаю")
            tunnel.terminate()
            tunnel = None
            time.sleep(5)
            continue

        if url != current:
            log(f"новый адрес {url}")
            set_env_url(url)
            current = url
            kill_bots()
            start_bot()

        while tunnel.poll() is None and healthy(url):
            time.sleep(HEALTH_INTERVAL)

        log("туннель перестал отвечать, перезапускаю")
        tunnel.terminate()
        try:
            tunnel.wait(timeout=5)
        except subprocess.TimeoutExpired:
            tunnel.kill()
        tunnel = None
        time.sleep(5)


if __name__ == "__main__":
    main()
