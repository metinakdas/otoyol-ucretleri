"""Güvenlik yardımcıları: anahtar maskeleme, güvenli bağlantı adresi, gizli bilgi desenleri.

- Hata mesajları data/ klasörüne (herkese açık depoda herkes görür) ve GitHub Actions günlüklerine
  yazılabilir. Bu yüzden içlerindeki anahtar ve şifreler her zaman "***" ile maskelenir.
- Kaynak sitelerden gelen bağlantılar yalnızca http(s) ise kullanılır; "javascript:" gibi adresler
  panelde ya da bildirimde tıklanabilir hâle gelmez.
"""

from __future__ import annotations

import os
import re
from urllib.parse import urlsplit

MASK = "***"

# .env içinde gizli tutulan değerler (bildirim ayarları)
SECRET_ENV_KEYS = (
    "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "TELEGRAM_TECH_CHAT_ID",
    "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM", "EMAIL_TO",
)

# Depoya hiçbir zaman girmemesi gereken anahtar biçimleri
SECRET_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("Telegram bot anahtarı", re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{30,}\b")),
    ("GitHub anahtarı", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b")),
    ("Özel anahtar", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY")),
    ("AWS erişim anahtarı", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("Slack anahtarı", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    ("Google API anahtarı", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
]


def safe_url(url: str | None) -> str | None:
    """Yalnızca http ve https adreslerini döndürür."""
    if not url:
        return None
    url = str(url).strip()
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https") or not parts.netloc:
        return None
    return url


def secret_values(settings=None) -> list[str]:
    """Maskelenecek değerler: ayarlardaki ve ortamdaki anahtarlar, şifreler, alıcı adresleri."""
    values: list[str] = []
    if settings is not None:
        values += [settings.telegram_token, settings.telegram_chat_id, settings.telegram_tech_chat_id,
                   settings.smtp_password, settings.smtp_user, settings.smtp_from, *settings.email_to]
    values += [os.environ.get(k, "") for k in SECRET_ENV_KEYS]
    out = set()
    for v in values:
        for part in str(v or "").split(","):
            part = part.strip()
            if len(part) >= 5:  # çok kısa değerler (ör. "587") maskelenmez
                out.add(part)
    return sorted(out, key=len, reverse=True)


def redact(text, settings=None) -> str:
    """Metindeki anahtarları, şifreleri ve bilinen anahtar biçimlerini "***" ile değiştirir."""
    text = "" if text is None else str(text)
    for value in secret_values(settings):
        text = text.replace(value, MASK)
    for _, pattern in SECRET_PATTERNS:
        text = pattern.sub(MASK, text)
    return text
