"""Gişe kaydı (config/giseler.yaml), il-bölge tablosu ve geçişlerin yapılandırmadaki konumları.

Otoyol gişelerinin konumları yalnızca bizim kaydımızdan gelir; radar çalışırken dışarıdan konum alınmaz.
"""

from __future__ import annotations

import json
import re
import shutil

import pytest

from radar import bolgeler
from radar import ucret_tablosu as ut
from radar.config import ConfigError, load_config

from conftest import ROOT

KAYIT = ROOT / "config" / "giseler.yaml"


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


# ------------------------------------------------------------------ gerçek kayıt

def test_kayit_gecerli_ve_tarifedeki_her_gise_kayitli(cfg):
    """config/giseler.yaml okunur ve depodaki ücret tablosunun her istasyonu kayıtta vardır."""
    assert cfg.gise_kaydi == KAYIT
    kayit = ut.gise_kaydi_oku(KAYIT)
    tablo = json.loads((ROOT / "data" / "ucret-tablosu.json").read_text(encoding="utf-8"))
    eksik = []
    for o in tablo["otoyollar"]:
        gises = kayit.get(o["id"]) or {}
        eksik += [f"{o['id']}/{s['ad']}" for s in o["istasyonlar"] if ut._ad_anahtari(s["ad"]) not in gises]
    assert eksik == []
    for oid, gises in kayit.items():
        for g in gises.values():
            assert g["il"] and g["bolge"], (oid, g["ad"])     # konumu bilinmeyenin bile ili yazılır


def test_kayittaki_komsu_giseler_yol_km_siyle_celismez():
    """Kuş uçuşu uzaklık tarifedeki yol km'sini (biraz payla) aşamaz: yanlış yere konmuş gişeyi yakalar."""
    import math

    def uzaklik(a, b):
        p1, p2 = math.radians(a[0]), math.radians(b[0])
        dp, dl = p2 - p1, math.radians(b[1] - a[1])
        h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
        return 2 * 6371.0 * math.asin(math.sqrt(h))

    kayit = ut.gise_kaydi_oku(KAYIT)
    tablo = json.loads((ROOT / "data" / "ucret-tablosu.json").read_text(encoding="utf-8"))
    celiski = []
    for o in tablo["otoyollar"]:
        gises = kayit[o["id"]]
        pos = [gises[ut._ad_anahtari(s["ad"])] for s in o["istasyonlar"]]
        km = o.get("km") or []
        for i in range(len(pos)):
            for j in range(i):
                k = km[i][j] if i < len(km) and j < len(km[i]) else None
                if k and pos[i]["lat"] is not None and pos[j]["lat"] is not None:
                    d = uzaklik((pos[i]["lat"], pos[i]["lon"]), (pos[j]["lat"], pos[j]["lon"]))
                    if d > k * 1.15 + 3:
                        celiski.append(f"{o['id']}: {pos[j]['ad']} → {pos[i]['ad']} km={k} kuş={d:.1f}")
    assert celiski == []


# ------------------------------------------------------------------ okuma ve eşleme

def _yaz(tmp_path, text: str):
    path = tmp_path / "giseler.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_kayit_eslemesi_harf_farkina_dayanikli(tmp_path):
    path = _yaz(tmp_path, """
izmir-aydin:
  - ad: ISIKKENT
    konum: [38.34124, 27.23407]
    il: İzmir
  - ad: Tahtalıçay  (Havalimanı)
    konum: [38.27234, 27.21707]
    il: izmir
  - ad: Aydın Batı
    konum: null
    il: Aydın
""")
    kayit = ut.gise_kaydi_oku(path)
    otoyollar = [{"id": "izmir-aydin", "ad": "İzmir – Aydın Otoyolu", "istasyonlar": [
        {"ad": "Işıkkent", "lat": 1.0, "lon": 1.0},
        {"ad": "Tahtalıçay (Havalimanı)", "lat": None, "lon": None},
        {"ad": "Aydın Batı", "lat": None, "lon": None},
        {"ad": "Torbalı", "lat": 38.1, "lon": 27.3},           # kayıtta yok: eski konum da silinir
    ]}, {"id": "baska-otoyol", "ad": "Başka", "istasyonlar": [{"ad": "Işıkkent", "lat": None, "lon": None}]}]
    kayitsiz = ut.konumlari_uygula(otoyollar, kayit)
    st = otoyollar[0]["istasyonlar"]
    assert st[0] == {"ad": "Işıkkent", "lat": 38.34124, "lon": 27.23407, "il": "İzmir", "bolge": "ege"}
    assert (st[1]["lat"], st[1]["il"]) == (38.27234, "İzmir")
    assert st[2] == {"ad": "Aydın Batı", "lat": None, "lon": None, "il": "Aydın", "bolge": "ege"}  # kayıtlı, konumsuz
    assert st[3] == {"ad": "Torbalı", "lat": None, "lon": None, "il": None, "bolge": None}
    # Aynı ad başka otoyolda kayıtlı değilse eşleşmez (eşleşme otoyol kimliği + ad)
    assert otoyollar[1]["istasyonlar"][0]["lat"] is None
    assert kayitsiz == [
        {"otoyol": "izmir-aydin", "otoyol_adi": "İzmir – Aydın Otoyolu", "ad": "Torbalı"},
        {"otoyol": "baska-otoyol", "otoyol_adi": "Başka", "ad": "Işıkkent"},
    ]


