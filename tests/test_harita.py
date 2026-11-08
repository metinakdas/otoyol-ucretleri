"""Harita: il-bölge tablosu, OpenStreetMap gişe verisinin ayrıştırılması ve aylık yenileme."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timedelta

import pytest

from radar import bolgeler, harita
from radar.config import ConfigError, load_config
from radar.pipeline import run_once
from radar.store import Store
from radar.timeutil import TZ, to_iso

from conftest import ROOT

OVERPASS = "https://overpass-api.de/api/interpreter"
YEDEK = "https://overpass.kumi.systems/api/interpreter"
T0 = datetime(2026, 11, 9, 10, 0, tzinfo=TZ)


def area(code: str) -> dict:
    return {"type": "area", "id": 3600000000 + int(code[-2:]), "tags": {"ISO3166-2": code, "boundary": "administrative"}}


def node(i: int, lat: float, lon: float, **tags) -> dict:
    tags = tags or {"barrier": "toll_booth"}
    return {"type": "node", "id": i, "lat": lat, "lon": lon, "tags": tags}


def road(i: int, ref: str | None, name: str | None = None, highway: str = "motorway") -> dict:
    tags = {"highway": highway}
    if ref:
        tags["ref"] = ref
    if name:
        tags["name"] = name
    return {"type": "way", "id": i, "tags": tags}


ELEMENTS = [
    area("TR-41"),
    node(1, 40.7800, 29.6000, barrier="toll_booth", name="Batı Gişeleri"), road(10, "O-4", "Anadolu Otoyolu"),
    node(2, 40.7804, 29.6006, barrier="toll_booth", name="Batı Gişeleri"), road(11, "O-4", "Anadolu Otoyolu"),
    road(12, None, None, "motorway_link"),
    node(3, 40.7806, 29.6010), road(13, "O-4", "Anadolu Otoyolu"),            # adsız şerit, ~90 m
    node(4, 40.7600, 29.7000, highway="toll_gantry"), road(14, "O-7", "Kuzey Marmara Otoyolu"),
    node(5, 40.7000, 29.9000), road(15, "D-100", None, "trunk"),
    area("TR-06"),
    node(6, 39.9500, 32.6000, barrier="toll_booth", name="Test Gişeleri"), road(16, "O-4", "Anadolu Otoyolu"),
    node(7, 39.5000, 32.7000, barrier="toll_booth", name="Gişe"), road(17, "O-21", "Ankara-Niğde Otoyolu"),
    {"type": "way", "id": 99, "center": {"lat": 39.9, "lon": 32.9}, "tags": {"barrier": "toll_booth", "name": "Doğu Gişeleri"}},
    area("TR-77"),
    node(2, 40.7804, 29.6006, barrier="toll_booth", name="Batı Gişeleri"), road(11, "O-4", "Anadolu Otoyolu"),
]


# ------------------------------------------------------------------ il ve bölge

def test_il_ve_bolge_tablosu():
    assert len(bolgeler.ILLER) == 81
    sayilar = {b[0]: 0 for b in bolgeler.BOLGELER}
    for _, b in bolgeler.ILLER.values():
        sayilar[b] += 1
    assert sayilar == {"marmara": 11, "ege": 8, "akdeniz": 8, "ic-anadolu": 13,
                       "karadeniz": 18, "dogu-anadolu": 14, "guneydogu-anadolu": 9}
    assert bolgeler.plaka_bul("TR-34") == 34
    assert bolgeler.plaka_bul("istanbul") == 34
    assert bolgeler.plaka_bul("İĞDIR") == 76
    assert bolgeler.plaka_bul("41") == 41
    assert bolgeler.plaka_bul("TR-99") is None
    assert bolgeler.bolge(77) == "marmara"


def test_gecis_konumlari_yapilandirmadan(cfg):
    osmangazi = cfg.crossing("osmangazi")
    assert osmangazi.kind == "kopru" and osmangazi.provinces == [41, 77]
    assert cfg.crossing("avrasya-tuneli").kind == "tunel"
    for c in cfg.crossings:
        if c.panel:
            assert c.location and bolgeler.turkiye_icinde(*c.location), c.id


@pytest.mark.parametrize("ek, hata", [
    ("    il: Atlantis\n", "bilinmeyen il"),
    ("    konum: [48.85, 2.35]\n", "Türkiye sınırları dışında"),
    ("    tur: feribot\n", "tur"),
])
def test_yanlis_konum_ayari_yakalanir(tmp_path, ek, hata):
    shutil.copytree(ROOT / "config", tmp_path / "config")
    path = tmp_path / "config" / "crossings.yaml"
    text = path.read_text(encoding="utf-8")
    # kgm-otoyollari kaydının sonuna yanlış satırı ekle (önceki değerleri ezer)
    text = text.replace("    panel: false\n    tur: otoyol\n", "    panel: false\n    tur: otoyol\n" + ek)
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError, match=hata):
        load_config(tmp_path)


# ------------------------------------------------------------------ ayrıştırma

def test_gise_noktalari_gruplanir_ve_bolgelere_ayrilir():
    data = harita.build_map(ELEMENTS, T0)
    pts = {p["id"]: p for p in data["noktalar"]}
    assert data["ozet"] == {"toplam": 6, "bolge": {"ic-anadolu": 3, "marmara": 3}}

    bati = pts["osm-node-1"]
    assert bati["ad"] == "Batı Gişeleri" and not bati["adsiz"]
    assert bati["nokta_sayisi"] == 3                     # iki adlı + bir adsız şerit
    assert (bati["yol"], bati["yol_adi"]) == ("O-4", "Anadolu Otoyolu")
    assert (bati["il"], bati["bolge"], bati["plaka"]) == ("Kocaeli", "marmara", 41)  # TR-77'de tekrar gelse de

    gantry = pts["osm-node-4"]
    assert gantry["tur"] == "serbest" and gantry["ad"] == "Serbest geçiş noktası (O-7)" and gantry["adsiz"]
    assert pts["osm-node-5"]["ad"] == "Gişe (D-100)"
    assert pts["osm-node-7"]["ad"] == "Gişe (O-21)" and pts["osm-node-7"]["adsiz"]   # "Gişe" ad sayılmaz
    dogu = pts["osm-way-99"]
    assert (dogu["ad"], dogu["il"], dogu["bolge"]) == ("Doğu Gişeleri", "Ankara", "ic-anadolu")

    # Sıra: bölge sırası (Marmara önce), sonra il, adlılar önce
    assert [p["bolge"] for p in data["noktalar"]] == ["marmara"] * 3 + ["ic-anadolu"] * 3
    assert data["noktalar"][0]["id"] == "osm-node-1"
    assert "OpenStreetMap" in data["lisans"]


# ------------------------------------------------------------------ yenileme

def _setup(cfg, web, elements=ELEMENTS):
    cfg.settings.map_refresh_days = 30
    cfg.settings.map_retry_hours = 24
    cfg.settings.overpass_urls = [OVERPASS, YEDEK]
    web.json(OVERPASS, {"version": 0.6, "elements": elements})
    return Store(cfg.data_dir), {}


def test_yenileme_takvime_uyar(cfg, web):
    store, state = _setup(cfg, web)
    note = harita.refresh(cfg, store, state, T0, transport=web.transport)
    assert note == "Harita: 6 gişe noktası güncellendi (OpenStreetMap)"
    assert store.read("harita.json", None)["olusturma"] == to_iso(T0)
    assert state["_harita"]["son_basari"] == to_iso(T0) and state["_harita"]["hata"] is None
    n = len(web.requests)

    for later in (timedelta(hours=2), timedelta(days=10), timedelta(days=29, hours=23)):
        assert harita.refresh(cfg, store, state, T0 + later, transport=web.transport) is None
    assert len(web.requests) == n

    assert harita.refresh(cfg, store, state, T0 + timedelta(days=30, hours=1), transport=web.transport)
    assert len(web.requests) == n + 1


def test_hata_eski_veriyi_korur_ve_bekler(cfg, web):
    store, state = _setup(cfg, web)
    harita.refresh(cfg, store, state, T0, transport=web.transport)
    web.error(OVERPASS, 504)
    web.error(YEDEK, 429)
    t1 = T0 + timedelta(days=31)
    note = harita.refresh(cfg, store, state, t1, transport=web.transport)
    assert note.startswith("Harita verisi alınamadı") and "504" in note and "429" in note
    assert store.read("harita.json", None)["olusturma"] == to_iso(T0)
    assert state["_harita"]["hata"]
    assert harita.refresh(cfg, store, state, t1 + timedelta(hours=3), transport=web.transport) is None
    web.json(OVERPASS, {"elements": ELEMENTS})
    assert harita.refresh(cfg, store, state, t1 + timedelta(hours=25), transport=web.transport).startswith("Harita:")
    assert state["_harita"]["hata"] is None


def test_yarim_sonuc_ve_ani_dusus_reddedilir(cfg, web):
    store, state = _setup(cfg, web)
    web.json(OVERPASS, {"remark": "runtime error: Query timed out in \"query\" at line 9", "elements": ELEMENTS[:3]})
    web.json(YEDEK, {"elements": []})
    note = harita.refresh(cfg, store, state, T0, transport=web.transport)
    assert "tamamlayamadı" in note and not store.read("harita.json", None)

    web.json(OVERPASS, {"elements": ELEMENTS})
    harita.refresh(cfg, store, state, T0, force=True, transport=web.transport)
    web.json(OVERPASS, {"elements": ELEMENTS[:3]})   # 6 → 1 nokta
    note = harita.refresh(cfg, store, state, T0 + timedelta(days=40), transport=web.transport)
    assert "eksik görünüyor" in note
    assert store.read("harita.json", None)["ozet"]["toplam"] == 6


def test_yedek_sunucu_kullanilir(cfg, web):
    store, state = _setup(cfg, web)
    web.error(OVERPASS, 503)
    web.json(YEDEK, {"elements": ELEMENTS})
    assert harita.refresh(cfg, store, state, T0, transport=web.transport).startswith("Harita: 6")
    assert web.requests == [OVERPASS, YEDEK]


def test_radar_turu_haritayi_yeniler_ve_panele_konum_yazar(cfg, web):
    _setup(cfg, web)
    report = run_once(cfg, now=T0, send=False, transport=web.transport)
    assert any(n.startswith("Harita: 6") for n in report.notes)
    panel = json.loads((cfg.data_dir / "panel.json").read_text(encoding="utf-8"))
    assert [b["id"] for b in panel["bolgeler"]][:2] == ["marmara", "ege"] and len(panel["bolgeler"]) == 7
    kopru = next(c for c in panel["crossings"] if c["id"] == "15-temmuz-sehitler")
    assert kopru["tur"] == "kopru" and kopru["iller"] == ["İstanbul"] and kopru["bolge"] == "marmara"
    assert kopru["konum"] == [41.0451, 29.0345]
    assert panel["harita"]["son_basari"] == to_iso(T0)

    # Deneme modunda Overpass'a gidilmez
    before = web.requests.count(OVERPASS)
    run_once(cfg, now=T0 + timedelta(days=60), send=False, dry_run=True, transport=web.transport)
    assert web.requests.count(OVERPASS) == before


def test_harita_guncelle_komutu_ilk_calistirmayi_bozmaz(cfg, monkeypatch, capsys):
    from radar import cli

    monkeypatch.setattr(harita, "fetch_elements", lambda c, transport=None: ELEMENTS)
    assert cli.cmd_harita(None, cfg) == 0
    out = capsys.readouterr().out
    assert "6 gişe noktası güncellendi" in out and "Marmara: 3" in out and "O-4 (2)" in out
    assert (cfg.data_dir / "harita.json").exists()
    # Radar hiç çalışmadıysa state.json yazılmaz; ilk tur yine sessiz başlangıç turu olur
    assert not (cfg.data_dir / "state.json").exists()
    report = run_once(cfg, now=T0, send=False, transport=_offline())
    assert report.first_run


def _offline():
    import httpx

    return httpx.MockTransport(lambda request: httpx.Response(404, text="yok"))


def test_yeni_overpass_bicimi_yol_dugum_listesiyle():
    elements = [
        area("TR-41"),
        node(1, 40.78, 29.60, barrier="toll_booth", name="Batı Gişeleri"),
        node(2, 40.7804, 29.6006, barrier="toll_booth", name="Batı Gişeleri"),
        node(4, 40.76, 29.70, highway="toll_gantry"),
        {"type": "way", "id": 10, "nodes": [9, 1, 2], "tags": {"highway": "motorway", "ref": "O-4", "name": "Anadolu Otoyolu"}},
        {"type": "way", "id": 11, "nodes": [4, 8], "tags": {"highway": "motorway", "ref": "O-7"}},
    ]
    pts = {p["id"]: p for p in harita.build_map(elements, T0)["noktalar"]}
    assert pts["osm-node-1"]["yol"] == "O-4" and pts["osm-node-1"]["nokta_sayisi"] == 2
    assert pts["osm-node-4"]["ad"] == "Serbest geçiş noktası (O-7)"
