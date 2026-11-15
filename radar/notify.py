"""Hangi bildirimin ne zaman gideceğine karar verir ve Telegram/WhatsApp/e-posta ile gönderir.

Her bildirimin bir anahtarı vardır (ör. "<kayıt>:karar"). Gönderilen anahtarlar
data/notifications.json'da tutulur; aynı bildirim iki kez gitmez.
"""

from __future__ import annotations

import html
import logging
import re
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
from .textutil import slugify
from .timeutil import fmt_date, from_iso, hours_since, to_iso

log = logging.getLogger(__name__)

TELEGRAM_LIMIT = 4000
META_PARAM_LIMIT = 900   # şablon gövdesi en fazla 1024 karakter (şablonun kendi metniyle birlikte)
META_API = "https://graph.facebook.com/v25.0"

# E-posta arızası: hesap kilitlenmesin diye bir mesaj için en fazla bu kadar denenir; uyarı en sık bu aralıkla tekrarlanır.
EMAIL_GIVE_UP = timedelta(days=3)
EMAIL_ALERT_EVERY = timedelta(hours=24)
EMAIL_FAIL_KEY = "eposta-hata:baslangic"   # e-postanın ilk hata verdiği an
EMAIL_ALERT_KEY = "eposta-hata:uyari"      # son uyarının Telegram'a gittiği an
CHANNEL_SUFFIXES = ("#telegram", "#tech", "#email", "#email-hata", "#email-birakildi")


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
    kayitsiz_giseler: list[dict] | None = None,
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

    # Tarifede olup gişe kaydında (config/giseler.yaml) olmayan gişeler: her gişe için bir kez, teknik gruba
    yeni = [g for g in kayitsiz_giseler or [] if todo(gise_anahtari(g))]
    if yeni:
        keys = [gise_anahtari(g) for g in yeni]
        out.append(_m(keys[0], ("tech",), msg.gise_kaydi_eksik(cfg, yeni), extra=keys[1:]))

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


def gise_anahtari(g: dict) -> str:
    on = "sgs-" if g.get("tur") == "serbest" else ""   # aynı adlı gişe ile serbest geçiş noktası ayrı bildirilir
    return f"gise-kaydi:{g['otoyol']}:{on}{slugify(g['ad'], 60)}"


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


