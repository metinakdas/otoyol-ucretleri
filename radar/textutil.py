"""Türkçe metin yardımcıları: büyük/küçük harf, karakter katlama, kısaltma."""

from __future__ import annotations

import hashlib
import re
import unicodedata

_TR_LOWER = str.maketrans({"I": "ı", "İ": "i"})
_ASCII_FOLD = str.maketrans({
    "ç": "c", "ğ": "g", "ı": "i", "ö": "o", "ş": "s", "ü": "u",
    "â": "a", "î": "i", "û": "u",
})
_ZERO_WIDTH = re.compile("[\u200b-\u200f\u2060\ufeff\u00ad]")  # sıfır genişlikli ve yön karakterleri
_SPACES = re.compile(r"\s+")


def tr_lower(text: str) -> str:
    """Türkçe kurallarla küçük harf (I → ı, İ → i)."""
    return text.translate(_TR_LOWER).lower()


def clean_spaces(text: str | None) -> str:
    if not text:
        return ""
    text = _ZERO_WIDTH.sub("", text)
    return _SPACES.sub(" ", text).strip()


def fold(text: str | None) -> str:
    """Karşılaştırma biçimi: küçük harf, Türkçe karakterler ASCII, tek boşluk.

    "Boğaziçi KÖPRÜSÜ" ve "bogazici koprusu" aynı sonucu verir.
    """
    if not text:
        return ""
    t = _ZERO_WIDTH.sub("", text)
    t = unicodedata.normalize("NFC", t)
    t = tr_lower(t)
    t = t.replace("\u0307", "")  # birleşik üst nokta (İ küçültülünce oluşur)
    t = t.translate(_ASCII_FOLD)
    t = t.replace("’", "'").replace("‘", "'").replace("`", "'")
    return _SPACES.sub(" ", t).strip()


def slugify(text: str, max_len: int = 80) -> str:
    t = fold(text)
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
    return t[:max_len].strip("-") or "kayit"


def short_hash(text: str, n: int = 12) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:n]


def shorten(text: str, limit: int = 280) -> str:
    text = clean_spaces(text)
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut + " …"


def sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?;])\s+|\n+", text)
    return [p.strip() for p in parts if p and p.strip()]
