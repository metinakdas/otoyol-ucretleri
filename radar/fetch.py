"""Nazik HTTP istemcisi: robots.txt'e uyar, aynı siteye istekleri aralıklı gönderir, koşullu GET kullanır."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

log = logging.getLogger(__name__)


class FetchError(Exception):
    pass


@dataclass
class FetchResult:
    url: str
    final_url: str
    status: int
    content: bytes = b""
    headers: dict = field(default_factory=dict)
    not_modified: bool = False
    encoding: str | None = None

    @property
    def text(self) -> str:
        """Başlıkta karakter seti varsa onu, yoksa UTF-8'i, o da olmazsa Windows-1254'ü (Türkçe) dener."""
        if self.encoding:
            try:
                return self.content.decode(self.encoding)
            except (LookupError, UnicodeDecodeError):
                pass
        try:
            return self.content.decode("utf-8")
        except UnicodeDecodeError:
            return self.content.decode("windows-1254", errors="replace")

    @property
    def content_type(self) -> str:
        return (self.headers.get("content-type") or "").split(";")[0].strip().lower()

    @property
    def is_pdf(self) -> bool:
        return self.content_type == "application/pdf" or self.content[:5] == b"%PDF-"


class Fetcher:
    def __init__(
        self,
        user_agent: str,
        *,
        timeout: float = 30.0,
        min_delay: float = 2.0,
        retries: int = 2,
        respect_robots: bool = True,
        transport: httpx.BaseTransport | None = None,
        max_bytes: int = 15_000_000,
    ):
        self.client = httpx.Client(
            headers={
                "User-Agent": user_agent,
                "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.5",
            },
            timeout=timeout,
            follow_redirects=True,
            transport=transport,
        )
        self.user_agent = user_agent
        self.min_delay = min_delay
        self.retries = retries
        self.respect_robots = respect_robots
        self.max_bytes = max_bytes
        self._last_request: dict[str, float] = {}
        self._robots: dict[str, RobotFileParser | None] = {}

    def close(self) -> None:
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # -- yardımcılar --------------------------------------------------------

    def _wait_turn(self, host: str) -> None:
        last = self._last_request.get(host)
        if last is not None and self.min_delay > 0:
            remaining = self.min_delay - (time.monotonic() - last)
            if remaining > 0:
                time.sleep(remaining)
        self._last_request[host] = time.monotonic()

    def allowed(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        parsed = urlparse(url)
        host = f"{parsed.scheme}://{parsed.netloc}"
        if host not in self._robots:
            parser: RobotFileParser | None = None
            try:
                self._wait_turn(parsed.netloc)
                resp = self.client.get(host + "/robots.txt")
                if resp.status_code == 200 and "text" in resp.headers.get("content-type", "text"):
                    parser = RobotFileParser()
                    parser.parse(resp.text.splitlines())
            except httpx.HTTPError as exc:
                log.debug("robots.txt okunamadı (%s): %s", host, exc)
            self._robots[host] = parser
        parser = self._robots[host]
        return True if parser is None else parser.can_fetch(self.user_agent, url)

    # -- ana işlev ----------------------------------------------------------

    def get(self, url: str, *, etag: str | None = None, last_modified: str | None = None,
            headers: dict | None = None) -> FetchResult:
        if not self.allowed(url):
            raise FetchError(f"robots.txt bu adrese erişime izin vermiyor: {url}")
        headers = dict(headers or {})
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified
        host = urlparse(url).netloc
        last_exc: Exception | None = None
        for attempt in range(self.retries + 1):
            self._wait_turn(host)
            try:
                resp = self.client.get(url, headers=headers)
            except httpx.HTTPError as exc:
                last_exc = exc
                log.debug("İstek hatası (%s, deneme %d): %s", url, attempt + 1, exc)
                if attempt < self.retries and self.min_delay > 0:
                    time.sleep(self.min_delay * (attempt + 1))
                continue
            if resp.status_code == 304:
                return FetchResult(url=url, final_url=str(resp.url), status=304,
                                   headers=dict(resp.headers), not_modified=True)
            if resp.status_code >= 500 and attempt < self.retries:
                last_exc = FetchError(f"Sunucu hatası {resp.status_code}")
                if self.min_delay > 0:
                    time.sleep(self.min_delay * (attempt + 1))
                continue
            if resp.status_code >= 400:
                raise FetchError(f"HTTP {resp.status_code}: {url}")
            content = resp.content
            if len(content) > self.max_bytes:
                raise FetchError(f"Yanıt çok büyük ({len(content)} bayt): {url}")
            ctype = resp.headers.get("content-type", "")
            charset = None
            if "charset=" in ctype.lower():
                charset = ctype.lower().split("charset=", 1)[1].split(";")[0].strip().strip('"') or None
            return FetchResult(
                url=url,
                final_url=str(resp.url),
                status=resp.status_code,
                content=content,
                headers={k.lower(): v for k, v in resp.headers.items()},
                encoding=charset,
            )
        raise FetchError(f"Erişilemedi: {url} ({last_exc})")
