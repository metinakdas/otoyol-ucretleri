"""Gişeden gişeye ücret tabloları: KGM PDF matrislerinin okunması, konum eşleme ve günlük yenileme.

Gerçek KGM PDF'lerinden iki küçük örnek tests/fixtures altında (kamu belgesi): İzmir–Aydın (üçgen tablo)
ve Kuzey Marmara Kınalı–Odayeri (yöne göre değişen kare tablo + serbest geçiş noktaları). Anadolu Otoyolu
PDF'i büyük olduğundan yapısı, pdfplumber'ın o PDF'ten çıkardığı gerçek hücrelerle taklit edilir.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from conftest import FIX
from radar import ucret_tablosu as ut
from radar.pipeline import run_once
from radar.store import Store
from radar.timeutil import TZ, to_iso

T0 = datetime(2026, 11, 9, 2, 0, tzinfo=TZ)
KGM_LIST = "https://www.kgm.gov.tr/Sayfalar/KGM/SiteTr/Otoyollar/UcretlerYeni.aspx"
BASE = "https://www.kgm.gov.tr/SiteCollectionDocuments/KGMdocuments/Otoyollar/OtoyolKopruUcret/2026Gecis_Ucret/"
IZMIR = BASE + "7-Izmir-Aydin.pdf"
KMO = BASE + "14-KMOAvrupaKinali-Odayeri.pdf"
FSM = BASE + "1-15Temmuz-FSM.pdf"


# ------------------------------------------------------------------ Anadolu Otoyolu yapısı

def _blok(ad, km, satirlar):
    rows = [[ad, ""] + [f"{k:.3f}".replace(".", ",") + " km" for k in km]]
    for sinif, degerler in enumerate(satirlar, 1):
        rows.append(["", str(sinif)] + [f"{v},00" for v in degerler])
    return rows


def anadolu_tablosu() -> list[list]:
    """5-AnadoluOtoyoluCamlica-Akinci.pdf tablosunun Körfez–Akyazı dilimi (hücreler PDF'teki gibi).

    PDF'teki iki tuhaflık da korunur: Körfez'in satırı bu dilimde yok (yalnızca sütunu var) ve
    Batı İzmit'in kendi sütunu yok: köşegeni Kandıra sütununa düşer.
    """
    header = ["İSTASYON", "ARAÇ SINIFI", "KÖRFEZ", "KANDIRA", "KARTEPE", "DOĞU İZMİT", "SAPANCA",
              "ADAPAZARI", "BEKİRPAŞA", "AKYAZI"]
    rows = [["ANADOLU OTOYOLU (Ç"] + [None] * 9, header]
    rows += _blok("BATI İZMİT", [7.0], [[40, 289], [45, 345], [49, 432], [56, 568], [115, 708], [15, 115]])
    rows += _blok("KANDIRA", [19.0], [[40, 289], [45, 345], [65, 432], [102, 568], [115, 708], [15, 115]])
    rows += _blok("KARTEPE", [24.25, 5.25], [[40, 40, 289], [45, 45, 345], [65, 49, 432], [102, 69, 568],
                                             [115, 115, 708], [15, 15, 115]])
    rows += _blok("DOĞU İZMİT", [26.35, 7.35, 2.1], [[40, 40, 40, 289], [45, 45, 45, 345], [56, 49, 49, 432],
                                                    [115, 69, 69, 568], [148, 115, 115, 708], [15, 15, 15, 115]])
    rows += _blok("SAPANCA", [45.85, 26.85, 21.6, 19.5],
                  [[49, 40, 40, 40, 250], [56, 45, 45, 45, 292], [102, 65, 65, 65, 407], [148, 115, 115, 103, 542],
                   [168, 148, 148, 115, 659], [20, 15, 15, 15, 102]])
    rows += _blok("ADAPAZARI", [59.35, 40.35, 35.1, 33.0, 13.5],
                  [[49, 49, 49, 49, 40, 250], [56, 56, 56, 56, 45, 292], [102, 69, 69, 65, 65, 407],
                   [148, 115, 115, 115, 73, 542], [168, 148, 148, 148, 115, 607], [20, 20, 20, 20, 15, 102]])
    rows += _blok("BEKİRPAŞA", [65.43, 46.43, 41.18, 39.08, 19.58, 6.08],
                  [[73, 49, 49, 49, 40, 40, 250], [82, 56, 56, 56, 45, 45, 292], [148, 102, 102, 69, 65, 49, 407],
                   [168, 148, 148, 115, 103, 69, 542], [193, 168, 168, 148, 115, 115, 595],
                   [33, 20, 20, 20, 15, 15, 102]])
    rows += _blok("AKYAZI", [75.15, 56.15, 50.9, 48.8, 29.3, 15.8, 9.725],
                  [[73, 49, 49, 49, 40, 40, 40, 250], [82, 56, 56, 56, 45, 45, 45, 292],
                   [148, 102, 102, 102, 69, 65, 49, 407], [168, 148, 148, 148, 102, 73, 69, 542],
                   [193, 168, 168, 168, 148, 115, 115, 595], [33, 20, 20, 20, 15, 15, 15, 102]])
    rows.append(["Not: Ücretlere KDV Dahildir."] + [None] * 9)
    width = len(header)
    return [r + [""] * (width - len(r)) for r in rows]


def test_anadolu_otoyolu_adapazari_akyazi():
    t = ut.tablo_coz(anadolu_tablosu()).to_dict()
    assert t["tur"] == "ucgen" and not t["yonlu"] and t["ucret_geri"] is None
    assert t["istasyonlar"] == ["Körfez", "Batı İzmit", "Kandıra", "Kartepe", "Doğu İzmit", "Sapanca",
                                "Adapazarı", "Bekirpaşa", "Akyazı"]
    a, b = t["istasyonlar"].index("Adapazarı"), t["istasyonlar"].index("Akyazı")
    assert t["ucret"][b][a] == [40, 45, 65, 73, 115, 15]
    assert t["km"][b][a] == 15.8
    assert t["azami"][b] == [250, 292, 407, 542, 595, 102]
    # Her satırda yalnızca önceki istasyonlar
    assert [len(r) for r in t["ucret"]] == list(range(9)) and [len(r) for r in t["km"]] == list(range(9))

    # Kendi sütunu olmayan Batı İzmit: önceki istasyona (Körfez) ücreti var, sonrakilerle yok
    assert t["ucret"][1][0] == [40, 45, 49, 56, 115, 15] and t["km"][1][0] == 7.0
    assert all(t["ucret"][i][1] is None for i in range(2, 9))
    # Kandıra sütunun sahibi: Kartepe'nin 5,25 km'lik hücresi Kandıra'ya yazılır
    assert t["km"][3][2] == 5.25
    # Satırı olmayan Körfez: azami yok, ama sonrakilerden ücreti var
    assert t["azami"][0] is None and t["ucret"][8][0] == [73, 82, 148, 168, 193, 33]
    assert any("Batı İzmit" in w and "sütunu yok" in w for w in t["uyarilar"])
    assert any("Körfez" in w and "satırı yok" in w for w in t["uyarilar"])


def test_bozuk_hucre_sessizce_kabul_edilmez():
    table = anadolu_tablosu()
    table[-3][4] = "1l5,00"   # Akyazı 5. sınıf, yanlış okunmuş hücre
    with pytest.raises(ut.UcretTablosuHatasi, match="ücret okunamadı"):
        ut.tablo_coz(table)
    table = anadolu_tablosu()
    table[4][1] = "7"         # bozuk sınıf sırası
    with pytest.raises(ut.UcretTablosuHatasi):
        ut.tablo_coz(table)


def test_tek_ucretli_kopru_matris_sayilmaz():
    assert ut.parse_matrix_pdf((FIX / "1-15Temmuz-FSM-2026.pdf").read_bytes(), ref=T0) == []


# ------------------------------------------------------------------ gerçek PDF'ler

def test_izmir_aydin_gercek_pdf():
    [t] = ut.parse_matrix_pdf((FIX / "ucret-7-Izmir-Aydin-2026.pdf").read_bytes(), ref=T0)
    assert t["istasyonlar"] == ["Işıkkent", "Tahtalıçay (Havalimanı)", "Torbalı", "Belevi", "Germencik", "Aydın Batı"]
    assert t["tur"] == "ucgen" and not t["yonlu"]
    assert t["ucret"][2][0] == [49, 56, 65, 102, 115, 20] and t["km"][2][0] == 23.15
    assert t["ucret"][5][4] == [49, 56, 65, 102, 115, 20] and t["km"][5][4] == 21.9
    assert t["azami"][0] == [73, 82, 115, 148, 168, 33]
    assert t["gecerlilik"] == "2026-01-01T00:00:00+03:00"
    assert "Ücretlere KDV Dahildir." in t["notlar"]


def test_yone_gore_degisen_kare_tablo_gercek_pdf():
    [t] = ut.parse_matrix_pdf((FIX / "ucret-14-KMOAvrupaKinali-Odayeri-2026.pdf").read_bytes(), ref=T0)
    assert t["istasyonlar"] == ["Kınalı", "Silivri", "Çatalca", "Nakkaş", "Yassıören", "Tayakadın", "Fatih"]
    assert t["tur"] == "kare" and t["yonlu"]
    # ucret[i][j]: j'den girip i'den çıkış; ucret_geri[i][j]: i'den girip j'den çıkış
    assert t["ucret"][1][0] == [65, 120, 120, 165, 225, 65]          # Kınalı → Silivri
    assert t["ucret_geri"][1][0] == [105, 120, 165, 195, 225, 65]    # Silivri → Kınalı
    assert t["ucret_geri"][6][0][2] == 480                           # PDF'te "4 8 0 , 0 0" yazılı hücre
    assert t["azami"][6] == [260, 410, 490, 630, 800, 195]
    assert t["km"] == [[None] * i for i in range(7)]
    assert t["gecerlilik"] == "2026-07-01T00:00:00+03:00"
    sgs = {(s["ad"], s["yon"]): s["ucret"] for s in t["serbest_gecis"]}
    assert len(sgs) == 15 and sgs[("21 (Terminal A)", "Kuzey - Güney")] == [19.5, 29.5, 34.5, 48, 60, 12]


def test_turkce_baslik_harfi():
    assert ut.baslik_harfi("ADAPAZARI") == "Adapazarı"
    assert ut.baslik_harfi("Ş.PINAR") == "Ş.Pınar"
    assert ut.baslik_harfi("İ.PINAR") == "İ.Pınar"
    assert ut.baslik_harfi("DÜZCE (GÖLYAKA)") == "Düzce (Gölyaka)"
    assert ut.baslik_harfi("İSKENDERUN OSB") == "İskenderun OSB"
    assert ut.baslik_harfi("YUMURTALIK SERBEST B.") == "Yumurtalık Serbest B."
    assert ut.baslik_harfi("MALKARA G-1") == "Malkara G-1"
    assert ut.baslik_harfi("KMO AKYAZI") == "KMO Akyazı"
    assert ut.baslik_harfi("ISPARTAKULE") == "Ispartakule"
    assert ut.baslik_harfi("Ankara Alın") == "Ankara Alın"   # küçük harf içeren ada dokunulmaz


# ------------------------------------------------------------------ konum eşleme

def _nokta(i, ad, lat, lon, yol=None, tur="gise"):
    return {"id": f"osm-node-{i}", "ad": ad, "adsiz": False, "tur": tur, "lat": lat, "lon": lon, "yol": yol}


HARITA = {"noktalar": [
    _nokta(1, "Işıkkent Gişeleri", 38.33, 27.21),
    _nokta(2, "Havalimanı Gişeleri", 38.27, 27.22),
    _nokta(3, "Torbalı Otomatik Geçiş Sistemi", 38.18, 27.32, tur="serbest"),
    _nokta(4, "Belevi Gişeleri", 38.03, 27.45, yol="O-31"),
    _nokta(5, "Germencik Gişeleri", 37.88, 27.58),
    _nokta(6, "Germencik Gişeleri", 39.90, 32.80),            # aynı adlı, çok uzak: belirsiz
    _nokta(7, "Aydın Batı Gişeleri", 37.85, 27.75, yol="O-4"),  # başka otoyola ait: elenir
    _nokta(8, "Kınalı Gişeleri", 41.11, 28.17, yol="O-6"),
    _nokta(9, "Kınalı Gişeleri", 41.13, 28.21, yol="O-7"),
]}


def test_konumlar_guvenilir_eslesmeyle_yazilir():
    [t] = ut.parse_matrix_pdf((FIX / "ucret-7-Izmir-Aydin-2026.pdf").read_bytes(), ref=T0)
    [o] = ut.otoyol_kayitlari([t], IZMIR, "7- KGM İzmir - Aydın Otoyolu Geçiş Ücretleri")
    assert (o["id"], o["yol"]) == ("izmir-aydin", "O-31")
    info = ut.konumlari_esle(o, HARITA["noktalar"])
    konum = {s["ad"]: (s["lat"], s["lon"]) for s in o["istasyonlar"]}
    assert konum["Işıkkent"] == (38.33, 27.21)
    assert konum["Tahtalıçay (Havalimanı)"] == (38.27, 27.22)     # parantez içindeki adla
    assert konum["Torbalı"] == (38.18, 27.32)
    assert konum["Germencik"] == (37.88, 27.58)                   # komşu istasyonlara yakın olan seçilir
    assert konum["Aydın Batı"] == (None, None)                    # O-4'teki aynı adlı nokta alınmaz
    assert info == {"eslesen": 5, "toplam": 6, "yol": "O-31"}


def test_yol_mesafesiyle_celisen_eslesme_atilir():
    [t] = ut.parse_matrix_pdf((FIX / "ucret-7-Izmir-Aydin-2026.pdf").read_bytes(), ref=T0)
    [o] = ut.otoyol_kayitlari([t], IZMIR, "7- KGM İzmir - Aydın Otoyolu Geçiş Ücretleri")
    pts = [dict(p) for p in HARITA["noktalar"]]
    pts[2].update(lat=38.60, lon=27.90)    # Torbalı'yı 70 km öteye taşı: Işıkkent'e yol 23 km
    ut.konumlari_esle(o, pts)
    konum = {s["ad"]: s["lat"] for s in o["istasyonlar"]}
    assert konum["Torbalı"] is None and konum["Işıkkent"] == 38.33


def test_kinali_iki_ayri_otoyolda():
    [t] = ut.parse_matrix_pdf((FIX / "ucret-14-KMOAvrupaKinali-Odayeri-2026.pdf").read_bytes(), ref=T0)
    [o] = ut.otoyol_kayitlari([t], KMO, "14- Kuzey Marmara Avrupa (Kınalı - Odayeri) Otoyolu Geçiş Ücretleri")
    assert o["yol"] == "O-7"
    ut.konumlari_esle(o, HARITA["noktalar"])
    assert (o["istasyonlar"][0]["lat"], o["istasyonlar"][0]["lon"]) == (41.13, 28.21)


# ------------------------------------------------------------------ yenileme

def kgm_page() -> str:
    return f"""<html><body>
<a href="{FSM}">1- 15 Temmuz Şehitler ve Fatih Sultan Mehmet Köprüleri Geçiş Ücretleri Tarifesi</a>
<a href="{IZMIR}">7- KGM İzmir - Aydın Otoyolu (Işıkkent - Aydın Batı Kesimi ) Geçiş Ücretleri</a>
<a href="{KMO}">14- Kuzey Marmara Avrupa (Kınalı - Odayeri) Otoyolu Geçiş Ücretleri</a>
<a href="https://www.kgm.gov.tr/strateji.pdf">2024-2028 Stratejik Plan</a>
</body></html>"""


def _setup(cfg, web):
    web.html(KGM_LIST, kgm_page())
    web.pdf(FSM, FIX / "1-15Temmuz-FSM-2026.pdf")
    web.pdf(IZMIR, FIX / "ucret-7-Izmir-Aydin-2026.pdf")
    web.pdf(KMO, FIX / "ucret-14-KMOAvrupaKinali-Odayeri-2026.pdf")
    store = Store(cfg.data_dir)
    store.write("harita.json", HARITA)
    return store, {}


def test_yenileme_dosyayi_yazar(cfg, web):
    store, state = _setup(cfg, web)
    note = ut.refresh(cfg, store, state, T0, transport=web.transport)
    assert note == "Ücret tablosu: 2 otoyol, 13 istasyon güncellendi"
    data = store.read("ucret-tablosu.json", None)
    assert data["schema"] == 1 and data["olusturma"] == to_iso(T0) and data["kaynak"] == "KGM geçiş ücreti tarifeleri"
    assert list(data["siniflar"]) == ["1", "2", "3", "4", "5", "6"] and "Motosiklet" in data["siniflar"]["6"]
    izmir, kmo = data["otoyollar"]
    assert izmir["id"] == "izmir-aydin" and izmir["belge"] == IZMIR
    assert izmir["belge_adi"].startswith("7- KGM İzmir - Aydın Otoyolu")
    assert izmir["istasyonlar"][0] == {"ad": "Işıkkent", "lat": 38.33, "lon": 27.21}
    assert set(izmir) >= {"id", "ad", "yol", "belge", "belge_adi", "istasyonlar", "ucret", "km", "azami"}
    assert kmo["id"] == "kmo-kinali-odayeri" and kmo["yonlu"] and kmo["ucret_geri"]
    st = state["_ucret_tablosu"]
    assert st["hata"] is None and st["hatalar"] == [] and st["konum"]["izmir-aydin"] == "5/6"
    fsm = next(d for d in st["belgeler"].values() if d["url"] == FSM)
    assert fsm["matris"] is False and fsm["otoyollar"] == [] and fsm["hata"] is None
    assert all("strateji" not in u for u in web.requests)

    # Günde bir: hemen ardından yeniden indirilmez
    n = len(web.requests)
    assert ut.refresh(cfg, store, state, T0 + timedelta(hours=3), transport=web.transport) is None
    assert len(web.requests) == n
    # Bir gün sonra yeniden bakılır; içerik aynıysa dosya yeniden yazılmaz
    assert ut.refresh(cfg, store, state, T0 + timedelta(hours=25), transport=web.transport) is None
    assert len(web.requests) > n
    assert store.read("ucret-tablosu.json", None)["olusturma"] == to_iso(T0)


def test_okunamayan_pdf_onceki_veriyi_korur(cfg, web):
    store, state = _setup(cfg, web)
    ut.refresh(cfg, store, state, T0, transport=web.transport)
    before = store.read("ucret-tablosu.json", None)

    web.routes[IZMIR] = (200, b"%PDF-1.4 bozuk dosya", "application/pdf")
    t1 = T0 + timedelta(days=1, hours=1)
    note = ut.refresh(cfg, store, state, t1, transport=web.transport)
    assert note == "Ücret tablosu: 1 belge okunamadı, önceki veri korundu"
    after = store.read("ucret-tablosu.json", None)
    assert after == before
    st = state["_ucret_tablosu"]
    assert len(st["hatalar"]) == 1 and st["hatalar"][0].startswith("7- KGM İzmir")
    key = next(k for k, d in st["belgeler"].items() if d["url"] == IZMIR)
    assert st["belgeler"][key]["hata"] and st["belgeler"][key]["otoyollar"] == ["izmir-aydin"]

    # Sayfanın kendisi okunamazsa da dosya olduğu gibi kalır
    web.error(KGM_LIST, 503)
    note = ut.refresh(cfg, store, state, t1 + timedelta(days=1), transport=web.transport)
    assert note.startswith("Ücret tablosu alınamadı") and "503" in note
    assert store.read("ucret-tablosu.json", None) == before

    # Düzelince yeniden okunur ve hata temizlenir
    web.html(KGM_LIST, kgm_page())
    web.pdf(IZMIR, FIX / "ucret-7-Izmir-Aydin-2026.pdf")
    ut.refresh(cfg, store, state, t1 + timedelta(days=2), transport=web.transport)
    assert state["_ucret_tablosu"]["hatalar"] == [] and state["_ucret_tablosu"]["belgeler"][key]["hata"] is None
    assert store.read("ucret-tablosu.json", None)["otoyollar"] == before["otoyollar"]


def test_radar_turu_ucret_tablosunu_yazar_ve_hata_turu_bozmaz(cfg, web, monkeypatch):
    _setup(cfg, web)
    report = run_once(cfg, now=T0, send=False, transport=web.transport)
    assert "ucret-tablosu.json" in report.written
    assert json.loads((cfg.data_dir / "ucret-tablosu.json").read_text(encoding="utf-8"))["otoyollar"]

    web.routes[IZMIR] = (200, b"%PDF-1.4 bozuk dosya", "application/pdf")
    report = run_once(cfg, now=T0 + timedelta(days=2), send=False, transport=web.transport)
    assert "Ücret tablosu: 1 belge okunamadı, önceki veri korundu" in report.notes

    def patlat(*a, **k):
        raise RuntimeError("beklenmeyen hata")

    assert json.loads((cfg.data_dir / "ucret-tablosu.json").read_text(encoding="utf-8"))["otoyollar"]

    monkeypatch.setattr(ut, "refresh", patlat)
    report = run_once(cfg, now=T0 + timedelta(days=4), send=False, transport=web.transport)
    assert any(n.startswith("Ücret tablosu alınamadı") for n in report.notes)


def test_ucret_tablosu_komutu(cfg, web, monkeypatch, capsys):
    from radar import cli

    store, _ = _setup(cfg, web)
    real = ut.refresh
    monkeypatch.setattr(ut, "refresh", lambda c, s, st, now, force=False: real(c, s, st, now, force=force,
                                                                                transport=web.transport))
    assert cli.cmd_ucret_tablosu(None, cfg) == 0
    out = capsys.readouterr().out
    assert "2 otoyol tablosu" in out and "İzmir – Aydın Otoyolu" in out and "konum 5/6" in out
    assert not (cfg.data_dir / "state.json").exists()   # radar hiç çalışmadıysa ilk tur bozulmaz


def test_panel_sunucusu_dosyayi_sunar():
    from radar.panel import _allowed_path

    assert _allowed_path("/data/ucret-tablosu.json") == "/data/ucret-tablosu.json"
