"""Bildirim metinleri (Telegram HTML ve e-posta)."""

from __future__ import annotations

import html
from datetime import datetime
from decimal import Decimal

from .config import Config
from .guvenlik import safe_url
from .matching import KIND_FREE
from .models import FLAG_LABELS, STATUS_LABELS
from .timeutil import days_until, fmt_date, fmt_datetime, from_iso, relative_days

FLAG_NOTES = {
    "degerler_okunamadi": "Ücretler kaynaktan okunamadı; belgeyi kontrol edin.",
    "tarih_belirsiz": "Yürürlük tarihi okunamadı; kaynağı kontrol edin.",
    "kapsam_kontrol": "Kapsam genel ifadeyle duyuruldu; hangi geçişlerin dahil olduğunu kaynaktan kontrol edin.",
    "saat_kontrol": "Başlangıç ve bitiş saatleri okunamadı; bayram günleri varsayıldı.",
    "olagan_disi": "Ücret değişimi olağan dışı (düşüş ya da çok yüksek artış).",
    "kontrol_et": "Okunan değerleri kaynakla karşılaştırın.",
}


def esc(text: str | None) -> str:
    return html.escape(text or "", quote=False)


def money(value: str | None) -> str:
    if value is None:
        return "?"
    d = Decimal(str(value)).quantize(Decimal("0.01"))
    whole, frac = f"{d:.2f}".split(".")
    groups = []
    while len(whole) > 3:
        groups.insert(0, whole[-3:])
        whole = whole[:-3]
    groups.insert(0, whole)
    return ".".join(groups) + "," + frac + " TL"


def names(cfg: Config, ids: list[str]) -> str:
    return ", ".join(cfg.crossing_name(i) for i in ids) or "—"


class Text:
    """Telegram (HTML) ve düz metin satırlarını birlikte üretir."""

    def __init__(self):
        self.html: list[str] = []
        self.plain: list[str] = []

    def line(self, html_text: str, plain_text: str | None = None) -> "Text":
        self.html.append(html_text)
        self.plain.append(plain_text if plain_text is not None else html.unescape(_strip_tags(html_text)))
        return self

    def blank(self) -> "Text":
        return self.line("", "")

    def render(self) -> tuple[str, str]:
        return "\n".join(self.html).strip(), "\n".join(self.plain).strip()


def _strip_tags(s: str) -> str:
    import re
    return re.sub(r"<[^>]+>", "", s)


def _link(url: str, label: str) -> str:
    url = safe_url(url)
    return f'<a href="{esc(url)}">{esc(label)}</a>' if url else esc(label)


def _change_lines(t: Text, cfg: Config, ev: dict) -> None:
    if ev["kind"] == KIND_FREE:
        t.line(f"Kapsamda: {esc(names(cfg, ev['crossings']))}")
        if ev.get("excluded"):
            t.line(f"Kapsam dışı: {esc(names(cfg, ev['excluded']))}")
        start, end = from_iso(ev.get("effective_from")), from_iso(ev.get("effective_to"))
        t.line(f"Başlangıç: {fmt_datetime(start)}   Bitiş: {fmt_datetime(end)}")
        return
    shown = 0
    for cid, change in ev.get("prices", {}).items():
        new = (change.get("new") or {}).get("1")
        old = (change.get("old") or {}).get("1")
        if new is None:
            continue
        if old is not None:
            t.line(f"{esc(cfg.crossing_name(cid))}, 1. sınıf: {money(old)} → <b>{money(new)}</b>",
                   f"{cfg.crossing_name(cid)}, 1. sınıf: {money(old)} → {money(new)}")
        else:
            t.line(f"{esc(cfg.crossing_name(cid))}, 1. sınıf: <b>{money(new)}</b>",
                   f"{cfg.crossing_name(cid)}, 1. sınıf: {money(new)}")
        shown += 1
    if not shown and ev.get("crossings"):
        t.line(f"Geçişler: {esc(names(cfg, ev['crossings']))}")
    extra_docs = len(ev.get("documents") or [])
    if extra_docs and extra_docs > shown:
        t.line(f"Değişen tarife belgesi: {extra_docs} (tümü panelde)")