@pytest.mark.parametrize("text, hata", [
    ("a:\n  - ad: X\n    konum: [48.85, 2.35]\n", "Türkiye dışında"),
    ("a:\n  - ad: X\n    konum: [40.1]\n", "enlem, boylam"),
    ("a:\n  - ad: X\n    il: Atlantis\n", "bilinmeyen il"),
    ("a:\n  - ad: X\n  - ad: x\n", "iki kez"),
    ("a:\n  - konum: null\n", "adı olmayan"),
    ("a: X\n", "gişe listesi"),
    ("a: [\n", "okunamadı"),
])
def test_bozuk_kayit_yakalanir(tmp_path, text, hata):
    with pytest.raises(ut.GiseKaydiHatasi, match=hata):
        ut.gise_kaydi_oku(_yaz(tmp_path, text))


def test_kayit_dosyasi_yoksa_bos(tmp_path):
    assert ut.gise_kaydi_oku(tmp_path / "yok.yaml") == {}


def test_radar_dosyalari_haritaya_dis_kaynak_kullanmaz():
    """Radar kodunda OpenStreetMap/Overpass'tan veri çeken bir adım kalmamalı (karolar yalnızca panelde)."""
    for path in (ROOT / "radar").glob("*.py"):
        text = path.read_text(encoding="utf-8").lower()
        assert "overpass" not in text, path.name
    assert not (ROOT / "radar" / "harita.py").exists()


# ------------------------------------------------------------------ serbest geçiş noktaları ve bağlantılar

def _tablo():
    return json.loads((ROOT / "data" / "ucret-tablosu.json").read_text(encoding="utf-8"))


def _km(a, b):
    return ut._uzaklik((a["lat"], a["lon"]), (b["lat"], b["lon"]))


def test_serbest_gecis_kaydi_tarifedeki_her_satiri_kapsar():
    """Tablolardaki her serbest geçiş satırı kayıtta; SGS adlı istasyonlar serbest, 'Serbest Bölge' değil."""
    kayit = ut.gise_kaydi_oku(KAYIT)
    serbest = ut.serbest_kaydi_oku(KAYIT)
    tablo = _tablo()
    eksik = [f"{o['id']}/{r['ad']}" for o in tablo["otoyollar"] for r in o["serbest_gecis"]
             if ut._ad_anahtari(r["ad"]) not in (serbest.get(o["id"]) or {})]
    assert eksik == []
    assert sum(len(o["serbest_gecis"]) for o in tablo["otoyollar"]) >= 40
    for o in tablo["otoyollar"]:
        for s in o["istasyonlar"]:
            g = kayit[o["id"]][ut._ad_anahtari(s["ad"])]
            if re.search(r"\bSGS\b", s["ad"]):
                assert g["serbest"] and s.get("serbest") is True, s["ad"]
            if "serbest b" in s["ad"].lower():          # Serbest Bölge çıkışı serbest geçiş değildir
                assert not g["serbest"] and "serbest" not in s, s["ad"]
        for r in o["serbest_gecis"]:                    # yayımlanan tabloda konum alanları var
            assert {"lat", "lon", "il", "bolge"} <= set(r), (o["id"], r["ad"])
    for oid, rows in serbest.items():
        for p in rows.values():
            assert p["il"] and p["bolge"], (oid, p["ad"])


def test_serbest_noktalar_ayni_otoyolun_giselerine_yakin():
    """Her serbest geçiş noktası aynı otoyolun en yakın gişesinden 40 km'den uzak olamaz (yanlış yer)."""
    kayit = ut.gise_kaydi_oku(KAYIT)
    for oid, rows in ut.serbest_kaydi_oku(KAYIT).items():
        gises = [g for g in kayit[oid].values() if g["lat"] is not None]
        for p in rows.values():
            if p["lat"] is not None:
                assert min(_km(p, g) for g in gises) < 40, (oid, p["ad"])


