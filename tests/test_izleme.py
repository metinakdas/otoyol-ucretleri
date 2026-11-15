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
