"""Kanal bazında gönderim takibi, e-posta hata uyarısı ve e-posta denemesinin bırakılması.

İnternete çıkılmaz: Telegram sahte yanıtlarla karşılanır, e-posta gönderimi taklit edilir.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import httpx
import pytest

from radar import notify
from radar.notify import EMAIL_ALERT_KEY, EMAIL_FAIL_KEY, Message, deliver, smtp_password
from radar.timeutil import TZ

NOW = datetime(2026, 11, 12, 10, 0, tzinfo=TZ)
PASSWORD = "gizli-sifre-123"


class Net:
    """Telegram isteklerini kaydeder; istenirse hata verdirir."""

    def __init__(self):
        self.chats: list[str] = []
        self.texts: list[str] = []
        self.fail = False
        self.client = httpx.Client(transport=httpx.MockTransport(self.handler))

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.chats.append(body["chat_id"])
        self.texts.append(body["text"])
        return httpx.Response(500 if self.fail else 200, json={"ok": not self.fail})

    def clear(self) -> None:
        self.chats.clear()
        self.texts.clear()


class Mail:
    """send_email yerine geçer; istenirse şifreyi içeren bir hata fırlatır."""

    def __init__(self):
        self.subjects: list[str] = []
        self.fail = False

    def __call__(self, cfg, subject, plain, html_body=None, **kwargs):
        self.subjects.append(subject)
        self.kwargs = kwargs
        if self.fail:
            raise RuntimeError(f"(535, b'5.7.8 Username and Password not accepted {PASSWORD}')")


@pytest.fixture
def ecfg(cfg):
    s = cfg.settings
    s.smtp_host, s.smtp_user, s.smtp_password = "smtp.ornek.com", "radar@ornek.com", PASSWORD
    s.smtp_from, s.email_to = "Radar <radar@ornek.com>", ["alici@ornek.com"]
    assert s.email_ready and s.telegram_ready and not s.whatsapp_ready
    return cfg


@pytest.fixture
def mail(monkeypatch):
    m = Mail()
    monkeypatch.setattr(notify, "send_email", m)
    return m


def msg(key="olay:karar", channels=("telegram", "email")):
    return Message(key=key, channels=channels, subject=f"[KARAR] {key}", html="<b>KARAR</b>", plain="KARAR")


def alerts(net: Net) -> list[str]:
    return [t for t in net.texts if "E-posta gönderilemiyor" in t]


# --- 1. Kanal bazında takip --------------------------------------------------

def test_email_failure_does_not_repeat_telegram(ecfg, mail):
    net, sent = Net(), {}
    mail.fail = True
    deliver(ecfg, [msg()], sent, NOW, client=net.client)
    assert "olay:karar" not in sent and "olay:karar#telegram" in sent and "olay:karar#email" not in sent
    assert net.chats.count("-100") == 1

    net.clear()
    mail.fail = False
    mail.subjects.clear()
    deliver(ecfg, [msg()], sent, NOW + timedelta(minutes=30), client=net.client)
    assert "-100" not in net.chats                       # Telegram yeniden gönderilmedi
    assert mail.subjects == ["[KARAR] olay:karar"]       # yalnızca e-posta denendi
    assert "olay:karar" in sent
    assert not any(k.startswith("olay:karar#") for k in sent)  # kanal işaretleri temizlendi


def test_telegram_failure_does_not_repeat_email(ecfg, mail):
    net, sent = Net(), {}
    net.fail = True
    deliver(ecfg, [msg()], sent, NOW, client=net.client)
    assert "olay:karar#email" in sent and "olay:karar" not in sent

    net.fail = False
    net.clear()
    mail.subjects.clear()
    deliver(ecfg, [msg()], sent, NOW + timedelta(minutes=30), client=net.client)
    assert mail.subjects == [] and net.chats == ["-100"]
    assert "olay:karar" in sent


def test_extra_keys_written_only_when_complete(ecfg, mail):
    net, sent = Net(), {}
    mail.fail = True
    m = Message(key="olay:karar", channels=("telegram", "email"), subject="s", html="h", plain="p",
                extra_keys=["olay:t0"])
    deliver(ecfg, [m], sent, NOW, client=net.client)
    assert "olay:t0" not in sent
    mail.fail = False
    deliver(ecfg, [m], sent, NOW + timedelta(minutes=30), client=net.client)
    assert "olay:t0" in sent


def test_old_record_counts_as_complete(ecfg, mail):
    net, sent = Net(), {"olay:karar": "2026-11-11T10:00:00+03:00"}  # kanal işaretlerinden önceki biçim
    deliver(ecfg, [msg()], sent, NOW, client=net.client)
    assert net.chats == [] and mail.subjects == []
    assert sent["olay:karar"] == "2026-11-11T10:00:00+03:00"


def test_one_login_attempt_per_run(ecfg, mail):
    net, sent = Net(), {}
    mail.fail = True
    deliver(ecfg, [msg("a:karar"), msg("b:karar"), msg("ozet:1", ("email",))], sent, NOW, client=net.client)
    assert len(mail.subjects) == 1                        # hata veren hesapla ikinci giriş denenmez
    assert all(f"{k}#email-hata" in sent for k in ("a:karar", "b:karar", "ozet:1"))
    assert net.chats.count("-100") == 2                   # Telegram mesajları yine de gitti


# --- 2. E-posta hata uyarısı ---------------------------------------------------

def test_alert_once_to_tech_chat_and_redacted(ecfg, mail):
    net, sent = Net(), {}
    mail.fail = True
    lines = deliver(ecfg, [msg("a:karar"), msg("b:karar")], sent, NOW, client=net.client)
    a = alerts(net)
    assert len(a) == 1
    assert net.chats[net.texts.index(a[0])] == "-200"     # teknik gruba
    assert "535" in a[0] and "uygulama şifresi" in a[0] and "yayinla --yalnizca-ayarlar" in a[0]
    assert PASSWORD not in a[0] and all(PASSWORD not in x for x in lines)
    assert EMAIL_FAIL_KEY in sent and EMAIL_ALERT_KEY in sent

    # Sonraki turlar: 24 saat dolmadan tekrar uyarılmaz
    for minutes in (30, 60, 23 * 60):
        net.clear()
        deliver(ecfg, [msg("c:karar", ("email",))], sent, NOW + timedelta(minutes=minutes), client=net.client)
        assert alerts(net) == []

    # 24 saat sonra hatırlatılır
    net.clear()
    deliver(ecfg, [msg("c:karar", ("email",))], sent, NOW + timedelta(hours=24, minutes=30), client=net.client)
    assert len(alerts(net)) == 1


def test_alert_goes_to_main_chat_without_tech_chat(ecfg, mail):
    ecfg.settings.telegram_tech_chat_id = ""
    net, sent = Net(), {}
    mail.fail = True
    deliver(ecfg, [msg("ozet:1", ("email",))], sent, NOW, client=net.client)
    assert net.chats == ["-100"] and len(alerts(net)) == 1


def test_alert_state_reset_after_success(ecfg, mail):
    net, sent = Net(), {}
    mail.fail = True
    deliver(ecfg, [msg("ozet:1", ("email",))], sent, NOW, client=net.client)
    assert len(alerts(net)) == 1

    mail.fail = False
    lines = deliver(ecfg, [msg("ozet:1", ("email",))], sent, NOW + timedelta(hours=1), client=net.client)
    assert EMAIL_FAIL_KEY not in sent and EMAIL_ALERT_KEY not in sent
    assert any("yeniden çalışıyor" in x for x in lines)

    # Yeniden bozulunca 24 saat beklenmeden hemen uyarılır
    net.clear()
    mail.fail = True
    deliver(ecfg, [msg("ozet:2", ("email",))], sent, NOW + timedelta(hours=2), client=net.client)
    assert len(alerts(net)) == 1


def test_no_alert_when_email_not_configured(cfg, mail):
    net, sent = Net(), {}
    deliver(cfg, [msg()], sent, NOW, client=net.client)
    assert mail.subjects == [] and alerts(net) == [] and "olay:karar" in sent


# --- 3. Sonsuz deneme olmaz ----------------------------------------------------

def test_email_given_up_after_three_days(ecfg, mail):
    net, sent = Net(), {}
    mail.fail = True
    deliver(ecfg, [msg()], sent, NOW, client=net.client)
    assert "olay:karar#email-hata" in sent

    # 2 gün sonra hâlâ denenir
    mail.subjects.clear()
    deliver(ecfg, [msg()], sent, NOW + timedelta(days=2), client=net.client)
    assert len(mail.subjects) == 1 and "olay:karar" not in sent

    # 3 günü geçince bırakılır, mesaj tamamlanmış sayılır
    mail.subjects.clear()
    net.clear()
    lines = deliver(ecfg, [msg()], sent, NOW + timedelta(days=3, hours=1), client=net.client)
    assert mail.subjects == [] and net.chats == []
    assert "olay:karar" in sent and not any(k.startswith("olay:karar#") for k in sent)
    assert any("bırakıldı" in x for x in lines)


def test_give_up_counts_from_first_failure_per_message(ecfg, mail):
    net, sent = Net(), {}
    mail.fail = True
    deliver(ecfg, [msg("eski:karar")], sent, NOW, client=net.client)
    later = NOW + timedelta(days=3, hours=1)
    mail.subjects.clear()
    deliver(ecfg, [msg("eski:karar"), msg("yeni:karar")], sent, later, client=net.client)
    assert "eski:karar" in sent                          # 3 günü geçti, bırakıldı
    assert "yeni:karar" not in sent and len(mail.subjects) == 1  # yenisi denendi


# --- Gmail uygulama şifresi --------------------------------------------------

def test_gmail_app_password_spaces_removed(ecfg):
    s = ecfg.settings
    s.smtp_host, s.smtp_password = "smtp.gmail.com", " abcd efgh ijkl mnop "
    assert smtp_password(s) == "abcdefghijklmnop"
    s.smtp_host = "smtp.ornek.com"
    assert smtp_password(s) == "abcd efgh ijkl mnop"  # başka sunucularda iç boşluklar korunur


# ------------------------------------------------------------------ e-posta imzası

def test_email_signature_embeds_logo(cfg, monkeypatch):
    captured = {}

    class FakeSMTP:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def starttls(self, **k): pass
        def login(self, *a): pass
        def send_message(self, m): captured["m"] = m

    monkeypatch.setattr(notify.smtplib, "SMTP", FakeSMTP)
    s = cfg.settings
    s.smtp_host, s.smtp_user, s.smtp_password, s.email_to, s.smtp_ssl = "smtp.ornek.com", "u", "p", ["a@ornek.com"], False
    s.panel_url = "https://ornek.github.io/panel/"
    notify.send_email(cfg, "[Tarife Radarı] KARAR ÇIKTI: Köprü", "[KARAR ÇIKTI] Köprü\nSatır 1\n<b>kaçış</b>")
    m = captured["m"]
    assert m["Subject"] == "Otoyol Ücretleri | KARAR ÇIKTI: Köprü"
    types = [p.get_content_type() for p in m.walk()]
    assert types == ["multipart/alternative", "text/plain", "multipart/related", "text/html", "image/png"]
    plain = m.get_body(("plain",)).get_content()
    html_part = m.get_body(("html",)).get_content()
    assert "Sayın İlgili," in plain and "Saygılarımızla," in plain and "Web: https://ornek.github.io/panel/" in plain
    assert "[KARAR ÇIKTI]" not in plain                                   # ilk satır başlıkta, tekrarlanmaz
    assert "Satır 1<br>&lt;b&gt;kaçış&lt;/b&gt;" in html_part           # düz metin HTML'e güvenli çevrilir
    assert "Sayın İlgili," in html_part and "Bilgilerinize sunarız." in html_part and "bağlayıcı nitelik" in html_part
    assert 'src="cid:imza-logo"' in html_part and 'href="https://ornek.github.io/panel/"' in html_part
    img = [p for p in m.walk() if p.get_content_type() == "image/png"][0]
    assert img["Content-ID"] == "<imza-logo>" and img.get_content_disposition() == "inline"
    assert "seyir" not in m.as_string().lower()


def test_email_layout_without_panel_url(cfg):
    cfg.settings.panel_url = ""
    plain, body = notify.email_layout(cfg, "konu", "metin", None)
    assert "Web:" not in plain and "<a href" not in body and "Otoyol Ücretleri" in body


def test_time_zone_email_embeds_green_logo(cfg, monkeypatch):
    """Saat dilimi e-postası kendi temasında ("Zaman Dilimi" antetli, iOS renkleri); antetteki yeşil logo gömülü
    gider, kullanılmayan logo eklenmez."""
    from radar import eposta
    t = eposta.sablon("07")
    antet = t[t.index("<!-- ▼ BİLEŞEN: antet -->"):t.index("<!-- ▲ BİLEŞEN: antet -->")]
    assert 'src="cid:logo-yesil"' in antet and "Zaman Dilimi" in antet and "Otoyol Ücretleri" not in antet
    assert "#ff9500" in t and "#34c759" in t
    captured = {}

    class FakeSMTP:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def starttls(self, **k): pass
        def login(self, *a): pass
        def send_message(self, m): captured["m"] = m

    monkeypatch.setattr(notify.smtplib, "SMTP", FakeSMTP)
    s = cfg.settings
    s.smtp_host, s.smtp_user, s.smtp_password, s.email_to, s.smtp_ssl = "smtp.ornek.com", "u", "p", ["a@ornek.com"], False
    notify.send_email(cfg, "[Tarife Radarı] SAAT DİLİMİ DEĞİŞTİ", "metin", t)
    cids = [p["Content-ID"] for p in captured["m"].walk() if p.get_content_type() == "image/png"]
    assert cids == ["<logo-yesil>"]
