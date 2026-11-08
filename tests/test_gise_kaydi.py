"""Gişe kaydı (config/giseler.yaml), il-bölge tablosu ve geçişlerin yapılandırmadaki konumları.

Otoyol gişelerinin konumları yalnızca bizim kaydımızdan gelir; radar çalışırken dışarıdan konum alınmaz.
"""

from __future__ import annotations

import json
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
