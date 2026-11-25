"""Обновление WEB_APP_URL: берётся последний живой адрес туннеля."""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "scripts"))

import refresh_webapp_url as refresher  # noqa: E402


def test_picks_last_url_and_rewrites_env(tmp_path, monkeypatch):
    log = tmp_path / "cloudflare.log"
    log.write_text(
        "старый запуск https://old-tunnel-aaa.trycloudflare.com\n"
        "новый запуск https://new-tunnel-bbb.trycloudflare.com\n",
        encoding="utf-8",
    )
    env = tmp_path / ".env"
    env.write_text("BOT_TOKEN=1\nWEB_APP_URL=https://stale.trycloudflare.com\n", encoding="utf-8")

    monkeypatch.setattr(refresher, "ENV_PATH", env)
    monkeypatch.setattr(refresher, "_alive", lambda url: True)
    monkeypatch.setattr(sys, "argv", ["refresh_webapp_url.py", "--log", str(log), "--timeout", "1"])

    assert refresher.main() == 0
    text = env.read_text(encoding="utf-8")
    assert "WEB_APP_URL=https://new-tunnel-bbb.trycloudflare.com" in text
    assert "stale" not in text


def test_waits_for_alive_tunnel(tmp_path, monkeypatch):
    log = tmp_path / "cloudflare.log"
    log.write_text("https://dead-tunnel.trycloudflare.com\nhttps://live-tunnel.trycloudflare.com\n", encoding="utf-8")
    env = tmp_path / ".env"
    env.write_text("WEB_APP_URL=\n", encoding="utf-8")

    monkeypatch.setattr(refresher, "ENV_PATH", env)
    monkeypatch.setattr(
        refresher, "_alive", lambda url: url == "https://live-tunnel.trycloudflare.com"
    )
    monkeypatch.setattr(sys, "argv", ["refresh_webapp_url.py", "--log", str(log), "--timeout", "2"])

    assert refresher.main() == 0
    assert "live-tunnel" in env.read_text(encoding="utf-8")


def test_missing_url_reports_error(tmp_path, monkeypatch, capsys):
    log = tmp_path / "cloudflare.log"
    log.write_text("ничего интересного\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["refresh_webapp_url.py", "--log", str(log), "--timeout", "1"])

    assert refresher.main() == 1
    assert "URL туннеля не найден" in capsys.readouterr().err
