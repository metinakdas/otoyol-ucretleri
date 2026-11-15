"""E-posta tasarım şablonları (radar/eposta_sablon/). İnternete çıkılmaz; SMTP taklit edilir."""

from __future__ import annotations

import html
import re
from datetime import datetime, timedelta

import pytest

from radar import eposta, notify
from radar.matching import KIND_FREE
from radar.notify import Message, deliver, email_layout
from radar.timeutil import TZ, to_iso

NOW = datetime(2026, 11, 15, 10, 30, tzinfo=TZ)
EFF = datetime(2027, 1, 1, 0, 0, tzinfo=TZ)
PANEL = "https://ornek.github.io/panel/"


def T(*a):
    return datetime(*a, tzinfo=TZ)


def olay(**k):
    ev = {"id": "e1", "title": "2027 yılı geçiş ücretleri", "kind": "zam", "status": "karar_cikti", "flags": [],
          "crossings": ["Osmangazi Köprüsü", "Avrasya Tüneli"], "excluded": [], "effective_from": to_iso(EFF),
          "effective_to": None, "documents": [],
          "prices": {"Osmangazi Köprüsü": {"old": {"1": "1170.00"}, "new": {"1": "1500.00"}},
                     "Avrasya Tüneli": {"old": {"1": "330.00"}, "new": {"1": "420.00"}}},
          "evidence": [{"url": "https://www.kgm.gov.tr/duyuru/1", "publisher": "kgm.gov.tr", "tier": "resmi"}],
          "created_at": to_iso(NOW), "updated_at": to_iso(NOW)}
    ev.update(k)
    return ev


def ucretsiz(**k):
    return olay(**{"title": "Ramazan Bayramı ücretsiz geçiş uygulaması", "kind": KIND_FREE, "prices": {},
                   "crossings": ["15 Temmuz Şehitler Köprüsü", "Fatih Sultan Mehmet Köprüsü"], "excluded": ["Avrasya Tüneli"],
                   "effective_from": to_iso(T(2027, 3, 8, 12)), "effective_to": to_iso(T(2027, 3, 11, 23, 59)), **k})


def bitmis(cfg, govde, ref="OÜ-TB-2026/147", url=PANEL):
    cfg.settings.panel_url = url
    return email_layout(cfg, "[Tarife Radarı] x", "x", govde, when=NOW, ref=ref)[1]