def _cut(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def one_line(text: str) -> str:
    """Meta şablon değişkeni satır sonu, sekme ve 4'ten fazla art arda boşluk kabul etmez."""
    parts = [re.sub(r"\s+", " ", line).strip() for line in str(text).splitlines()]
    return " · ".join(p for p in parts if p)


def send_whatsapp(cfg: Config, text: str, client: httpx.Client | None = None, to: list[str] | None = None) -> None:
    """Düz metni Meta WhatsApp Cloud API ile, onaylı şablonun {{1}} değişkeni olarak her alıcıya gönderir.

    Radarın mesajları kendiliğinden gittiği için (alıcı önce yazmadığı için) WhatsApp şablon şartı koyar.
    """
    s = cfg.settings
    if not s.whatsapp_ready:
        raise RuntimeError("WhatsApp ayarlı değil")
    own = client is None
    client = client or httpx.Client(timeout=30)
    try:
        template = {"name": s.wa_template, "language": {"code": s.wa_template_lang},
                    "components": [{"type": "body", "parameters": [
                        {"type": "text", "text": _cut(one_line(text), META_PARAM_LIMIT)}]}]}
        for number in s.wa_to if to is None else to:
            resp = client.post(f"{META_API}/{s.wa_phone_id}/messages",
                               headers={"Authorization": f"Bearer {s.wa_token}"},
                               json={"messaging_product": "whatsapp", "to": number, "type": "template", "template": template})
            if resp.status_code != 200:
                raise RuntimeError(f"WhatsApp {resp.status_code}: {redact(resp.text[:300], s)}")
    except httpx.HTTPError as exc:  # hata metni adresi (dolayısıyla anahtarı) içerebilir
        raise RuntimeError(f"WhatsApp'a bağlanılamadı: {redact(exc, s)}") from None
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
            server.login(s.smtp_user, smtp_password(s))
        server.send_message(m)


def smtp_password(s) -> str:
    """Gmail uygulama şifresi "abcd efgh ijkl mnop" biçiminde gösterilir; boşluklar şifreye dahil değildir."""
    password = (s.smtp_password or "").strip()
    if "gmail" in (s.smtp_host or "").lower():
        password = "".join(password.split())
    return password


def _email_alert(error: str) -> str:
    return ("<b>[Tarife Radarı] E-posta gönderilemiyor</b>\n"
            "Gönderici hesabın uygulama şifresi iptal edilmiş ya da değişmiş olabilir.\n"
            f"Hata: <code>{html.escape(error)}</code>\n"
            "Düzeltmek için .env'yi güncelleyip "
            "<code>python -m radar yayinla --yalnizca-ayarlar</code> çalıştırın.")


def deliver(
    cfg: Config,
    messages: list[Message],
    sent: dict,
    now: datetime,
    *,
    dry_run: bool = False,
    client: httpx.Client | None = None,
) -> list[str]:
    """Mesajları gönderir; başarılı olanları sent sözlüğüne işler. Günlük satırları döndürür.

    Her kanal ayrı işaretlenir ("<anahtar>#telegram", "#tech", "#email"): bir kanal hata verirse bir sonraki
    turda yalnızca o kanal yeniden denenir. Tüm kanallar tamamlanınca "<anahtar>" yazılır ve kanal
    işaretleri silinir. "<anahtar>" zaten varsa mesaj tamamlanmış sayılır.
    """
    log_lines: list[str] = []
    s = cfg.settings
    stamp = to_iso(now)
    email_error: str | None = None   # bu turdaki ilk e-posta hatası
    email_ok = False
    for m in messages:
        if dry_run:
            if m.channels:
                log_lines.append(f"[gönderilmedi, deneme] {m.subject}\n{m.plain}")
            continue
        if m.key in sent:
            continue
        ok = True
        # WhatsApp, Telegram'a giden ana bildirimlerin kopyasını alır (teknik uyarılar ve özetler hariç).
        # Her alıcı ayrı işaretlenir (sıra numarasıyla; numara herkese açık data/ klasörüne yazılmaz).
        # WhatsApp hatası bildirimi "gönderilemedi" saymaz: yoksa Telegram her turda yinelenirdi.
        if "telegram" in m.channels and s.whatsapp_ready:
            for n, number in enumerate(s.wa_to, 1):
                wkey = f"{m.key}#wa{n}"
                if wkey in sent:
                    continue
                try:
                    send_whatsapp(cfg, m.plain or m.subject, client, to=[number])
                    sent[wkey] = to_iso(now)
                    log_lines.append(f"WhatsApp'a gönderildi ({n}. alıcı): {m.subject}")
                except Exception as exc:
                    log_lines.append(f"WhatsApp'a gönderilemedi ({n}. alıcı): {m.subject}: {redact(exc, s)}")
        for ch in m.channels:
            ckey = f"{m.key}#{ch}"
            if ckey in sent:
                continue  # bu kanala daha önceki bir turda gitti
            try:
                if ch in ("telegram", "tech"):
                    if not s.telegram_ready:
                        log_lines.append(f"Telegram ayarlı değil, atlandı: {m.subject}")
                        continue
                    chat = s.telegram_tech_chat_id if ch == "tech" and s.telegram_tech_chat_id else s.telegram_chat_id
                    send_telegram(cfg, chat, m.html, client)
                    sent[ckey] = stamp
                    log_lines.append(f"Telegram'a gönderildi: {m.subject}")
                elif ch == "email":
                    if not s.email_ready:
                        log_lines.append(f"E-posta ayarlı değil, atlandı: {m.subject}")
                        continue
                    first_fail = from_iso(sent.get(f"{m.key}#email-hata"))
                    if first_fail and now - first_fail > EMAIL_GIVE_UP:
                        sent[f"{m.key}#email-birakildi"] = stamp
                        log_lines.append(f"E-posta {EMAIL_GIVE_UP.days} günden uzun süredir gönderilemiyor, "
                                         f"bu mesaj için bırakıldı: {m.subject}")
                        continue
                    if email_error is not None:
                        # Aynı turda hata veren hesapla yeniden giriş denenmez (Gmail art arda hatalı girişte kilitler)
                        raise RuntimeError("bu turda e-posta zaten hata verdi, denenmedi")
                    send_email(cfg, m.subject, m.plain, m.email_html or m.html.replace("\n", "<br>"))
                    sent[ckey] = stamp
                    sent.pop(f"{m.key}#email-hata", None)
                    email_ok = True
                    log_lines.append(f"E-posta gönderildi: {m.subject}")
            except Exception as exc:  # bir sonraki çalışmada yalnızca bu kanal yeniden denenir
                ok = False
                err = redact(exc, s)
                log_lines.append(f"Gönderilemedi ({ch}): {m.subject}: {err}")
                if ch == "email":
                    sent.setdefault(f"{m.key}#email-hata", stamp)
                    if email_error is None:
                        email_error = err
        if ok:
            sent[m.key] = stamp
            for k in m.extra_keys:
                sent.setdefault(k, stamp)
            for suffix in CHANNEL_SUFFIXES:
                sent.pop(m.key + suffix, None)
    log_lines += _email_health(cfg, sent, now, email_error, email_ok, client)
    # 180 günden eski anahtarları temizle
    cutoff = now - timedelta(days=180)
    for k in [k for k, v in sent.items() if from_iso(v) and from_iso(v) < cutoff]:
        del sent[k]
    return log_lines


def _email_health(cfg: Config, sent: dict, now: datetime, error: str | None, ok: bool,
                  client: httpx.Client | None) -> list[str]:
    """E-posta hata vermeye başlayınca Telegram'a uyarır (en sık 24 saatte bir); düzelince durumu sıfırlar."""
    s = cfg.settings
    if error is None:
        if ok and (EMAIL_FAIL_KEY in sent or EMAIL_ALERT_KEY in sent):
            sent.pop(EMAIL_FAIL_KEY, None)
            sent.pop(EMAIL_ALERT_KEY, None)
            return ["E-posta yeniden çalışıyor; hata durumu sıfırlandı."]
        return []
    sent.setdefault(EMAIL_FAIL_KEY, to_iso(now))
    last = from_iso(sent.get(EMAIL_ALERT_KEY))
    if last and now - last < EMAIL_ALERT_EVERY:
        return []
    if not s.telegram_ready:
        return ["E-posta hatası Telegram'a bildirilemedi: Telegram ayarlı değil."]
    chat = s.telegram_tech_chat_id or s.telegram_chat_id
    try:
        send_telegram(cfg, chat, _email_alert(error[:200]), client)
    except Exception as exc:
        return [f"E-posta hatası Telegram'a bildirilemedi: {redact(exc, s)}"]
    sent[EMAIL_ALERT_KEY] = to_iso(now)
    return ["E-posta hatası Telegram'a bildirildi."]
