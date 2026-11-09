"""Avrasya Tüneli ücret tablosu: sitenin JSON yanıtı (kaydedilmiş gerçek yanıt), sınıf eşlemesi ve değişiklik tespiti.
İnternete çıkılmaz."""

import json
from datetime import datetime

import pytest
from conftest import FIX

from radar import prices as ledger
from radar.avrasya import AvrasyaHatasi, ucretleri_coz
from radar.collectors import Context, collect_avrasya_ucret
from radar.config import Source
from radar.fetch import Fetcher
from radar.matching import Matcher
from radar.timeutil import TZ

API = "https://www.avrasyatuneli.com/api/toll/priceHtml"
KAYIT = (FIX / "avrasya-priceHtml-2026.json").read_text(encoding="utf-8")


def test_gercek_yanit_okunur_ve_siniflar_eslenir():
    c = ucretleri_coz(KAYIT)
    # Otomobil 1., minibüs 2., motosiklet 6. sınıf; 3–5. sınıf araçlar tünelden geçemez
    assert set(c["gunduz"]) == {"1", "2", "6"}
    assert c["gunduz"]["1"] == "330.00" and c["gunduz"]["2"] == "495.00" and c["gunduz"]["6"] == "257.40"
    assert c["gece"]["1"] == "165.00"
    assert c["saat"]["gunduz"] == "05:00-23:59"


def test_taninmayan_tablo_sessizce_yanlis_okunmaz():
    bozuk = json.dumps({"EuropeToAsia": "<table><tr><th>Kamyon</th></tr><tr><td>Gündüz</td><td>1</td></tr></table>",
                        "AsiaToEurope": "", "IsTabForm": False})
    with pytest.raises(AvrasyaHatasi):
        ucretleri_coz(bozuk)


def _ctx(cfg, web, now, data):
    fetcher = Fetcher(cfg.settings.user_agent, min_delay=0, respect_robots=False, transport=web.transport)
    return Context(cfg=cfg, matcher=Matcher(cfg.crossings, cfg.generic_phrases), fetcher=fetcher, now=now, crossings_data=data)


def test_ilk_gorus_baslangic_sonra_degisiklik_adayi(cfg, web):
    src = Source(id="avrasya-ucretler", name="Avrasya", type="avrasya_ucret", tier="resmi", url=API, crossings=["avrasya-tuneli"])
    data, st = {}, {}
    web.json(API, json.loads(KAYIT))
    r1 = collect_avrasya_ucret(src, st, _ctx(cfg, web, datetime(2026, 11, 9, 10, tzinfo=TZ), data))
    assert r1.candidates == []
    assert ledger.latest_entry(data, "avrasya-tuneli")["classes"]["1"] == "330.00"

    # Aynı tablo: değişiklik yok
    r2 = collect_avrasya_ucret(src, st, _ctx(cfg, web, datetime(2026, 11, 9, 11, tzinfo=TZ), data))
    assert r2.candidates == []

    # Ücret değişti: resmi değişiklik adayı, yeni sınıf ücretleriyle
    yeni = json.loads(KAYIT)
    for k in ("EuropeToAsia", "AsiaToEurope"):
        if yeni.get(k):
            yeni[k] = yeni[k].replace("330,00", "396,00").replace("330.00", "396.00")
    web.json(API, yeni)
    r3 = collect_avrasya_ucret(src, st, _ctx(cfg, web, datetime(2027, 1, 1, 0, 30, tzinfo=TZ), data))
    assert len(r3.candidates) == 1
    cand = r3.candidates[0]
    assert cand.crossings == ["avrasya-tuneli"] and cand.prices["avrasya-tuneli"]["1"] == "396.00"
