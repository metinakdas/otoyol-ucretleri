"""Ortak test yardımcıları. Testler internete çıkmaz; tüm siteler sahte yanıtlarla taklit edilir."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from radar.config import load_config  # noqa: E402

FIX = ROOT / "tests" / "fixtures"


class FakeWeb:
    """URL → yanıt eşlemesi. Tanımsız adresler 404 döner."""

    def __init__(self):
        self.routes: dict[str, tuple[int, bytes, str]] = {}
        self.requests: list[str] = []

    def html(self, url: str, body: str, status: int = 200) -> None:
        self.routes[url] = (status, body.encode("utf-8"), "text/html; charset=utf-8")

    def pdf(self, url: str, path: Path) -> None:
        self.routes[url] = (200, path.read_bytes(), "application/pdf")

    def error(self, url: str, status: int = 500) -> None:
        self.routes[url] = (status, b"hata", "text/plain")

    def json(self, url: str, data, status: int = 200) -> None:
        self.routes[url] = (status, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json")

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.requests.append(url)
        status, body, ctype = self.routes.get(url, (404, b"yok", "text/plain"))
        return httpx.Response(status, content=body, headers={"content-type": ctype})

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)


class FakeTelegram:
    def __init__(self):
        self.sent: list[dict] = []
        self.client = httpx.Client(transport=httpx.MockTransport(self.handler))

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.sent.append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True})

    def texts(self) -> list[str]:
        return [m["text"] for m in self.sent]

    def take(self) -> list[str]:
        out = self.texts()
        self.sent.clear()
        return out


@pytest.fixture
def cfg(tmp_path):
    c = load_config(ROOT, data_dir=tmp_path / "data")
    s = c.settings
    s.telegram_token = "TEST"
    s.telegram_chat_id = "-100"
    s.telegram_tech_chat_id = "-200"
    # Gerçek .env'deki WhatsApp ayarları testlerde kullanılmaz
    s.wa_token = s.wa_phone_id = ""
    s.wa_to = []
    s.smtp_host = ""
    s.email_to = []
    s.request_delay = 0
    s.panel_url = "https://ornek.github.io/otoyol/"
    return c


@pytest.fixture
def web():
    return FakeWeb()


@pytest.fixture
def telegram():
    return FakeTelegram()