def _footer(t: Text, cfg: Config, ev: dict) -> None:
    for flag in ev.get("flags", []):
        if flag in FLAG_NOTES:
            t.line(f"<i>Not: {esc(FLAG_NOTES[flag])}</i>", f"Not: {FLAG_NOTES[flag]}")
    if ev.get("evidence"):
        last = ev["evidence"][-1]
        t.line(f"Kaynak: {_link(last['url'], last.get('publisher') or 'kaynak')}",
               f"Kaynak: {last['url']}")
    if cfg.settings.panel_url:
        t.line(_link(cfg.settings.panel_url, "Panelde aç"), f"Panel: {cfg.settings.panel_url}")


def decision(cfg: Config, ev: dict, now: datetime) -> tuple[str, str, str]:
    urgent = "kacirildi" in ev.get("flags", [])
    head = "ACİL · KAÇIRILDI" if urgent else "KARAR ÇIKTI"
    t = Text().line(f"<b>[{head}] {esc(ev['title'])}</b>", f"[{head}] {ev['title']}")
    _change_lines(t, cfg, ev)
    eff = from_iso(ev.get("effective_from"))
    if ev["kind"] != KIND_FREE:
        t.line(f"Yürürlük: <b>{fmt_datetime(eff)}</b>" + (f" ({relative_days(eff, now)})" if eff else ""),
               f"Yürürlük: {fmt_datetime(eff)}" + (f" ({relative_days(eff, now)})" if eff else ""))
    if urgent:
        t.line("<b>Yürürlük anı geçmiş; ilgili taksimetreleri hemen kontrol edin.</b>",
               "Yürürlük anı geçmiş; ilgili taksimetreleri hemen kontrol edin.")
    _footer(t, cfg, ev)
    h, p = t.render()
    return f"[Tarife Radarı] {head}: {ev['title']}", h, p


def reminder(cfg: Config, ev: dict, days: int, now: datetime) -> tuple[str, str, str]:
    eff = from_iso(ev.get("effective_from"))
    head = f"HATIRLATMA · {days} gün kaldı" if days > 1 else "HATIRLATMA · yarın yürürlükte"
    t = Text().line(f"<b>[{head}] {esc(ev['title'])}</b>", f"[{head}] {ev['title']}")
    _change_lines(t, cfg, ev)
    t.line(f"Yürürlük: <b>{fmt_datetime(eff)}</b>", f"Yürürlük: {fmt_datetime(eff)}")
    _footer(t, cfg, ev)
    h, p = t.render()
    return f"[Tarife Radarı] {head}: {ev['title']}", h, p


def in_force(cfg: Config, ev: dict, now: datetime) -> tuple[str, str, str]:
    eff = from_iso(ev.get("effective_from"))
    # Radar bir süre çalışmadıysa geçiş geç fark edilebilir; o zaman "bugün" denmez
    head = "BUGÜN YÜRÜRLÜKTE" if eff is None or days_until(eff, now) == 0 else f"YÜRÜRLÜĞE GİRDİ · {fmt_date(eff)}"
    t = Text().line(f"<b>[{head}] {esc(ev['title'])}</b>", f"[{head}] {ev['title']}")
    _change_lines(t, cfg, ev)
    _footer(t, cfg, ev)
    h, p = t.render()
    return f"[Tarife Radarı] {head}: {ev['title']}", h, p


def ended(cfg: Config, ev: dict, now: datetime) -> tuple[str, str, str]:
    head = "SONA ERDİ"
    t = Text().line(f"<b>[{head}] Ücretsiz geçiş bitti: {esc(ev['title'])}</b>",
                    f"[{head}] Ücretsiz geçiş bitti: {ev['title']}")
    t.line(f"Geçiş ücretleri yeniden alınıyor: {esc(names(cfg, ev['crossings']))}")
    _footer(t, cfg, ev)
    h, p = t.render()
    return f"[Tarife Radarı] {head}: {ev['title']}", h, p


def date_changed(cfg: Config, ev: dict, now: datetime) -> tuple[str, str, str]:
    head = "TARİH DEĞİŞTİ"
    eff = from_iso(ev.get("effective_from"))
    t = Text().line(f"<b>[{head}] {esc(ev['title'])}</b>", f"[{head}] {ev['title']}")
    t.line(f"Yeni yürürlük: <b>{fmt_datetime(eff)}</b>", f"Yeni yürürlük: {fmt_datetime(eff)}")
    _change_lines(t, cfg, ev)
    _footer(t, cfg, ev)
    h, p = t.render()
    return f"[Tarife Radarı] {head}: {ev['title']}", h, p


