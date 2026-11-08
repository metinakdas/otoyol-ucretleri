"""Kayıtların yaşam döngüsü.

Sinyal → Gündemde → Karar çıktı → Yürürlükte
Sinyal/Gündemde → Kapandı (teyit gelmedi)    Karar çıktı → İptal / ertelendi

Onay adımı yoktur. Bir kayıt ancak resmi kaynakta ya da aynı tarihi veren iki bağımsız
haberde görülürse "Karar çıktı" olur ve o anda ücret kaydı ya da ücretsiz geçiş kuralı yazılır.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, time, timedelta

from . import prices as ledger
from .config import Config, Period
from .matching import KIND_FREE, KIND_PRICE
from .models import OPEN, RANK, STATUS_LABELS, Candidate
from .textutil import short_hash, slugify
from .timeutil import TZ, from_iso, to_iso

DECIDED = ("karar_cikti", "yururlukte")


def _add_flag(ev: dict, flag: str) -> None:
    if flag not in ev["flags"]:
        ev["flags"].append(flag)


def _drop_flag(ev: dict, flag: str) -> None:
    if flag in ev["flags"]:
        ev["flags"].remove(flag)


def _history(ev: dict, now: datetime, note: str) -> None:
    ev["history"].append({"at": to_iso(now), "status": ev["status"], "note": note})


def set_status(ev: dict, status: str, now: datetime, note: str) -> None:
    if ev["status"] == status:
        return
    ev["status"] = status
    ev["updated_at"] = to_iso(now)
    _history(ev, now, note)


def new_event(cand: Candidate, now: datetime) -> dict:
    scope = "-".join(cand.crossings[:2]) or (cand.documents[0] if cand.documents else "genel")
    kind_short = "ucretsiz" if cand.kind == KIND_FREE else "ucret"
    eid = f"{now:%Y%m%d}-{kind_short}-{slugify(scope, 40)}-{short_hash(cand.url + cand.title + now.isoformat(), 6)}"
    ev = {
        "id": eid,
        "kind": cand.kind,
        "status": "sinyal",
        "title": cand.title,
        "crossings": list(cand.crossings),
        "excluded": list(cand.excluded),
        "documents": list(cand.documents),
        "prices": {},
        "effective_from": to_iso(cand.effective_from),
        "effective_to": to_iso(cand.effective_to),
        "period_id": None,
        "flags": [],
        "evidence": [],
        "applied": False,
        "created_at": to_iso(now),
        "updated_at": to_iso(now),
        "history": [],
    }
    _history(ev, now, "Kayıt açıldı")
    return ev


def _evidence(cand: Candidate, now: datetime) -> dict:
    return {
        "source_id": cand.source_id,
        "tier": cand.tier,
        "url": cand.url,
        "publisher": cand.publisher,
        "title": cand.title,
        "quote": cand.quote,
        "published": cand.published,
        "effective_from": to_iso(cand.effective_from),
        "effective_to": to_iso(cand.effective_to),
        "cancel": cand.cancel,
        "seen_at": to_iso(now),
    }


def _overlap(ev: dict, cand: Candidate) -> bool:
    if set(ev.get("crossings") or []) & set(cand.crossings):
        return True
    return bool(set(ev.get("documents") or []) & set(cand.documents))


def find_match(events: dict, cand: Candidate, now: datetime, statuses=OPEN) -> dict | None:
    best = None
    for ev in events.values():
        if ev["status"] not in statuses:
            continue
        if cand.kind and ev["kind"] != cand.kind:
            continue
        if not _overlap(ev, cand):
            continue
        if now - from_iso(ev["created_at"]) > timedelta(days=60):
            continue
        ev_from = from_iso(ev.get("effective_from"))
        if ev_from and cand.effective_from and abs(ev_from - cand.effective_from) > timedelta(days=1):
            # Takvim kaydı bir dönemi bekler; karar o dönem içinde kalıyorsa eşleşir
            if "takvim" not in ev["flags"]:
                continue
        if best is None or ev["updated_at"] > best["updated_at"]:
            best = ev
    return best


def merge(ev: dict, cand: Candidate, now: datetime) -> bool:
    """Adayı mevcut kayda ekler. Yeni bilgi geldiyse True."""
    urls = {e["url"] for e in ev["evidence"]}
    if cand.url in urls and not cand.documents:
        return False
    ev["evidence"].append(_evidence(cand, now))

    # Kapsam: belirli geçiş adı içeren aday, genel ifadeden gelen kapsamın yerine geçer
    if cand.crossings and not cand.generic and ("kapsam_kontrol" in ev["flags"] or "takvim" in ev["flags"]):
        ev["crossings"] = list(cand.crossings)
        _drop_flag(ev, "kapsam_kontrol")
    else:
        ev["crossings"] = list(dict.fromkeys(ev["crossings"] + cand.crossings))
    ev["excluded"] = list(dict.fromkeys(ev["excluded"] + cand.excluded))
    ev["crossings"] = [c for c in ev["crossings"] if c not in ev["excluded"]]
    ev["documents"] = list(dict.fromkeys(ev.get("documents", []) + cand.documents))
    for cid, classes in cand.prices.items():
        ev["prices"].setdefault(cid, {})["new"] = classes

    old_from = from_iso(ev.get("effective_from"))
    if cand.effective_from and (old_from is None or cand.tier == "resmi"):
        if old_from and abs(old_from - cand.effective_from) > timedelta(minutes=1) and ev["status"] in DECIDED:
            _add_flag(ev, "tarih_degisti")
            _history(ev, now, f"Yürürlük tarihi güncellendi: {to_iso(cand.effective_from)}")
            ev["applied"] = False  # yeni tarihle yeniden uygulanacak
        ev["effective_from"] = to_iso(cand.effective_from)
    if cand.effective_to and (ev.get("effective_to") is None or cand.tier == "resmi"):
        ev["effective_to"] = to_iso(cand.effective_to)

    for flag in cand.flags:
        _add_flag(ev, flag)
    if ev.get("effective_from"):
        _drop_flag(ev, "tarih_belirsiz")
    if ev["prices"] and all(p.get("new") for p in ev["prices"].values()) and cand.prices:
        _drop_flag(ev, "degerler_okunamadi")
    if cand.tier == "resmi" and cand.title:
        ev["title"] = cand.title
        _drop_flag(ev, "takvim")  # artık takvim uyarısı değil, resmi bilgi var
    ev["updated_at"] = to_iso(now)
    return True


def _has_specifics(ev: dict) -> bool:
    if ev["kind"] == KIND_PRICE:
        return bool(ev["prices"] or ev.get("effective_from") or ev.get("documents"))
    return bool(ev.get("effective_from") or ev.get("period_id"))


def target_status(ev: dict) -> str:
    official = [e for e in ev["evidence"] if e["tier"] == "resmi"]
    news = [e for e in ev["evidence"] if e["tier"] == "haber"]
    publishers = {e["publisher"] for e in news if e.get("publisher")}
    specific = _has_specifics(ev)
    if official and specific:
        return "karar_cikti"
    if official:
        return "gundemde"
    if len(publishers) >= 2:
        dates = Counter((e.get("effective_from") or "")[:10] for e in news if e.get("effective_from"))
        agreeing = dates.most_common(1)[0][1] if dates else 0
        if specific and agreeing >= 2:
            return "karar_cikti"
        return "gundemde"
    return "sinyal"


def promote(ev: dict, now: datetime) -> bool:
    """Durumu yalnızca ileri taşır. Değiştiyse True."""
    if ev["status"] not in OPEN:
        return False
    target = target_status(ev)
    if RANK[target] > RANK[ev["status"]]:
        notes = {"gundemde": "Gündeme geldi", "karar_cikti": "Karar çıktı"}
        set_status(ev, target, now, notes.get(target, target))
        return True
    return False


# ---------------------------------------------------------------------------
# Karar uygulama: ücret kayıtları ve ücretsiz geçiş kuralları
# ---------------------------------------------------------------------------

def _period_window(period: Period) -> tuple[datetime, datetime]:
    start = datetime.combine(period.start, time(0, 0), tzinfo=TZ)
    end = datetime.combine(period.end, time(23, 59, 59), tzinfo=TZ)
    return start, end


def apply_decision(ev: dict, cfg: Config, crossings_data: dict, rules: dict, now: datetime) -> list[str]:
    """Karar çıkmış bir kaydı veriye işler. Notlar döndürür."""
    if ev["status"] not in DECIDED or ev.get("applied"):
        return []
    notes: list[str] = []
    if ev["kind"] == KIND_PRICE:
        # Tarih değiştiyse bu karar için daha önce yazılmış ileri tarihli kayıtları geri al
        ledger.remove_event_entries(crossings_data, ev["id"], now)
        valid_from = from_iso(ev.get("effective_from"))
        if valid_from is None:
            valid_from = now
            _add_flag(ev, "tarih_belirsiz")
        for cid, change in ev["prices"].items():
            new = change.get("new")
            if not new:
                continue
            current = ledger.entry_at(crossings_data, cid, valid_from) or ledger.latest_entry(crossings_data, cid)
            if current:
                change["old"] = current["classes"]
                ratio = ledger.change_ratio(current["classes"], new)
                if ratio is not None and (ratio < 0 or ratio > cfg.settings.unusual_increase_pct):
                    _add_flag(ev, "olagan_disi")
                    _add_flag(ev, "kontrol_et")
            if ledger.add_entry(crossings_data, cid, cfg.crossing_name(cid), valid_from, new,
                                source_url=ev["evidence"][-1]["url"] if ev["evidence"] else "",
                                event_id=ev["id"], note=ev["title"]):
                notes.append(f"Ücret kaydı eklendi: {cfg.crossing_name(cid)}")
        if valid_from < now - timedelta(hours=1):
            _add_flag(ev, "kacirildi")
    else:
        start = from_iso(ev.get("effective_from"))
        end = from_iso(ev.get("effective_to"))
        period = next((p for p in cfg.periods if p.id == ev.get("period_id")), None)
        if (start is None or end is None) and period:
            p_start, p_end = _period_window(period)
            start = start or p_start
            end = end or p_end
            _add_flag(ev, "saat_kontrol")
            ev["effective_from"] = to_iso(start)
            ev["effective_to"] = to_iso(end)
        if start is None:
            return notes
        rule_id = f"kural-{ev['id']}"
        rules[rule_id] = {
            "id": rule_id,
            "event_id": ev["id"],
            "title": ev["title"],
            "crossings": [c for c in ev["crossings"] if c not in ev["excluded"]],
            "excluded": ev["excluded"],
            "valid_from": to_iso(start),
            "valid_to": to_iso(end),
            "fee": 0,
            "cancelled": False,
            "flags": list(ev["flags"]),
            "source_url": ev["evidence"][-1]["url"] if ev["evidence"] else "",
        }
        notes.append(f"Ücretsiz geçiş kuralı yazıldı: {ev['title']}")
        if start < now - timedelta(hours=1):
            _add_flag(ev, "kacirildi")
    ev["applied"] = True
    return notes


def cancel_event(ev: dict, cand: Candidate, crossings_data: dict, rules: dict, now: datetime) -> bool:
    """Resmi kaynaktan gelen iptal/erteleme haberini kayda işler."""
    ev["evidence"].append(_evidence(cand, now))
    ev["updated_at"] = to_iso(now)
    if cand.tier != "resmi":
        publishers = {e["publisher"] for e in ev["evidence"] if e["tier"] == "haber" and e.get("cancel")}
        _add_flag(ev, "iptal_iddiasi")
        if len(publishers) < 2:
            return False
    set_status(ev, "iptal_ertelendi", now, "İptal edildi ya da ertelendi")
    ledger.remove_event_entries(crossings_data, ev["id"], now)
    for rule in rules.values():
        if rule["event_id"] == ev["id"]:
            rule["cancelled"] = True
    return True


# ---------------------------------------------------------------------------
# Zamana bağlı geçişler
# ---------------------------------------------------------------------------

def advance(events: dict, cfg: Config, now: datetime) -> list[tuple[dict, str]]:
    """Zaman geçtikçe değişen durumlar. (kayıt, geçiş türü) listesi döndürür."""
    out: list[tuple[dict, str]] = []
    close_after = timedelta(days=cfg.settings.signal_close_days)
    periods = {p.id: p for p in cfg.periods}
    for ev in events.values():
        status = ev["status"]
        start = from_iso(ev.get("effective_from"))
        end = from_iso(ev.get("effective_to"))
        if status == "karar_cikti" and start and start <= now:
            set_status(ev, "yururlukte", now, "Yürürlüğe girdi")
            out.append((ev, "yururlukte"))
        if ev["status"] == "yururlukte" and ev["kind"] == KIND_FREE and end and end < now and "sona_erdi" not in ev["flags"]:
            _add_flag(ev, "sona_erdi")
            ev["updated_at"] = to_iso(now)
            out.append((ev, "sona_erdi"))
        if status in ("sinyal", "gundemde"):
            if "takvim" in ev["flags"]:
                period = periods.get(ev.get("period_id"))
                if period and now.date() > period.end:
                    set_status(ev, "kapandi", now, "Dönem bitti, karar çıkmadı")
                    out.append((ev, "kapandi"))
            else:
                last = max(from_iso(e["seen_at"]) for e in ev["evidence"]) if ev["evidence"] else from_iso(ev["created_at"])
                if now - last > close_after:
                    set_status(ev, "kapandi", now, f"{cfg.settings.signal_close_days} gün içinde teyit gelmedi")
                    out.append((ev, "kapandi"))
    return out


def label(status: str) -> str:
    return STATUS_LABELS.get(status, status)
