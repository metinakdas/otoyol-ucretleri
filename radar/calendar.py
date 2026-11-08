"""Bayram ve yılbaşı gibi bilinen dönemler için izleme kayıtları."""

from __future__ import annotations

from datetime import datetime, time, timedelta

from .config import Config, Period
from .lifecycle import _history
from .matching import KIND_FREE, KIND_PRICE
from .timeutil import TZ, fmt_date, to_iso


def watch_start(p: Period) -> datetime:
    return datetime.combine(p.start - timedelta(days=p.watch_days), time(0, 0), tzinfo=TZ)


def in_watch(p: Period, now: datetime) -> bool:
    return watch_start(p) <= now and now.date() <= p.end


def upcoming(cfg: Config, now: datetime, limit: int = 4) -> list[Period]:
    items = [p for p in cfg.periods if p.end >= now.date()]
    return sorted(items, key=lambda p: p.start)[:limit]


def ensure_watch_events(events: dict, cfg: Config, now: datetime) -> list[dict]:
    """İzleme dönemine giren her dönem için bir kez "Sinyal" kaydı açar."""
    created = []
    for p in cfg.periods:
        if not in_watch(p, now):
            continue
        eid = f"takvim-{p.id}"
        if eid in events:
            continue
        # Bu dönem için karar zaten geldiyse ayrıca izleme kaydı açma
        if any(e.get("period_id") == p.id and e["status"] not in ("kapandi", "iptal_ertelendi") for e in events.values()):
            continue
        kind = KIND_FREE if p.kind == "bayram" else KIND_PRICE
        what = "ücretsiz geçiş kararı izleniyor" if kind == KIND_FREE else "geçiş ücreti değişikliği izleniyor"
        ev = {
            "id": eid,
            "kind": kind,
            "status": "sinyal",
            "title": f"{p.name} yaklaşıyor ({fmt_date(datetime.combine(p.start, time(0, 0), tzinfo=TZ))}): {what}",
            "crossings": list(cfg.generic_scope),
            "excluded": [],
            "documents": [],
            "prices": {},
            "effective_from": None,
            "effective_to": None,
            "period_id": p.id,
            "flags": ["takvim"],
            "evidence": [],
            "applied": False,
            "created_at": to_iso(now),
            "updated_at": to_iso(now),
            "history": [],
        }
        _history(ev, now, "İzleme dönemi başladı")
        events[eid] = ev
        created.append(ev)
    return created