def gorunen(h: str) -> str:
    h = re.sub(r"<!--.*?-->|<style>.*?</style>|<title>.*?</title>", "", h, flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", h)))


def tum_turler(cfg):
    tz = {"iana": "2026f", "farklar": [{"zone": "America/Asuncion", "cc": "PY", "eski": -14400, "yeni": -10800,
                                         "tarih": "1 Ocak 2027 00:00"}]}
    return {
        "01": eposta.karar(cfg, olay(), NOW),
        "02": eposta.karar(cfg, olay(flags=["kacirildi"]), T(2027, 1, 1, 8, 15)),
        "03": eposta.hatirlatma(cfg, olay(), 3, T(2026, 12, 29, 9), NOW),
        "04": eposta.yururluk(cfg, olay(status="yururlukte"), T(2027, 1, 1, 0, 5), NOW),
        "05": eposta.karar(cfg, ucretsiz(), NOW),
        "06a": eposta.tarih_degisti(cfg, olay(effective_from=to_iso(T(2027, 1, 15)), onceki_yururluk=to_iso(EFF)), NOW),
        "06b": eposta.iptal(cfg, olay(title="Köprü ücret değişikliği ertelendi", status="iptal_ertelendi"), NOW),
        "06c": eposta.sona_erdi(cfg, ucretsiz(status="sona_erdi"), T(2027, 3, 12, 0, 5), NOW),
        "07": eposta.saat_dilimi(tz, {"PY": "Paraguay"}, "https://data.iana.org/time-zones/tzdb/NEWS"),
        "08": eposta.ozet(cfg, {"e1": olay()}, [], T(2026, 11, 16, 9), haftalik=True),
    }


# --------------------------------------------------------------------------- şablonlar

def test_templates_are_designer_files_unchanged():
    adlar = sorted(p.name for p in eposta.SABLONLAR.glob("*.html"))
    assert adlar == ["01-karar-cikti.html", "02-acil-kacirildi.html", "03-hatirlatma.html", "04-yururluge-girdi.html",
                     "05-ucretsiz-gecis.html", "06a-tarih-degisti.html", "06b-iptal-ertelendi.html",
                     "06c-sona-erdi.html", "07-saat-dilimi-degisti.html", "08-haftalik-ozet.html"]
    for ad in ("01", "08"):
        t = eposta.sablon(ad)
        assert "<!-- ▼ BİLEŞEN: antet -->" in t and 'src="cid:imza-logo"' in t and "{{referans_no}}" in t


@pytest.mark.parametrize("tur", ["01", "02", "03", "04", "05", "06a", "06b", "06c", "07", "08"])
def test_every_type_fully_filled(cfg, tur):
    h = bitmis(cfg, tum_turler(cfg)[tur])
    assert eposta.kalan_alanlar(re.sub(r"<!--.*?-->", "", h, flags=re.S)) == []
    assert "OÜ-TB-2026/147" in h and "15 Kasım 2026 Pazar, 10:30" in h          # sayı ve tarih gönderimde yazılır
    assert "Sayın İlgili," in h and "Saygılarımızla," in h and "bağlayıcı nitelik" in h
    assert 'href="https://ornek.github.io/panel/"' in h and ">ornek.github.io/panel</a>" in h  # düğme ve imza
    assert "metinakdas.github.io" not in h
    assert "seyir" not in h.lower()


def test_decision_content(cfg):
    h = gorunen(bitmis(cfg, tum_turler(cfg)["01"]))
    assert "KARAR ÇIKTI" in h and "Yeni geçiş ücretleri 1 Ocak 2027 tarihinde yürürlüğe giriyor" in h
    assert "Karayolları Genel Müdürlüğü tarafından yayımlanan karar ile" in h
    assert "1 Ocak 2027 Cuma, 00:00" in h and "47 gün" in h
    assert "Osmangazi Köprüsü 1.170,00 TL 1.500,00 TL +%28,2" in h and "Avrasya Tüneli 330,00 TL 420,00 TL +%27,3" in h


def test_urgent_content(cfg):
    h = gorunen(bitmis(cfg, tum_turler(cfg)["02"]))
    assert "ACİL · KAÇIRILDI" in h and "Yürürlük anı geçmiş; ilgili taksimetreleri hemen kontrol edin." in h
    assert "Yeni ücretler 8 saat 15 dakikadır uygulanıyor" in h and "Gecikme 8 sa 15 dk" in h
    assert "1. Taksimetre" in h and "2. 00:00 ile bildirim saati" in h


def test_free_passage_lists_and_badges(cfg):
    h = bitmis(cfg, tum_turler(cfg)["05"])
    assert h.count(">ÜCRETSİZ</td>") == 2 and h.count(">ÜCRETLİ</td>") == 1
    assert "Kapsam dışındaki geçişlerde olağan ücretler uygulanır." in h
    assert "8 Mart 2027 Pazartesi, 12:00" in h and "11 Mart 2027 Perşembe, 23:59" in h
    # dışarıda kalan yoksa o bölüm hiç gösterilmez
    h2 = bitmis(cfg, eposta.karar(cfg, ucretsiz(excluded=[]), NOW))
    assert "Kapsam dışı geçişler" not in h2 and "ÜCRETLİ" not in h2


def test_repeated_rows_get_separator_like_design(cfg):
    h = tum_turler(cfg)["06a"]
    rows = re.findall(r"<tr><td class=\"ob-c-text ob-bd-line\" style=\"([^\"]*)\">[^<]*<br>", h)
    assert len(rows) == 2
    assert "border-top" not in rows[0] and rows[1].startswith("padding:12px 0;border-top:1px solid #e1e8e4;")


def test_reminder_tomorrow_and_days(cfg):
    assert "Kalan süre" in tum_turler(cfg)["03"] and ">3 gün<" in tum_turler(cfg)["03"]
    yarin = gorunen(eposta.hatirlatma(cfg, olay(), 1, T(2026, 12, 31, 9), NOW))
    assert "Yeni ücretler yarın yürürlükte" in yarin and "yarın saat 00:00 itibarıyla" in yarin
    assert "15 Kasım 2026 tarihli bildirimimizde" in yarin


def test_date_changed_and_cancelled(cfg):
    a = gorunen(tum_turler(cfg)["06a"])
    assert "Önceki yürürlük tarihi 1 Ocak 2027, 00:00" in a and "15 Ocak 2027 Cuma, 00:00" in a
    assert "1.170,00 → 1.500,00 TL" in a
    b = gorunen(tum_turler(cfg)["06b"])
    assert "ERTELENDİ" in b and "ertelendi: ertelendi" not in b and "Açıklanmadı" in b


def test_ended_normal_fares_next_minute(cfg):
    h = gorunen(tum_turler(cfg)["06c"])
    assert "Uygulama sona erdi 11 Mart 2027, 23:59" in h and "Olağan ücretler 12 Mart 2027, 00:00" in h


def test_time_zone_mail(cfg):
    h = gorunen(tum_turler(cfg)["07"])
    assert "Paraguay (America/Asuncion)" in h and "eski UTC−04:00 → yeni UTC−03:00" in h
    assert "Yürürlük: 1 Ocak 2027, 00:00 (yerel saat)" in h and "Saat dilimlerini görüntüle" in h


def test_digest_counts_empty_state_and_dark_css(cfg):
    iz = {"izlenen": [{"ad": "Tarifeler", "alt": "17 tarife tablosu"}], "tz_yaklasan": []}
    h = bitmis(cfg, eposta.ozet(cfg, {"e1": olay()}, [], T(2026, 11, 16, 9), haftalik=True, izleme=iz), ref="OÜ-HO-2026/46")
    g = gorunen(h)
    assert "Haftalık tarife özeti · 9–15 Kasım 2026" in g
    assert "Yaklaşan değişiklikler (2)" in g and "Yürürlüğe girenler (0)" in g
    assert "Bu hafta yürürlüğe giren değişiklik yok." in g and "<!-- NOT:" not in h
    assert ".ob-bg-soft{background-color:#15211d !important;}" in h
    assert "Tarifeler 17 tarife tablosu" in g and "Kaynak durumu Tümü okunuyor" in g
    gunluk = gorunen(eposta.ozet(cfg, {}, ["KGM duyuruları (30 saattir)"], NOW, haftalik=False))
    assert "GÜNLÜK ÖZET" in gunluk and "Yaklaşan değişiklik yok." in gunluk and "1 kaynak okunamıyor" in gunluk


def test_free_flow_count_matches_panel():
    yakin = {"lat": 41.0, "lon": 29.0}
    yollar = [{"serbest_gecis": [dict(yakin, ad="X A"), dict(lat=41.001, lon=29.0, ad="X B"), dict(lat=41.1, lon=29.0, ad="Y")],
               "istasyonlar": [dict(lat=40.0, lon=30.0, serbest=True), dict(lat=40.5, lon=30.0)]}]
    assert eposta._serbest_sayisi(yollar) == 3  # X (A/B tek nokta), Y ve tümü serbest olan gişe


def test_values_are_escaped(cfg):
    h = eposta.karar(cfg, olay(title='<script>alert(1)</script> {{konu}}'), NOW)
    assert "<script>" not in h and "&lt;script&gt;" in h and "{{konu}}" not in h


def test_without_panel_url_no_button_or_link(cfg):
    h = bitmis(cfg, tum_turler(cfg)["01"], url="")
    assert "Panelde görüntüle" not in h and "{{panel_url}}" not in h and "metinakdas.github.io" not in h
    assert "Saygılarımızla," in h


def test_formats():
    assert eposta.sure_ekli(timedelta(hours=8, minutes=15)) == "8 saat 15 dakikadır"
    assert eposta.sure_ekli(timedelta(days=2, hours=3)) == "2 gün 3 saattir"
    assert eposta.sure_ekli(timedelta(days=1)) == "1 gündür"
    assert eposta.degisim("52.00", "66.50") == "+%27,9" and eposta.degisim("100", "95") == "−%5,0"
    assert eposta.aralik(T(2026, 11, 30), T(2026, 12, 6)) == "30 Kasım – 6 Aralık 2026"
    assert eposta.aralik(T(2026, 12, 28), T(2027, 1, 3)) == "28 Aralık 2026 – 3 Ocak 2027"


# --------------------------------------------------------------------------- gönderim ve sayı

class Mail:
    def __init__(self):
        self.calls: list[dict] = []
        self.fail = False

    def __call__(self, cfg, subject, plain, html_body=None, **kw):
        self.calls.append({"subject": subject, "html": html_body, **kw})
        if self.fail:
            raise RuntimeError("535")


@pytest.fixture
def ecfg(cfg):
    s = cfg.settings
    s.smtp_host, s.smtp_user, s.smtp_password = "smtp.ornek.com", "radar@ornek.com", "gizli-sifre"
    s.smtp_from, s.email_to, s.telegram_token = "Radar <radar@ornek.com>", ["alici@ornek.com"], ""
    return cfg


def m(key, tur="TB"):
    return Message(key=key, channels=("email",), subject="s", html="h", plain="p", email_html="<!doctype html>x", ref_tur=tur)


def test_reference_numbers_sequential_and_kept_on_retry(ecfg, monkeypatch):
    mail = Mail()
    monkeypatch.setattr(notify, "send_email", mail)
    sent = {}
    deliver(ecfg, [m("a:karar"), m("b:karar")], sent, NOW)
    assert [c["ref"] for c in mail.calls] == ["OÜ-TB-2026/001", "OÜ-TB-2026/002"]
    assert [k for k in sent if k.startswith("sayi:")] == ["sayi:TB:2026:2"]  # yalnızca son sayaç tutulur
    mail.fail = True
    deliver(ecfg, [m("c:karar")], sent, NOW)
    mail.fail = False
    deliver(ecfg, [m("c:karar")], sent, NOW + timedelta(minutes=30))
    assert [c["ref"] for c in mail.calls[2:]] == ["OÜ-TB-2026/003", "OÜ-TB-2026/003"]  # gidemeyen numarayı tüketmez
    assert mail.calls[-1]["when"] == NOW + timedelta(minutes=30)


def test_reference_counter_survives_cleanup(ecfg, monkeypatch):
    monkeypatch.setattr(notify, "send_email", Mail())
    sent = {"sayi:TB:2026:40": "2026-01-02T10:00:00+03:00"}
    deliver(ecfg, [], sent, NOW)  # 180 günden eski anahtarlar silinir, sayaç kalır
    assert "sayi:TB:2026:40" in sent


def test_reference_formats():
    assert notify.referans(m("x", "HO"), {}, T(2026, 11, 16, 9)) == ("OÜ-HO-2026/46", None)
    assert notify.referans(m("x", "GO"), {}, NOW) == ("OÜ-GO-2026/319", None)
    assert notify.referans(m("x", "SD"), {"sayi:SD:2026:5": "x"}, NOW) == ("OÜ-SD-2026/006", "sayi:SD:2026:6")
    assert notify.referans(m("x", ""), {}, NOW) == ("—", None)


def test_plan_uses_designed_templates(cfg):
    ev = olay()
    msgs = notify.plan(cfg, {"e1": ev}, [], [], {}, {}, NOW)
    karar = next(x for x in msgs if x.key == "e1:karar")
    assert karar.channels == ("telegram", "email") and karar.ref_tur == "TB"
    assert karar.email_html.startswith("<!doctype html>") and "KARAR ÇIKTI" in karar.email_html


def test_send_email_uses_design_and_embeds_logo(cfg, monkeypatch):
    captured = {}

    class FakeSMTP:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def starttls(self, **k): pass
        def login(self, *a): pass
        def send_message(self, msg): captured["m"] = msg

    monkeypatch.setattr(notify.smtplib, "SMTP", FakeSMTP)
    s = cfg.settings
    s.smtp_host, s.smtp_user, s.smtp_password, s.email_to, s.panel_url = "smtp.ornek.com", "u", "p", ["a@ornek.com"], PANEL
    notify.send_email(cfg, "[Tarife Radarı] KARAR ÇIKTI: Köprü", "[KARAR ÇIKTI] Köprü\nsatır",
                      eposta.karar(cfg, olay(), NOW), ref="OÜ-TB-2026/147", when=NOW)
    msg = captured["m"]
    h = msg.get_body(("html",)).get_content()
    assert "ob-bg-card" in h and "OÜ-TB-2026/147" in h and 'src="cid:imza-logo"' in h
    assert "Sayı: OÜ-TB-2026/147" in msg.get_body(("plain",)).get_content()
    assert [p.get_content_type() for p in msg.walk()][-1] == "image/png"


def test_time_zone_message_has_design():
    from radar import saat_dilimi
    b = {"key": "saatdilimi:2026f", "kind": "degisim", "iana": "2026f", "subject": "s", "channels": ["telegram", "email"],
         "lines": ["[SAAT DİLİMİ DEĞİŞTİ]", "x"], "at": to_iso(NOW),
         "farklar": [{"zone": "America/Asuncion", "cc": "PY", "eski": -14400, "yeni": -10800, "tarih": None}]}
    msg = saat_dilimi._mesaj(b)
    assert msg.ref_tur == "SD" and "SAAT DİLİMİ DEĞİŞTİ" in msg.email_html and "Hemen (yerel saat)" in msg.email_html
