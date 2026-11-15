"""Grafana Cloud izleme kayıtları (radar/izleme.py). Ağ taklit edilir; gerçek gönderim yapılmaz."""

from __future__ import annotations

import json

import httpx
import pytest

from radar import izleme
from radar.pipeline import RunReport


def rapor() -> RunReport:
    r = RunReport()
    r.sources = [("kgm-tarifeler", "tamam", "20 tarife belgesi, 0 değişiklik"),
                 ("uab-haberler", "HATA", "zaman aşımı")]
    r.messages = ["Telegram'a gönderildi: [KAYNAK HATASI] UAB okunamıyor",   # konudaki HATASI yanıltmamalı
                  "Gönderilemedi (email): konu: 535 kimlik doğrulanamadı",
                  "WhatsApp'a gönderildi (deneme): konu"]
    r.notes = ["Ücret tablosu alınamadı: kaynak kapalı"]
    r.status_changes = ["Sinyal → Karar çıktı: 2027 ücretleri"]
    r.new_events = 1
    r.candidates = 3
    return r


def test_ayar_yoksa_kapali(cfg, monkeypatch):
    for k in ("LOKI_URL", "LOKI_USER", "LOKI_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    assert not izleme.aktif()
    assert izleme.gonder(cfg, rapor(), 12.0) is None


def test_kayitlar_siniflandirma():
    kayitlar = izleme.kayitlar(rapor(), 42.3)
    olaylar = {(seviye, o["olay"]) for seviye, o in kayitlar}
    assert ("error", "kaynak") in olaylar and ("info", "kaynak") in olaylar
    bildirimler = [(s, o) for s, o in kayitlar if o["olay"] == "bildirim"]
    assert [s for s, _ in bildirimler] == ["info", "error", "info"]     # konudaki "HATASI" hata sayılmaz
    assert bildirimler[1][1]["kanal"] == "email"
    tur = [o for s, o in kayitlar if o["olay"] == "tur"][0]
    assert tur["kaynak_hata"] == 1 and tur["bildirim_hata"] == 1 and tur["sure_sn"] == 42.3
    assert [s for s, o in kayitlar if o["olay"] == "tur"] == ["error"]


def test_gonderim_ve_redaksiyon(cfg, monkeypatch):
    monkeypatch.setenv("LOKI_URL", "https://logs-ornek.grafana.net")
    monkeypatch.setenv("LOKI_USER", "123456")
    monkeypatch.setenv("LOKI_TOKEN", "glc_ornekanahtar123")
    cfg.settings.smtp_user = "gizli-adres@ornek.com"
    r = rapor()
    r.messages = list(r.messages) + ["Gönderilemedi (email): konu: gizli-adres@ornek.com reddedildi"]

    gelen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        gelen["url"] = str(request.url)
        gelen["auth"] = request.headers.get("authorization", "")
        gelen["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(204)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    not_ = izleme.gonder(cfg, r, 5.0, client=client)
    assert not_ and "Grafana'ya gönderildi" in not_
    assert gelen["url"].endswith("/loki/api/v1/push")       # tabana otomatik eklenir
    govde = json.dumps(gelen["body"], ensure_ascii=False)
    assert "gizli-adres@ornek.com" not in govde and "***" in govde
    etiketler = {s["stream"]["level"] for s in gelen["body"]["streams"]}
    assert etiketler == {"info", "error"}
    assert all(s["stream"]["app"] == "tarife-radari" for s in gelen["body"]["streams"])


def test_gonderim_hatasi_turu_durdurmaz(cfg, monkeypatch):
    monkeypatch.setenv("LOKI_URL", "https://logs-ornek.grafana.net/loki/api/v1/push")
    monkeypatch.setenv("LOKI_USER", "123456")
    monkeypatch.setenv("LOKI_TOKEN", "glc_ornekanahtar123")

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("bağlantı yok")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    not_ = izleme.gonder(cfg, rapor(), 5.0, client=client)
    assert not_ and "gönderilemedi" in not_


def _sahte_loki(monkeypatch, url="https://logs-ornek.grafana.net"):
    monkeypatch.setenv("LOKI_URL", url)
    monkeypatch.setenv("LOKI_USER", "123456")
    monkeypatch.setenv("LOKI_TOKEN", "glc_ornekanahtar123")
    gelen: dict = {"satirlar": []}

    def handler(request: httpx.Request) -> httpx.Response:
        govde = json.loads(request.content.decode("utf-8"))
        gelen["govde"] = govde
        for s in govde["streams"]:
            gelen["satirlar"] += [(s["stream"]["level"], json.loads(v[1])) for v in s["values"]]
        return httpx.Response(204)

    return gelen, httpx.Client(transport=httpx.MockTransport(handler))


def test_kanal_yalnizca_satir_basindan_okunur():
    assert izleme._kanal("Gönderilemedi (tech): [KAYNAK HATASI] UAB: zaman aşımı") == "telegram"
    assert izleme._kanal("Gönderilemedi (email): Telegram duyurusu: 535") == "email"
    assert izleme._kanal("E-posta gönderildi: WhatsApp ve Telegram özeti") == "email"
    assert izleme._kanal("Telegram'a gönderildi: E-posta kanalı arızalı") == "telegram"
    assert izleme._kanal("WhatsApp'a gönderilemedi (1. alıcı): konu: 131047") == "whatsapp"
    assert izleme._kanal("E-posta hatası Telegram'a bildirildi.") == "telegram"


def test_hata_siniflandirma_kenar_durumlari():
    assert not izleme._hata_mi("E-posta hatası Telegram'a bildirildi.")
    assert izleme._hata_mi("E-posta hatası Telegram'a bildirilemedi: Telegram ayarlı değil.")
    assert izleme._hata_mi("Tarife belgesi indirilemedi: 2027 tarifesi (zaman aşımı)")
    assert izleme._hata_mi("E-posta 3 günden uzun süredir gönderilemiyor, bu mesaj için bırakıldı: konu")


def test_tur_durumu_kismi_ve_hata():
    r = rapor()
    tur = [o for _, o in izleme.kayitlar(r, 1.0) if o["olay"] == "tur"][0]
    assert tur["durum"] == "kismi"
    assert "cpu_sn" in tur and tur["tetik"]
    r.sources = [("a", "HATA", "x"), ("b", "HATA", "y")]
    tur = [o for _, o in izleme.kayitlar(r, 1.0) if o["olay"] == "tur"][0]
    assert tur["durum"] == "hata"
    r.sources = [("a", "tamam", "x")]
    r.messages, r.notes = [], []
    seviye, tur = [(s, o) for s, o in izleme.kayitlar(r, 1.0) if o["olay"] == "tur"][0]
    assert tur["durum"] == "tamam" and seviye == "info"


def test_tetik_kaynagi(monkeypatch):
    monkeypatch.delenv("RADAR_TETIK", raising=False)
    monkeypatch.delenv("GITHUB_EVENT_NAME", raising=False)
    assert izleme.tetik() == "yerel"
    monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule")
    assert izleme.tetik() == "schedule"
    monkeypatch.setenv("RADAR_TETIK", "zamanlayici")
    assert izleme.tetik() == "zamanlayici"


def test_cokme_kaydi(cfg, monkeypatch):
    gelen, client = _sahte_loki(monkeypatch)
    cfg.settings.smtp_password = r'sif"re\gizli'
    not_ = izleme.cokme(cfg, RuntimeError(r'beklenmeyen: sif"re\gizli'), 3.2, client=client)
    assert not_ and "gönderildi" in not_
    assert len(gelen["satirlar"]) == 1
    seviye, olay = gelen["satirlar"][0]
    assert seviye == "error" and olay["olay"] == "tur" and olay["durum"] == "coktu"
    assert "RuntimeError" in olay["hata"] and "gizli" not in olay["hata"]


def test_kacislanan_sifre_ve_rastgele_eposta_maskelenir(cfg, monkeypatch):
    gelen, client = _sahte_loki(monkeypatch)
    cfg.settings.smtp_password = r'a"b\c-gizli'
    r = rapor()
    r.messages = [r'Gönderilemedi (email): konu: a"b\c-gizli reddedildi; yabanci@baska-alan.com.tr bilinmiyor']
    izleme.gonder(cfg, r, 1.0, client=client)
    ham = json.dumps(gelen["govde"], ensure_ascii=False)
    assert "gizli" not in ham
    assert "yabanci@baska-alan.com.tr" not in ham


def test_http_adresi_reddedilir(cfg, monkeypatch):
    gelen, client = _sahte_loki(monkeypatch, url="http://logs-ornek.grafana.net")
    assert not izleme.aktif()
    not_ = izleme.gonder(cfg, rapor(), 1.0, client=client)
    assert not_ and "https" in not_
    assert gelen["satirlar"] == []


def test_grafana_anahtar_deseni():
    from radar.guvenlik import redact
    anahtar = "glc_" + "eyJvIjoiMTIzNDU2Nzg5MCIsIm4iOiJvdG95b2wi" + "fQ=="
    assert anahtar not in redact(f"token={anahtar} son")
    servis = "glsa_" + "AbCdEfGhIjKlMnOpQrStUvWxYz012345" + "_0a1b2c3d"
    assert servis not in redact(f"Authorization: Bearer {servis}")


def test_deneme_turu_grafana_ya_yazilmaz(cfg, monkeypatch):
    from types import SimpleNamespace

    from radar import cli

    cagrilar = []
    monkeypatch.setattr(izleme, "gonder", lambda *a, **k: cagrilar.append("gonder"))
    monkeypatch.setattr("radar.pipeline.run_once", lambda *a, **k: rapor())
    args = SimpleNamespace(zaman=None, bildirim_yok=True, deneme=True)
    cli.cmd_calistir(args, cfg)
    assert cagrilar == []


def test_cokme_bildirilir_ve_hata_iletilir(cfg, monkeypatch):
    from types import SimpleNamespace

    from radar import cli

    cagrilar = []
    monkeypatch.setattr(izleme, "cokme", lambda cfg, exc, sure, client=None: cagrilar.append(type(exc).__name__))

    def patla(*a, **k):
        raise ValueError("bozuk veri")

    monkeypatch.setattr("radar.pipeline.run_once", patla)
    args = SimpleNamespace(zaman=None, bildirim_yok=True, deneme=False)
    with pytest.raises(ValueError):
        cli.cmd_calistir(args, cfg)
    assert cagrilar == ["ValueError"]
