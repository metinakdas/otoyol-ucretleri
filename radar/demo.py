"""Panel önizlemesi için örnek veri. Değerler gerçek değildir; panelde "ÖRNEK VERİ" olarak gösterilir."""

from __future__ import annotations

from datetime import datetime, time, timedelta

from . import bolgeler
from . import calendar as cal
from .config import Config
from .panel import crossing_place
from .timeutil import TZ, to_iso

# Açıkça yuvarlak, gerçek olmayan değerler
_SAMPLE = {
    "15-temmuz-sehitler": ["100.00", "125.00", "250.00", "500.00", "650.00", "40.00"],
    "fatih-sultan-mehmet": ["100.00", "125.00", "250.00", "500.00", "650.00", "40.00"],
    "yavuz-sultan-selim": ["150.00", "200.00", "380.00", "950.00", "1200.00", "60.00"],
    "avrasya-tuneli": None,
    "osmangazi": ["700.00", "1100.00", "1300.00", "1750.00", "2200.00", "500.00"],
    "1915-canakkale": ["900.00", "1150.00", "1350.00", "3000.00", "4000.00", "250.00"],
}


def _classes(values):
    return {str(i + 1): v for i, v in enumerate(values)}


def sample_panel(cfg: Config, now: datetime) -> dict:
    jan1 = datetime(now.year + 1, 1, 1, tzinfo=TZ)
    this_year = datetime(now.year, 1, 1, tzinfo=TZ)
    last_year = datetime(now.year - 1, 1, 1, tzinfo=TZ)
    crossings = []
    for c in cfg.crossings:
        if not c.panel:
            continue
        values = _SAMPLE.get(c.id)
        current = upcoming = None
        history = []
        if values:
            old = [f"{float(v) * 0.8:.2f}" for v in values]
            current = {"valid_from": to_iso(this_year), "valid_to": None, "classes": _classes(values),
                       "source_url": "https://www.kgm.gov.tr/", "note": "örnek"}
            history = [
                {"valid_from": to_iso(last_year), "valid_to": to_iso(this_year - timedelta(seconds=1)), "class1": old[0]},
                {"valid_from": to_iso(this_year), "valid_to": None, "class1": values[0]},
            ]
            if c.operator == "KGM":
                new = [f"{float(v) * 1.25:.2f}" for v in values]
                upcoming = {"valid_from": to_iso(jan1), "valid_to": None, "classes": _classes(new)}
                history.append({"valid_from": to_iso(jan1), "valid_to": None, "class1": new[0]})
        crossings.append({
            "id": c.id, "name": c.name, "operator": c.operator,
            "current": current, "upcoming": upcoming, "history": history, "free_now": None,
            **crossing_place(c),
        })

    kgm_ids = [c.id for c in cfg.crossings if c.panel and c.operator == "KGM"]
    upcoming_event = {
        "id": "ornek-karar", "kind": "ucret_degisikligi", "kind_label": "Geçiş ücreti değişikliği",
        "status": "karar_cikti", "status_label": "Karar çıktı",
        "title": "KGM tarifesi değişti: 15 Temmuz Şehitler ve Fatih Sultan Mehmet Köprüleri (örnek)",
        "crossings": [{"id": i, "name": cfg.crossing_name(i)} for i in kgm_ids],
        "excluded": [], "effective_from": to_iso(jan1), "effective_to": None, "prices": {},
        "flags": [], "updated_at": to_iso(now - timedelta(hours=3)), "created_at": to_iso(now - timedelta(hours=3)),
        "sources": [{"url": "https://www.kgm.gov.tr/Sayfalar/KGM/SiteTr/Otoyollar/UcretlerYeni.aspx",
                     "publisher": "kgm.gov.tr", "tier": "resmi", "quote": "Örnek kayıt"}],
    }
    signal = dict(upcoming_event, id="ornek-sinyal", status="sinyal", status_label="Sinyal",
                  kind="ucretsiz_gecis", kind_label="Ücretsiz geçiş",
                  title="Köprü ve otoyollarda bayram uygulamasıyla ilgili haber (örnek)",
                  effective_from=None, updated_at=to_iso(now - timedelta(days=2)),
                  flags=[{"id": "kapsam_kontrol", "label": "Kapsamı kontrol et"}],
                  sources=[{"url": "https://www.uab.gov.tr/haberler/", "publisher": "uab.gov.tr", "tier": "resmi", "quote": ""}])
    closed = dict(signal, id="ornek-kapandi", status="kapandi", status_label="Kapandı",
                  kind="ucret_degisikligi", kind_label="Geçiş ücreti değişikliği",
                  title="Teyit edilmeyen zam haberi (örnek)", flags=[], updated_at=to_iso(now - timedelta(days=9)))

    sources = []
    for s in cfg.sources:
        sources.append({
            "id": s.id, "name": s.name, "tier": s.tier, "type": s.type, "url": s.url, "enabled": s.enabled,
            "ok": True if s.enabled else None, "last_success": to_iso(now - timedelta(minutes=12)) if s.enabled else None,
            "failing_since": None, "error": None, "info": None,
        })
    periods = [{
        "id": p.id, "name": p.name, "kind": p.kind, "start": p.start.isoformat(), "end": p.end.isoformat(),
        "watch_start": to_iso(cal.watch_start(p)),
    } for p in cal.upcoming(cfg, now)]
    documents = [
        {"key": "ornek-1", "title": "15 Temmuz Şehitler ve Fatih Sultan Mehmet Köprüleri Geçiş Ücretleri Tarifesi",
         "url": "https://www.kgm.gov.tr/Sayfalar/KGM/SiteTr/Otoyollar/UcretlerYeni.aspx",
         "changed_at": to_iso(now - timedelta(hours=3)), "checked_at": to_iso(now), "effective_from": to_iso(jan1),
         "crossings": [cfg.crossing_name(i) for i in kgm_ids], "removed": False, "error": None},
        {"key": "ornek-2", "title": "Osmangazi Köprüsü Geçiş Ücretleri Tarifesi",
         "url": "https://www.kgm.gov.tr/Sayfalar/KGM/SiteTr/Otoyollar/UcretlerYeni.aspx",
         "changed_at": to_iso(this_year), "checked_at": to_iso(now), "effective_from": to_iso(this_year),
         "crossings": [cfg.crossing_name("osmangazi")], "removed": False, "error": None},
    ]
    return {
        "schema": 1,
        "ornek": True,
        "last_run": to_iso(now - timedelta(minutes=12)),
        "run_interval_minutes": cfg.settings.run_interval_minutes,
        "panel_url": "",
        "names": {c.id: c.name for c in cfg.crossings},
        "crossings": crossings,
        "upcoming": [upcoming_event],
        "active_rules": [],
        "next_rules": [],
        "events": [upcoming_event, signal, closed],
        "documents": documents,
        "sources": sources,
        "calendar": periods,
        "bolgeler": bolgeler.panel_listesi(),
        "harita": {"hata": None, "son_basari": to_iso(now - timedelta(days=3))},
    }


