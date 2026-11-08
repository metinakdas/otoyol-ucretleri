"""Hangi bildirimin ne zaman gideceğine karar verir ve Telegram/e-posta ile gönderir.

Her bildirimin bir anahtarı vardır (ör. "<kayıt>:karar"). Gönderilen anahtarlar
data/notifications.json'da tutulur; aynı bildirim iki kez gitmez.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from email.message import EmailMessage

import httpx

from . import messages as msg
from .config import Config
from .guvenlik import redact
from .lifecycle import DECIDED
from .timeutil import fmt_date, from_iso, hours_since, to_iso

log = logging.getLogger(__name__)

TELEGRAM_LIMIT = 4000


@dataclass
class Message:
    key: str
    channels: tuple[str, ...]  # "telegram", "tech", "email"; boşsa yalnızca "gönderildi" işaretlenir
    subject: str = ""
    html: str = ""
    plain: str = ""
    email_html: str | None = None
    extra_keys: list[str] = field(default_factory=list)


def _m(key: str, channels: tuple[str, ...], parts: tuple[str, str, str], extra: list[str] | None = None,
       email_html: str | None = None) -> Message:
    subject, h, p = parts
    return Message(key=key, channels=channels, subject=subject, html=h, plain=p,
                   email_html=email_html, extra_keys=extra or [])


def plan(
    cfg: Config,
    events: dict,
    transitions: list[tuple[dict, str]],
    created_watch: list[dict],
    health: dict,
    sent: dict,
    now: datetime,
    *,
    first_run: bool = False,
    n_prices: int = 0,
    notes: list[str] | None = None,
) -> list[Message]:
    out: list[Message] = []
    s = cfg.settings
    both = ("telegram", "email")

    def todo(key: str) -> bool:
        return key not in sent and all(m.key != key for m in out)

    if first_run:
        if todo("kurulum"):
            n_sources = sum(1 for x in cfg.sources if x.enabled)
            out.append(_m("kurulum", ("telegram",), msg.setup_done(cfg, n_sources, n_prices, notes or [])))
        return out

    transitioned = {(ev["id"], kind) for ev, kind in transitions}

    for ev in sorted(events.values(), key=lambda e: e["updated_at"]):
        eid = ev["id"]
        if ev["status"] in DECIDED:
            if todo(f"{eid}:karar"):
                # Karar ile yürürlük aynı turda geldiyse tek mesaj yeter
                out.append(_m(f"{eid}:karar", both, msg.decision(cfg, ev, now),
                              extra=[f"{eid}:t0"] if ev["status"] == "yururlukte" else []))
                continue
            eff = from_iso(ev.get("effective_from"))
            if "tarih_degisti" in ev["flags"] and eff and todo(f"{eid}:tarih:{to_iso(eff)}"):
                out.append(_m(f"{eid}:tarih:{to_iso(eff)}", both, msg.date_changed(cfg, ev, now)))
            if ev["status"] == "karar_cikti" and eff:
                created = from_iso(ev["created_at"])
                for days in sorted(s.reminder_days):
                    key = f"{eid}:t{days}"
                    if not todo(key):
                        break
                    if eff - now <= timedelta(days=days) and eff - created > timedelta(days=days):
                        larger = [f"{eid}:t{d}" for d in s.reminder_days if d > days]
                        out.append(_m(key, both, msg.reminder(cfg, ev, days, now), extra=larger))
                        break
            if (eid, "yururlukte") in transitioned and todo(f"{eid}:t0"):
                out.append(_m(f"{eid}:t0", both, msg.in_force(cfg, ev, now)))
            if (eid, "sona_erdi") in transitioned and todo(f"{eid}:bitti"):
                out.append(_m(f"{eid}:bitti", both, msg.ended(cfg, ev, now)))
        elif ev["status"] == "iptal_ertelendi" and todo(f"{eid}:iptal"):
            if f"{eid}:karar" in sent:  # karar bildirilmişse iptal de bildirilir
                out.append(_m(f"{eid}:iptal", both, msg.cancelled(cfg, ev, now)))

    for ev in created_watch:
        key = f"takvim:{ev['period_id']}"
        if ev["status"] in DECIDED:  # aynı turda karar da geldiyse yalnızca karar bildirilir
            out.append(Message(key=key, channels=()))
        elif todo(key):
            out.append(_m(key, ("telegram",), msg.watch_started(cfg, ev, now)))

    for src in cfg.sources:
        h = health.get(src.id) or {}
        if not src.enabled or h.get("ok", True):
            continue
        hours = hours_since(h.get("failing_since"), now)
        if hours >= s.source_error_hours:
            key = f"kaynak:{src.id}:{now.date().isoformat()}"
            if todo(key):
                out.append(_m(key, ("tech",), msg.source_error(cfg, src.name, src.url, hours, h.get("error") or "")))

    # Günlük özet (e-posta)
    if now.hour >= s.digest_hour:
        key = f"ozet:{now.date().isoformat()}"
        if todo(key):
            out.append(_daily_digest(cfg, events, health, now, key))
        if now.weekday() == 0:
            iso = now.isocalendar()
            wkey = f"haftalik:{iso[0]}-{iso[1]:02d}"
            if todo(wkey):
                out.append(_weekly_digest(cfg, events, health, now, wkey))
    return out


def _problems(cfg: Config, health: dict, now: datetime) -> list[str]:
    out = []
    for src in cfg.sources:
        h = health.get(src.id) or {}
        if src.enabled and not h.get("ok", True):
            out.append(f"{src.name}: {int(hours_since(h.get('failing_since'), now))} saattir okunamıyor ({h.get('error', '')[:120]})")
    return out


def _daily_digest(cfg: Config, events: dict, health: dict, now: datetime, key: str) -> Message:
    upcoming = sorted(
        (e for e in events.values() if e["status"] == "karar_cikti"),
        key=lambda e: e.get("effective_from") or "9999",
    )
    open_items = sorted(
        (e for e in events.values() if e["status"] in ("sinyal", "gundemde")),
        key=lambda e: e["updated_at"], reverse=True,
    )
    problems = _problems(cfg, health, now)
    if not (upcoming or open_items or problems):
        return Message(key=key, channels=())  # anlatacak bir şey yok; yalnızca işaretle
    title = f"Günlük özet · {fmt_date(now)}: {len(upcoming)} karar, {len(open_items)} sinyal"
    return _m(key, ("email",), msg.digest(cfg, title, [
        ("Yaklaşan değişiklikler", upcoming),
        ("Gündemde ve sinyaller", open_items),
    ], problems, now))


def _weekly_digest(cfg: Config, events: dict, health: dict, now: datetime, key: str) -> Message:
    horizon = now + timedelta(days=30)
    upcoming = sorted(
        (e for e in events.values() if e["status"] in ("karar_cikti", "yururlukte")
         and e.get("effective_from") and now - timedelta(days=1) <= from_iso(e["effective_from"]) <= horizon),
        key=lambda e: e["effective_from"],
    )
    watching = [e for e in events.values() if e["status"] in ("sinyal", "gundemde")]
    title = f"Haftalık takvim · {fmt_date(now)}: önümüzdeki 30 gün"
    return _m(key, ("email",), msg.digest(cfg, title, [
        ("Önümüzdeki 30 gün", upcoming),
        ("İzlenenler", watching),
    ], _problems(cfg, health, now), now))


# ---------------------------------------------------------------------------
# Gönderim
# ---------------------------------------------------------------------------

def send_telegram(cfg: Config, chat_id: str, text: str, client: httpx.Client | None = None) -> None:
    if len(text) > TELEGRAM_LIMIT:
        text = text[:TELEGRAM_LIMIT] + "\n…"
    url = f"https://api.telegram.org/bot{cfg.settings.telegram_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    own = client is None
    client = client or httpx.Client(timeout=20)
    try:
        resp = client.post(url, json=payload)
        if resp.status_code != 200:
            raise RuntimeError(f"Telegram {resp.status_code}: {redact(resp.text[:200], cfg.settings)}")
    except httpx.HTTPError as exc:  # hata metni adresi (dolayısıyla anahtarı) içerebilir
        raise RuntimeError(f"Telegram'a bağlanılamadı: {redact(exc, cfg.settings)}") from None
    finally:
        if own:
            client.close()


def send_email(cfg: Config, subject: str, plain: str, html_body: str | None = None) -> None:
    s = cfg.settings
    m = EmailMessage()
    m["Subject"] = subject
    m["From"] = s.smtp_from or s.smtp_user
    m["To"] = ", ".join(s.email_to)
    m.set_content(plain)
    if html_body:
        m.add_alternative(html_body, subtype="html")
    # Sunucu sertifikası her zaman doğrulanır; araya giren biri şifreyi ele geçiremez.
    context = ssl.create_default_context()
    if s.smtp_ssl:
        server = smtplib.SMTP_SSL(s.smtp_host, s.smtp_port or 465, timeout=30, context=context)
    else:
        server = smtplib.SMTP(s.smtp_host, s.smtp_port or 587, timeout=30)
    with server:
        if not s.smtp_ssl:
            server.starttls(context=context)  # şifreli bağlantı kurulamazsa gönderim durur
        if s.smtp_user:
            server.login(s.smtp_user, s.smtp_password)
        server.send_message(m)


def deliver(
    cfg: Config,
    messages: list[Message],
    sent: dict,
    now: datetime,
    *,
    dry_run: bool = False,
    client: httpx.Client | None = None,
) -> list[str]:
    """Mesajları gönderir; başarılı olanları sent sözlüğüne işler. Günlük satırları döndürür."""
    log_lines: list[str] = []
    s = cfg.settings
    for m in messages:
        if dry_run:
            if m.channels:
                log_lines.append(f"[gönderilmedi, deneme] {m.subject}\n{m.plain}")
            continue
        ok = True
        for ch in m.channels:
            try:
                if ch in ("telegram", "tech"):
                    if not s.telegram_ready:
                        log_lines.append(f"Telegram ayarlı değil, atlandı: {m.subject}")
                        continue
                    chat = s.telegram_tech_chat_id if ch == "tech" and s.telegram_tech_chat_id else s.telegram_chat_id
                    send_telegram(cfg, chat, m.html, client)
                    log_lines.append(f"Telegram'a gönderildi: {m.subject}")
                elif ch == "email":
                    if not s.email_ready:
                        log_lines.append(f"E-posta ayarlı değil, atlandı: {m.subject}")
                        continue
                    send_email(cfg, m.subject, m.plain, m.email_html or m.html.replace("\n", "<br>"))
                    log_lines.append(f"E-posta gönderildi: {m.subject}")
            except Exception as exc:  # bir sonraki çalışmada yeniden denenir
                ok = False
                log_lines.append(f"Gönderilemedi ({ch}): {m.subject}: {redact(exc, s)}")
        if ok:
            sent[m.key] = to_iso(now)
            for k in m.extra_keys:
                sent.setdefault(k, to_iso(now))
    # 180 günden eski anahtarları temizle
    cutoff = now - timedelta(days=180)
    for k in [k for k, v in sent.items() if from_iso(v) and from_iso(v) < cutoff]:
        del sent[k]
    return log_lines
