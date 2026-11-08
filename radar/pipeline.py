"""Bir radar turu: kaynakları oku → kayıtları güncelle → bildir → kaydet."""

from __future__ import annotations

import hashlib
import json
import logging
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import httpx

from . import calendar as cal
from . import harita, lifecycle, notify, ucret_tablosu
from . import panel as panel_mod
from . import prices as ledger
from .collectors import Context, collect
from .config import Config
from .fetch import Fetcher
from .guvenlik import redact
from .lifecycle import DECIDED
from .matching import KIND_FREE, Matcher
from .store import Store
from .timeutil import from_iso, hours_since, now as tz_now, to_iso

log = logging.getLogger(__name__)


@dataclass
class RunReport:
    first_run: bool = False
    sources: list[tuple[str, str, str]] = field(default_factory=list)
    candidates: int = 0
    new_events: int = 0
    status_changes: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    written: list[str] = field(default_factory=list)


def _link_period(ev: dict, cfg: Config) -> None:
    """Ücretsiz geçiş kararını tarihine göre bilinen bir bayram dönemine bağlar."""
    if ev["kind"] != KIND_FREE or ev.get("period_id"):
        return
    start = from_iso(ev.get("effective_from"))
    if not start:
        return
    for p in cfg.periods:
        if p.start - timedelta(days=2) <= start.date() <= p.end + timedelta(days=1):
            ev["period_id"] = p.id
            return


def _panel_signature(data: dict) -> str:
    d = deepcopy(data)
    d.pop("last_run", None)
    for s in d.get("sources", []):
        s.pop("last_success", None)
        s.pop("info", None)
    for doc in d.get("documents", []):
        doc.pop("checked_at", None)
    return hashlib.sha256(json.dumps(d, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


def run_once(
    cfg: Config,
    *,
    now: datetime | None = None,
    send: bool = True,
    dry_run: bool = False,
    transport: httpx.BaseTransport | None = None,
    notify_client: httpx.Client | None = None,
) -> RunReport:
    now = now or tz_now()
    store = Store(cfg.data_dir)
    report = RunReport(first_run=not store.exists)

    state: dict = store.read("state.json", {})
    health: dict = store.read("health.json", {})
    sent: dict = store.read("notifications.json", {})
    crossings_data: dict = store.read("crossings.json", {})
    meta: dict = store.read("meta.json", {})
    events = store.load_events()
    rules = store.load_rules()

    # 1) Kaynakları oku
    matcher = Matcher(cfg.crossings, cfg.generic_phrases)
    delay = 0 if transport is not None else cfg.settings.request_delay
    fetcher = Fetcher(cfg.settings.user_agent, min_delay=delay, transport=transport)
    ctx = Context(cfg=cfg, matcher=matcher, fetcher=fetcher, now=now, crossings_data=crossings_data, notes=report.notes)
    candidates = []
    health_changed = False
    try:
        for src in cfg.sources:
            if not src.enabled:
                continue
            st = state.setdefault(src.id, {})
            h = health.setdefault(src.id, {})
            was_ok = h.get("ok")
            try:
                result = collect(src, st, ctx)
                candidates.extend(result.candidates)
                h.update(ok=True, last_success=to_iso(now), info=result.info)
                h.pop("error", None)
                h.pop("failing_since", None)
                report.sources.append((src.id, "tamam", result.info))
            except Exception as exc:
                log.debug("Kaynak hatası %s", src.id, exc_info=True)
                h["ok"] = False
                h["error"] = redact(exc, cfg.settings)[:500]
                h.setdefault("failing_since", to_iso(now))
                report.sources.append((src.id, "HATA", h["error"][:200]))
            if h.get("ok") != was_ok:
                health_changed = True
    finally:
        fetcher.close()
    report.candidates = len(candidates)

    # 1b) Harita: otoyol gişelerinin konumları (ayda bir). Hata radarın asıl işini etkilemez.
    if not dry_run:
        note = harita.refresh(cfg, store, state, now, transport=transport)
        if note:
            report.notes.append(note)
            if not note.startswith("Harita verisi alınamadı"):
                report.written.append("harita.json")
        # Gişeden gişeye ücret tabloları (günde bir ya da tarife belgesi değişince). Hata asıl işi etkilemez.
        try:
            note = ucret_tablosu.refresh(cfg, store, state, now, transport=transport)
        except Exception as exc:  # beklenmeyen hata da radar turunu durdurmasın
            log.debug("Ücret tablosu hatası", exc_info=True)
            note = f"Ücret tablosu alınamadı: {redact(exc, cfg.settings)[:200]}"
        if note:
            report.notes.append(note)
            if note.startswith("Ücret tablosu:") and "güncellendi" in note:
                report.written.append(ucret_tablosu.DOSYA)

    # 2) Takvim ve kayıtlar
    created_watch = cal.ensure_watch_events(events, cfg, now)
    for cand in candidates:
        if cand.cancel:
            target = lifecycle.find_match(events, cand, now, statuses=("sinyal", "gundemde", "karar_cikti", "yururlukte"))
            if target and lifecycle.cancel_event(target, cand, crossings_data, rules, now):
                report.status_changes.append(f"İptal/erteleme: {target['title']}")
            continue
        if not cand.kind:
            continue
        ev = lifecycle.find_match(events, cand, now)
        if ev is None:
            ev = lifecycle.new_event(cand, now)
            events[ev["id"]] = ev
            report.new_events += 1
        lifecycle.merge(ev, cand, now)
        _link_period(ev, cfg)

    for ev in events.values():
        before = ev["status"]
        if lifecycle.promote(ev, now):
            report.status_changes.append(f"{lifecycle.label(before)} → {lifecycle.label(ev['status'])}: {ev['title']}")
        if ev["status"] in DECIDED and not ev.get("applied"):
            report.notes.extend(lifecycle.apply_decision(ev, cfg, crossings_data, rules, now))
    transitions = lifecycle.advance(events, cfg, now)
    for ev, kind in transitions:
        report.status_changes.append(f"{kind}: {ev['title']}")

    # 3) Bildirimler
    n_prices = sum(1 for c in cfg.crossings if ledger.entries(crossings_data, c.id))
    messages = notify.plan(cfg, events, transitions, created_watch, health, sent, now,
                           first_run=report.first_run, n_prices=n_prices, notes=report.notes)
    if send or dry_run:
        report.messages = notify.deliver(cfg, messages, sent, now, dry_run=dry_run, client=notify_client)
    else:
        report.messages = [f"[bildirim kapalı] {m.subject}" for m in messages if m.channels]

    if dry_run:
        return report

    # 4) Kaydet (yalnızca değişen dosyalar yazılır)
    for name, data in (("state.json", state), ("crossings.json", crossings_data), ("notifications.json", sent)):
        if store.write(name, data):
            report.written.append(name)
    if store.save_events(events):
        report.written.append("events/")
    if store.save_rules(rules):
        report.written.append("rules/")

    panel_data = panel_mod.build(cfg, events=events, rules=rules, crossings_data=crossings_data,
                                 state=state, health=health, now=now, last_run=to_iso(now),
                                 map_info=harita.panel_info(state))
    signature = _panel_signature(panel_data)
    heartbeat_due = hours_since(meta.get("heartbeat_at"), now) * 60 >= cfg.settings.heartbeat_minutes
    if heartbeat_due or health_changed or signature != meta.get("panel_signature") or report.written:
        store.write("health.json", health)
        store.write("panel.json", panel_data)
        meta.update(heartbeat_at=to_iso(now), panel_signature=signature)
        store.write("meta.json", meta)
        report.written.append("panel.json")
    return report
