"""Geçiş ücreti kayıtları (data/crossings.json).

Her geçiş için tarihli ücret kayıtları tutulur. Bir kayıt silinmez; yenisi eklenince öncekinin
bitiş zamanı doldurulur. Böylece geçmiş bir yolculuğun hangi ücretle hesaplandığı hep bulunur.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from .timeutil import from_iso, to_iso


def _classes(classes: dict) -> dict[str, str]:
    return {str(k): str(Decimal(str(v)).quantize(Decimal("0.01"))) for k, v in sorted(classes.items(), key=lambda kv: int(kv[0]))}


def entries(data: dict, crossing_id: str) -> list[dict]:
    return data.get(crossing_id, {}).get("prices", [])


def entry_at(data: dict, crossing_id: str, at: datetime) -> dict | None:
    for e in entries(data, crossing_id):
        start = from_iso(e["valid_from"])
        end = from_iso(e.get("valid_to"))
        if start <= at and (end is None or at <= end):
            return e
    return None


def latest_entry(data: dict, crossing_id: str) -> dict | None:
    items = entries(data, crossing_id)
    return items[-1] if items else None


def upcoming_entry(data: dict, crossing_id: str, at: datetime) -> dict | None:
    future = [e for e in entries(data, crossing_id) if from_iso(e["valid_from"]) > at]
    return future[0] if future else None


def same_classes(a: dict | None, b: dict | None) -> bool:
    if not a or not b:
        return False
    return _classes(a) == _classes(b)


def add_entry(
    data: dict,
    crossing_id: str,
    name: str,
    valid_from: datetime,
    classes: dict,
    *,
    source_url: str = "",
    event_id: str | None = None,
    note: str = "",
) -> bool:
    """Yeni ücret kaydı ekler. Aynı başlangıçlı kayıt varsa günceller. Değişiklik olduysa True."""
    record = data.setdefault(crossing_id, {"name": name, "prices": []})
    record["name"] = name
    items: list[dict] = record["prices"]
    new = {
        "valid_from": to_iso(valid_from),
        "valid_to": None,
        "classes": _classes(classes),
        "source_url": source_url,
        "event_id": event_id,
        "note": note,
    }
    for e in items:
        if from_iso(e["valid_from"]) == valid_from:
            if e["classes"] == new["classes"]:
                return False
            new["valid_to"] = e.get("valid_to")
            e.update(new)
            return True
    # Yeni kaydın başladığı anda geçerli olan kaydı kapat
    for e in items:
        start, end = from_iso(e["valid_from"]), from_iso(e.get("valid_to"))
        if start < valid_from and (end is None or end >= valid_from):
            e["valid_to"] = to_iso(valid_from - timedelta(seconds=1))
    # Sonraki bir kayıt varsa yeni kayıt onun başlangıcında biter
    later = sorted((from_iso(e["valid_from"]) for e in items if from_iso(e["valid_from"]) > valid_from))
    if later:
        new["valid_to"] = to_iso(later[0] - timedelta(seconds=1))
    items.append(new)
    items.sort(key=lambda e: from_iso(e["valid_from"]))
    return True


def remove_event_entries(data: dict, event_id: str, after: datetime) -> list[str]:
    """İptal edilen bir karar için henüz başlamamış ücret kayıtlarını geri alır."""
    touched = []
    for crossing_id, record in data.items():
        items = record.get("prices", [])
        keep = [e for e in items if not (e.get("event_id") == event_id and from_iso(e["valid_from"]) > after)]
        if len(keep) != len(items):
            # Önceki kaydı yeniden açık uçlu yap
            if keep:
                last = keep[-1]
                nxt = [e for e in keep if from_iso(e["valid_from"]) > from_iso(last["valid_from"])]
                if not nxt:
                    last["valid_to"] = None
            record["prices"] = keep
            touched.append(crossing_id)
    return touched


def change_ratio(old: dict | None, new: dict | None, cls: str = "1") -> float | None:
    try:
        o = Decimal(str(old[cls]))
        n = Decimal(str(new[cls]))
    except (KeyError, TypeError):
        return None
    if o == 0:
        return None
    return float((n - o) / o * 100)