# Örnek gişeler: yerleri kabaca gerçek otoyol güzergâhlarında, adları "(örnek)" etiketli.
_SAMPLE_GATES = [
    ("Edirne gişeleri (örnek)", 41.66, 26.62, 22, "O-3", "Avrupa Otoyolu", "gise"),
    ("Çatalca gişeleri (örnek)", 41.13, 28.45, 34, "O-3", "Avrupa Otoyolu", "gise"),
    ("Kuzey Marmara serbest geçiş (örnek)", 41.22, 28.95, 34, "O-7", "Kuzey Marmara Otoyolu", "serbest"),
    ("Gebze gişeleri (örnek)", 40.80, 29.43, 41, "O-4", "Anadolu Otoyolu", "gise"),
    ("İzmit gişeleri (örnek)", 40.77, 29.95, 41, "O-4", "Anadolu Otoyolu", "gise"),
    ("Bursa gişeleri (örnek)", 40.25, 29.05, 16, "O-5", "İstanbul-İzmir Otoyolu", "gise"),
    ("Düzce gişeleri (örnek)", 40.83, 31.15, 81, "O-4", "Anadolu Otoyolu", "gise"),
    ("Bolu gişeleri (örnek)", 40.72, 31.60, 14, "O-4", "Anadolu Otoyolu", "gise"),
    ("Ankara gişeleri (örnek)", 39.98, 32.70, 6, "O-4", "Anadolu Otoyolu", "gise"),
    (None, 39.90, 32.40, 6, "O-4", "Anadolu Otoyolu", "gise"),
    ("Niğde gişeleri (örnek)", 37.97, 34.68, 51, "O-21", "Ankara-Niğde Otoyolu", "gise"),
    ("İzmir gişeleri (örnek)", 38.45, 27.25, 35, "O-5", "İstanbul-İzmir Otoyolu", "gise"),
    ("Aydın gişeleri (örnek)", 37.86, 27.80, 9, "O-31", "İzmir-Aydın Otoyolu", "gise"),
    ("Mersin gişeleri (örnek)", 36.85, 34.55, 33, "O-51", "Mersin-Adana Otoyolu", "gise"),
    ("Adana gişeleri (örnek)", 37.02, 35.25, 1, "O-52", "Adana-Şanlıurfa Otoyolu", "gise"),
    ("Gaziantep gişeleri (örnek)", 37.10, 37.30, 27, "O-52", "Adana-Şanlıurfa Otoyolu", "gise"),
    ("Şanlıurfa gişeleri (örnek)", 37.20, 38.70, 63, "O-52", "Adana-Şanlıurfa Otoyolu", "gise"),
]


def sample_map(now: datetime) -> dict:
    points = []
    for i, (ad, lat, lon, plaka, ref, yol_adi, tur) in enumerate(_SAMPLE_GATES, start=1):
        points.append({
            "id": f"ornek-{i}", "ad": ad or f"Gişe ({ref})", "adsiz": ad is None, "tur": tur,
            "lat": lat, "lon": lon, "plaka": plaka, "il": bolgeler.il_adi(plaka), "bolge": bolgeler.bolge(plaka),
            "yol": ref, "yol_adi": yol_adi, "isletmeci": None, "osm": None, "nokta_sayisi": 2,
        })
    return {
        "schema": 1, "ornek": True, "olusturma": to_iso(now - timedelta(days=3)),
        "kaynak": "Örnek veri", "lisans": "Örnek veri; gerçek gişe konumları OpenStreetMap'ten alınır",
        "ozet": {"toplam": len(points)}, "noktalar": points,
    }
