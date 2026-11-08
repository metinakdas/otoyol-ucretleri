"""Saat dilimi ve tarih biçimlendirme yardımcıları. Tüm zamanlar İstanbul saatiyle tutulur."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Istanbul")

MONTHS_TR = [
    "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
    "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık",
]


def now() -> datetime:
    return datetime.now(TZ)


def aware(dt: datetime) -> datetime:
    """Saat dilimi olmayan tarihi İstanbul saati kabul eder."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=TZ)
    return dt.astimezone(TZ)


def to_iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return aware(dt).isoformat(timespec="seconds")


def from_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    return aware(datetime.fromisoformat(value))


def fmt_date(dt: datetime | None) -> str:
    if dt is None:
        return "belirsiz"
    dt = aware(dt)
    return f"{dt.day} {MONTHS_TR[dt.month - 1]} {dt.year}"


def fmt_datetime(dt: datetime | None) -> str:
    if dt is None:
        return "belirsiz"
    dt = aware(dt)
    return f"{fmt_date(dt)} {dt:%H:%M}"


def days_until(target: datetime, ref: datetime) -> int:
    """Takvim günü farkı (bugün = 0)."""
    return (aware(target).date() - aware(ref).date()).days


def hours_since(value: str | None, ref: datetime) -> float:
    dt = from_iso(value)
    if dt is None:
        return float("inf")
    return (ref - dt) / timedelta(hours=1)


def relative_days(target: datetime, ref: datetime) -> str:
    d = days_until(target, ref)
    if d == 0:
        return "bugün"
    if d == 1:
        return "yarın"
    if d > 1:
        return f"{d} gün sonra"
    if d == -1:
        return "dün"
    return f"{-d} gün önce"