def cancelled(cfg: Config, ev: dict, now: datetime) -> tuple[str, str, str]:
    head = "İPTAL / ERTELENDİ"
    t = Text().line(f"<b>[{head}] {esc(ev['title'])}</b>", f"[{head}] {ev['title']}")
    t.line("Bu karara göre yapılmış hazırlıkları geri alın; yeni tarih açıklanırsa ayrıca bildirilir.")
    _footer(t, cfg, ev)
    h, p = t.render()
    return f"[Tarife Radarı] {head}: {ev['title']}", h, p


def watch_started(cfg: Config, ev: dict, now: datetime) -> tuple[str, str, str]:
    head = "İZLEME BAŞLADI"
    t = Text().line(f"<b>[{head}] {esc(ev['title'])}</b>", f"[{head}] {ev['title']}")
    t.line("Karar açıklandığında ayrıca bildirilecek.")
    if cfg.settings.panel_url:
        t.line(_link(cfg.settings.panel_url, "Panelde aç"), f"Panel: {cfg.settings.panel_url}")
    h, p = t.render()
    return f"[Tarife Radarı] {head}: {ev['title']}", h, p


def source_error(cfg: Config, name: str, url: str, hours: float, error: str) -> tuple[str, str, str]:
    head = "KAYNAK HATASI"
    t = Text().line(f"<b>[{head}] {esc(name)}</b>", f"[{head}] {name}")
    t.line(f"{int(hours)} saattir okunamıyor.")
    t.line(f"Son hata: <code>{esc(error[:300])}</code>", f"Son hata: {error[:300]}")
    t.line(f"Adres: {_link(url, url)}", f"Adres: {url}")
    t.line("Site yapısı değişmiş ya da erişim engellenmiş olabilir. \"python -m radar kaynak-testi\" ile kontrol edin.")
    h, p = t.render()
    return f"[Tarife Radarı] {head}: {name}", h, p


def setup_done(cfg: Config, n_sources: int, n_prices: int, notes: list[str]) -> tuple[str, str, str]:
    head = "KURULUM"
    t = Text().line(f"<b>[{head}] Tarife Radarı çalışmaya başladı</b>", f"[{head}] Tarife Radarı çalışmaya başladı")
    t.line(f"İzlenen kaynak: {n_sources}. Ücreti kaydedilen geçiş: {n_prices}.")
    t.line("Bundan sonra yalnızca değişiklikler bildirilecek.")
    h, p = t.render()
    return "[Tarife Radarı] Kurulum tamamlandı", h, p


def _event_line(cfg: Config, ev: dict, now: datetime) -> str:
    eff = from_iso(ev.get("effective_from"))
    when = f" · yürürlük {fmt_date(eff)} ({relative_days(eff, now)})" if eff else ""
    status = STATUS_LABELS.get(ev["status"], ev["status"])
    flags = ", ".join(FLAG_LABELS[f] for f in ev.get("flags", []) if f in FLAG_LABELS and f != "takvim")
    url = ev["evidence"][-1]["url"] if ev.get("evidence") else ""
    return f"- [{status}] {ev['title']}{when}" + (f" ({flags})" if flags else "") + (f"\n  {url}" if url else "")


def digest(cfg: Config, title: str, sections: list[tuple[str, list[dict]]], problems: list[str], now: datetime) -> tuple[str, str, str]:
    lines = [title, ""]
    for heading, items in sections:
        if not items:
            continue
        lines.append(heading)
        lines.extend(_event_line(cfg, ev, now) for ev in items)
        lines.append("")
    if problems:
        lines.append("Kaynak sorunları")
        lines.extend(f"- {p}" for p in problems)
        lines.append("")
    if cfg.settings.panel_url:
        lines.append(f"Panel: {cfg.settings.panel_url}")
    plain = "\n".join(lines).strip()
    html_body = "<pre style=\"font-family:inherit;white-space:pre-wrap\">" + esc(plain) + "</pre>"
    return f"[Tarife Radarı] {title}", html_body, plain
