"""Обновить WEB_APP_URL в .env по адресу запущенного cloudflared туннеля."""

import argparse
import pathlib
import re
import sys

URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
ENV_PATH = pathlib.Path(".env")



def _alive(url: str) -> bool:
    """Туннель считается готовым, когда /health отвечает 200."""
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(f"{url}/health", timeout=8) as response:
            return response.status == 200
    except (urllib.error.URLError, OSError):
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Обновить WEB_APP_URL из лога cloudflared")
    parser.add_argument("--log", default="cloudflare.log", help="Файл лога cloudflared")
    parser.add_argument("--timeout", type=int, default=30, help="Сколько секунд ждать URL")
    args = parser.parse_args()

    import time

    log_path = pathlib.Path(args.log)
    url = None
    for _ in range(args.timeout):
        if log_path.exists():
            # quic-туннель дописывает лог, поэтому нужен последний адрес, а не первый:
            # в файле остаются ссылки от прошлых запусков
            matches = URL_RE.findall(log_path.read_text(encoding="utf-8", errors="ignore"))
            if matches:
                candidate = matches[-1]
                if _alive(candidate):
                    url = candidate
                    break
        time.sleep(1)

    if not url:
        print(f"URL туннеля не найден в {log_path}", file=sys.stderr)
        return 1

    if not ENV_PATH.exists():
        print("нет файла .env", file=sys.stderr)
        return 1

    text = ENV_PATH.read_text(encoding="utf-8")
    if re.search(r"^WEB_APP_URL=", text, flags=re.M):
        text = re.sub(r"^WEB_APP_URL=.*$", f"WEB_APP_URL={url}", text, flags=re.M)
    else:
        text = text.rstrip("\n") + f"\nWEB_APP_URL={url}\n"
    ENV_PATH.write_text(text, encoding="utf-8")

    print(f"WEB_APP_URL = {url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