def test_baglantilar_kayitta_gecerli_ve_yakin():
    """Bağlantının iki ucu tarifede var, farklı tablolarda; kuş uçuşu uzaklık yol km'sini aşmaz.

    Kavşak bağlantıları (yol_km ≤ 5) birkaç km içindedir; daha uzun olanlar ara kesimi gişesiz aynı
    otoyoldur ve 60 km'yi geçmez.
    """
    kayit = ut.gise_kaydi_oku(KAYIT)
    baglantilar = ut.baglanti_kaydi_oku(KAYIT)
    tablo = {o["id"]: o for o in _tablo()["otoyollar"]}
    assert len(baglantilar) >= 10
    for b in baglantilar:
        uclar = []
        for u in (b["a"], b["b"]):
            assert u["otoyol"] in tablo, u
            adlar = [ut._ad_anahtari(s["ad"]) for s in tablo[u["otoyol"]]["istasyonlar"]]
            assert ut._ad_anahtari(u["ad"]) in adlar, u
            uclar.append(kayit[u["otoyol"]][ut._ad_anahtari(u["ad"])])
        assert b["a"]["otoyol"] != b["b"]["otoyol"]
        assert b["not"] and 0 < b["yol_km"] <= 60
        assert uclar[0]["lat"] is not None and uclar[1]["lat"] is not None, b
        d = _km(*uclar)
        assert d <= b["yol_km"] + 1, (b["a"]["ad"], b["b"]["ad"], d)
        if b["yol_km"] <= 5:
            assert d <= 5, (b["a"]["ad"], b["b"]["ad"], d)
        for yon in ("ab", "ba"):
            for r in b["ara_serbest"][yon]:
                rows = tablo[r["otoyol"]]["serbest_gecis"]
                assert any(ut._ad_anahtari(x["ad"]) == ut._ad_anahtari(r["ad"]) and x["yon"] == r["yon"]
                           for x in rows), r


def test_yayimlanan_baglantilar_tabloyla_tutarli():
    """data/ucret-tablosu.json'daki bağlantılar: indeksler doğru istasyonu ve serbest geçiş satırını gösterir."""
    data = _tablo()
    tablo = {o["id"]: o for o in data["otoyollar"]}
    assert len(data["baglantilar"]) == len(ut.baglanti_kaydi_oku(KAYIT))
    for b in data["baglantilar"]:
        assert set(b) == {"a", "b", "tek_yon", "yol_km", "uzaklik_km", "ara_serbest", "ucretlendirme", "not"}
        for u in (b["a"], b["b"]):
            assert tablo[u["otoyol"]]["istasyonlar"][u["i"]]["ad"] == u["ad"]
        assert b["ucretlendirme"] == "ayri" and b["uzaklik_km"] is not None
        for yon in ("ab", "ba"):
            for r in b["ara_serbest"][yon]:
                x = tablo[r["otoyol"]]["serbest_gecis"][r["j"]]
                assert (x["ad"], x["yon"]) == (r["ad"], r["yon"])
    # İzmit Kuzey (KMO) → Paşaköy (YSS) sorusu Kurnaköy bağlantısıyla yanıtlanabilir
    assert any({b["a"]["ad"], b["b"]["ad"]} == {"Kurnaköy", "Kurnaköy 2"} for b in data["baglantilar"])
    assert tablo["yss-kuzey-cevre"]["dahil_gecisler"] == ["yavuz-sultan-selim"]
    assert tablo["izmir-aydin"]["dahil_gecisler"] == []


_BAG = "baglantilar:\n  - {a: {otoyol: x, ad: A}, b: {otoyol: y, ad: B}, yol_km: 1, not: n"


@pytest.mark.parametrize("text, hata", [
    ("baglantilar:\n  - {a: {otoyol: x, ad: A}, b: {otoyol: x, ad: B}, yol_km: 1, not: n}\n", "aynı tabloda"),
    ("baglantilar:\n  - {a: {otoyol: x, ad: A}, b: {otoyol: y, ad: B}, yol_km: 1}\n", "not yazılmalı"),
    ("baglantilar:\n  - {a: {otoyol: x, ad: A}, b: {otoyol: y, ad: B}, not: n}\n", "yol_km"),
    ("baglantilar:\n  - {a: {otoyol: x}, b: {otoyol: y, ad: B}, yol_km: 1, not: n}\n", "otoyol, ad"),
    (_BAG + "}\n  - {a: {otoyol: y, ad: b}, b: {otoyol: x, ad: a}, yol_km: 1, not: n}\n", "iki kez"),
    (_BAG + ", ara_serbest: {ileri: []}}\n", "ab ve ba"),
    (_BAG + ", tek_yon: evet}\n", "tek_yon"),
    ("baglantilar: {a: 1}\n", "liste"),
])
def test_bozuk_baglanti_kaydi_yakalanir(tmp_path, text, hata):
    with pytest.raises(ut.GiseKaydiHatasi, match=hata):
        ut.baglanti_kaydi_oku(_yaz(tmp_path, text))


