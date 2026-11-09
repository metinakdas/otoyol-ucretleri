"""Avrasya Tüneli geçiş ücretleri: işletmecinin sitesindeki ücret tablosu.

https://www.avrasyatuneli.com/ucretlendirme/ sayfası ücretleri sayfaya gömmez; sayfanın kendi betiği
(magiclick.min.js) tabloyu "/api/toll/priceHtml" adresinden JSON olarak alır ve sayfaya yerleştirir:

    GET https://www.avrasyatuneli.com/api/toll/priceHtml      (başlık: "X-Bone-Language: TR")
    → {"EuropeToAsia": "<table>…</table>", "AsiaToEurope": …, "IsTabForm": false}

Tablo: sütunlar araç türü (Otomobil, Minibüs, Motosiklet), satırlar zaman dilimi (Gündüz 05:00-23:59,
Gece 00:00-04:59). "IsTabForm" true olursa iki yönün tablosu ayrıdır.

Sınıf eşlemesi sitenin kendi açıklamasından: "Aks aralığı 3.20 metreden küçük iki akslı araçlar otomobil
(1. Sınıf), aks aralığı 3.20 metre ve üstünde olan ve UKOME kararınca tünelden geçişi uygun iki akslı araçlar
minibüs (2. Sınıf), motosikletler ise 6. Sınıf araç tarifesinden ücretlendiriliyor." 3, 4 ve 5. sınıf
araçlar tünelden geçemez; bu sınıfların ücreti yazılmaz. Tanınmayan bir sütun ya da satır gelirse tablo
okunmaz (sessizce yanlış eşlemek yerine kaynak hatası verilir).
"""

from __future__ import annotations

import html
import json
import re
from decimal import Decimal

from .textutil import clean_spaces, fold

DIL_BASLIGI = {"X-Bone-Language": "TR", "Accept": "application/json"}

# Sütun adı (katlanmış) → KGM sınıfı
SINIF_ESLEME = {
    "otomobil": "1",
    "car": "1",
    "minibus": "2",
    "motosiklet": "6",
    "motorcycle": "6",
}
SINIF_ADLARI = {"1": "Otomobil", "2": "Minibüs", "6": "Motosiklet"}
ZAMAN = {"gunduz": "gunduz", "day": "gunduz", "gece": "gece", "night": "gece"}

_TR = re.compile(r"<tr[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
_TD = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.IGNORECASE | re.DOTALL)
_TUTAR = re.compile(r"(\d{1,3}(?:\.\d{3})+|\d+),(\d{2})\s*(?:TL|₺)", re.IGNORECASE)
_SAAT = re.compile(r"(\d{1,2}:\d{2})\s*[-–]\s*(\d{1,2}:\d{2})")


class AvrasyaHatasi(Exception):
    pass


def _metin(cell: str) -> str:
    cell = re.sub(r"<br\s*/?>", " ", cell, flags=re.IGNORECASE)
    return clean_spaces(html.unescape(re.sub(r"<[^>]+>", " ", cell)).replace("\xa0", " "))


def _tutar(text: str) -> str:
    m = _TUTAR.search(text)
    if not m:
        raise AvrasyaHatasi(f"tutar okunamadı: {text[:40]!r}")
    return str(Decimal(m.group(1).replace(".", "") + "." + m.group(2)))


def tablo_coz(table_html: str) -> dict:
    """Ücret tablosu HTML'i → {"gunduz": {sınıf: tutar}, "gece": {...}, "saat": {"gunduz": "05:00-23:59", ...}}."""
    rows = [[_metin(c) for c in _TD.findall(r)] for r in _TR.findall(table_html or "")]
    rows = [r for r in rows if any(r)]
    if len(rows) < 2:
        raise AvrasyaHatasi("ücret tablosu boş")
    header = rows[0]
    siniflar = []
    for name in header[1:]:
        key = re.sub(r"[^a-z]", "", fold(name))
        if key not in SINIF_ESLEME:
            raise AvrasyaHatasi(f"tanınmayan araç türü sütunu: {name!r}")
        siniflar.append(SINIF_ESLEME[key])
    if len(set(siniflar)) != len(siniflar) or "1" not in siniflar:
        raise AvrasyaHatasi(f"araç türü sütunları beklenmedik: {header[1:]}")
    out: dict = {"saat": {}}
    for row in rows[1:]:
        label = row[0]
        zaman = next((v for k, v in ZAMAN.items() if fold(label).startswith(k)), None)
        if zaman is None:
            raise AvrasyaHatasi(f"tanınmayan zaman dilimi: {label!r}")
        if zaman in out:
            raise AvrasyaHatasi(f"zaman dilimi iki kez yazılmış: {label!r}")
        if len(row) != len(header):
            raise AvrasyaHatasi(f"{label}: {len(row) - 1} tutar var, {len(siniflar)} bekleniyordu")
        out[zaman] = {s: _tutar(v) for s, v in zip(siniflar, row[1:])}
        m = _SAAT.search(label)
        out["saat"][zaman] = f"{m.group(1)}-{m.group(2)}" if m else None
    if "gunduz" not in out:
        raise AvrasyaHatasi("gündüz ücretleri bulunamadı")
    return out


def ucretleri_coz(text: str) -> dict:
    """/api/toll/priceHtml yanıtı → tablo_coz sonucu (+ "yon_farkli": iki yönün ücreti farklı mı).

    İki yönün tablosu varsa ve farklıysa Avrupa→Asya tablosu alınır, "yon_farkli" true olur.
    """
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        raise AvrasyaHatasi("yanıt JSON değil") from None
    if not isinstance(data, dict) or not data.get("EuropeToAsia"):
        raise AvrasyaHatasi("yanıtta ücret tablosu (EuropeToAsia) yok")
    out = tablo_coz(data["EuropeToAsia"])
    out["yon_farkli"] = False
    if data.get("IsTabForm") and data.get("AsiaToEurope"):
        geri = tablo_coz(data["AsiaToEurope"])
        out["yon_farkli"] = {k: geri.get(k) for k in ("gunduz", "gece")} != {k: out.get(k) for k in ("gunduz", "gece")}
    return out


def defter_eki(c: dict) -> dict:
    """Ücret defteri kaydına eklenecek alanlar: gece tarifesi, gündüz saatleri, sınıf adları."""
    ek: dict = {"gunduz_saat": c["saat"].get("gunduz"),
                "sinif_adlari": {s: SINIF_ADLARI[s] for s in sorted(c["gunduz"], key=int)}}
    if c.get("gece"):
        ek["gece"] = {"saat": c["saat"].get("gece"), "classes": dict(c["gece"])}
    return ek