@pytest.mark.parametrize("text, hata", [
    ("serbest_gecis:\n  x:\n    - {ad: A, satirlar: B}\n", "satirlar"),
    ("serbest_gecis:\n  x:\n    - {ad: A, satirlar: [B]}\n    - {ad: C, satirlar: [b]}\n", "iki kez"),
    ("serbest_gecis:\n  x:\n    - {ad: A, konum: [48.8, 2.3]}\n", "Türkiye dışında"),
    ("serbest_gecis: [1]\n", "otoyol kimlikleri"),
    ("x:\n  - {ad: A, serbest: evet}\n", "serbest true ya da false"),
])
def test_bozuk_serbest_kaydi_yakalanir(tmp_path, text, hata):
    with pytest.raises(ut.GiseKaydiHatasi, match=hata):
        path = _yaz(tmp_path, text)
        ut.gise_kaydi_oku(path)
        ut.serbest_kaydi_oku(path)


def test_serbest_bayragi_satir_konumlari_ve_baglanti_cozumu(tmp_path):
    path = _yaz(tmp_path, """
serbest_gecis:
  kmo:
    - {ad: Kargo, satirlar: [24 (Kargo A), 24 (Kargo B)], konum: [41.23771, 28.81599], il: İstanbul}
baglantilar:
  - a: {otoyol: kmo, ad: Fatih}
    b: {otoyol: yss, ad: Odayeri}
    yol_km: 9
    not: O-7
    ara_serbest:
      ab: [{otoyol: kmo, ad: 24 (Kargo A), yon: Kuzey - Güney}]
      ba: [{otoyol: kmo, ad: 24 (Kargo B)}]
  - {a: {otoyol: kmo, ad: Fatih}, b: {otoyol: yss, ad: Yok}, yol_km: 1, not: n}
kmo:
  - {ad: Fatih, konum: [41.24345, 28.71436], il: İstanbul, serbest: true}
yss:
  - {ad: Odayeri, konum: [41.23794, 28.82095], il: İstanbul}
""")
    otoyollar = [
        {"id": "kmo", "ad": "KMO", "istasyonlar": [{"ad": "Fatih"}],
         "serbest_gecis": [{"ad": "24 (Kargo A)", "yon": "Kuzey - Güney", "ucret": [12] * 6},
                           {"ad": "24 (Kargo B)", "yon": "Güney - Kuzey", "ucret": [12] * 6},
                           {"ad": "21 (Terminal A)", "yon": "Kuzey - Güney", "ucret": [19.5] * 6},
                           {"ad": "21 (Terminal A)", "yon": "Güney - Kuzey", "ucret": [19.5] * 6}]},
        {"id": "yss", "ad": "YSS", "istasyonlar": [{"ad": "Odayeri", "serbest": True}], "serbest_gecis": []},
    ]
    kayitsiz = ut.konumlari_uygula(otoyollar, ut.gise_kaydi_oku(path), ut.serbest_kaydi_oku(path))
    assert otoyollar[0]["istasyonlar"][0]["serbest"] is True
    assert "serbest" not in otoyollar[1]["istasyonlar"][0]           # kayıtta yoksa eski bayrak silinir
    rows = otoyollar[0]["serbest_gecis"]
    assert (rows[0]["lat"], rows[0]["lon"], rows[0]["il"], rows[0]["bolge"]) == (41.23771, 28.81599, "İstanbul", "marmara")
    assert rows[1]["lat"] == 41.23771 and rows[2]["lat"] is None
    # Kayıtta olmayan satır bir kez (iki yönü olsa da) bildirilir
    assert kayitsiz == [{"otoyol": "kmo", "otoyol_adi": "KMO", "ad": "21 (Terminal A)", "tur": "serbest"}]

    baglantilar, eksik = ut.baglantilari_coz(otoyollar, ut.baglanti_kaydi_oku(path))
    assert baglantilar == [{
        "a": {"otoyol": "kmo", "i": 0, "ad": "Fatih"}, "b": {"otoyol": "yss", "i": 0, "ad": "Odayeri"},
        "tek_yon": False, "yol_km": 9.0, "uzaklik_km": 8.9, "ucretlendirme": "ayri", "not": "O-7",
        "ara_serbest": {"ab": [{"otoyol": "kmo", "j": 0, "ad": "24 (Kargo A)", "yon": "Kuzey - Güney"}],
                        "ba": [{"otoyol": "kmo", "j": 1, "ad": "24 (Kargo B)", "yon": "Güney - Kuzey"}]},
    }]
    assert eksik == ["Fatih ↔ Yok: tabloda yok: yss / Yok"]
