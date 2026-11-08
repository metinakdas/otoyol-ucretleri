"""Türkiye'nin 81 ili ve 7 coğrafi bölgesi.

İller plaka koduyla tutulur (OpenStreetMap'teki "ISO3166-2=TR-34" etiketi de plaka kodudur).
Bölge sınırları ve etiket konumları yaklaşıktır; yalnızca haritada yakınlaştırma ve bölge adını
göstermek için kullanılır.
"""

from __future__ import annotations

import re

from .textutil import fold

# (kimlik, ad, yaklaşık sınır [[güney, batı], [kuzey, doğu]], etiket konumu [enlem, boylam])
BOLGELER: list[tuple[str, str, list[list[float]], list[float]]] = [
    ("marmara", "Marmara", [[39.0, 25.6], [42.1, 31.0]], [40.45, 27.9]),
    ("ege", "Ege", [[36.6, 26.2], [39.8, 31.6]], [38.4, 28.6]),
    ("akdeniz", "Akdeniz", [[35.8, 29.2], [38.5, 37.6]], [36.95, 33.2]),
    ("ic-anadolu", "İç Anadolu", [[36.5, 29.9], [41.0, 38.9]], [38.9, 33.6]),
    ("karadeniz", "Karadeniz", [[39.6, 30.6], [42.1, 42.6]], [40.9, 35.8]),
    ("dogu-anadolu", "Doğu Anadolu", [[37.0, 37.4], [41.6, 44.8]], [39.3, 41.4]),
    ("guneydogu-anadolu", "Güneydoğu Anadolu", [[36.6, 36.5], [38.6, 43.0]], [37.45, 39.6]),
]
BOLGE_ADLARI = {b[0]: b[1] for b in BOLGELER}

# plaka → (il adı, bölge)
ILLER: dict[int, tuple[str, str]] = {
    1: ("Adana", "akdeniz"), 2: ("Adıyaman", "guneydogu-anadolu"), 3: ("Afyonkarahisar", "ege"),
    4: ("Ağrı", "dogu-anadolu"), 5: ("Amasya", "karadeniz"), 6: ("Ankara", "ic-anadolu"),
    7: ("Antalya", "akdeniz"), 8: ("Artvin", "karadeniz"), 9: ("Aydın", "ege"),
    10: ("Balıkesir", "marmara"), 11: ("Bilecik", "marmara"), 12: ("Bingöl", "dogu-anadolu"),
    13: ("Bitlis", "dogu-anadolu"), 14: ("Bolu", "karadeniz"), 15: ("Burdur", "akdeniz"),
    16: ("Bursa", "marmara"), 17: ("Çanakkale", "marmara"), 18: ("Çankırı", "ic-anadolu"),
    19: ("Çorum", "karadeniz"), 20: ("Denizli", "ege"), 21: ("Diyarbakır", "guneydogu-anadolu"),
    22: ("Edirne", "marmara"), 23: ("Elazığ", "dogu-anadolu"), 24: ("Erzincan", "dogu-anadolu"),
    25: ("Erzurum", "dogu-anadolu"), 26: ("Eskişehir", "ic-anadolu"), 27: ("Gaziantep", "guneydogu-anadolu"),
    28: ("Giresun", "karadeniz"), 29: ("Gümüşhane", "karadeniz"), 30: ("Hakkari", "dogu-anadolu"),
    31: ("Hatay", "akdeniz"), 32: ("Isparta", "akdeniz"), 33: ("Mersin", "akdeniz"),
    34: ("İstanbul", "marmara"), 35: ("İzmir", "ege"), 36: ("Kars", "dogu-anadolu"),
    37: ("Kastamonu", "karadeniz"), 38: ("Kayseri", "ic-anadolu"), 39: ("Kırklareli", "marmara"),
    40: ("Kırşehir", "ic-anadolu"), 41: ("Kocaeli", "marmara"), 42: ("Konya", "ic-anadolu"),
    43: ("Kütahya", "ege"), 44: ("Malatya", "dogu-anadolu"), 45: ("Manisa", "ege"),
    46: ("Kahramanmaraş", "akdeniz"), 47: ("Mardin", "guneydogu-anadolu"), 48: ("Muğla", "ege"),
    49: ("Muş", "dogu-anadolu"), 50: ("Nevşehir", "ic-anadolu"), 51: ("Niğde", "ic-anadolu"),
    52: ("Ordu", "karadeniz"), 53: ("Rize", "karadeniz"), 54: ("Sakarya", "marmara"),
    55: ("Samsun", "karadeniz"), 56: ("Siirt", "guneydogu-anadolu"), 57: ("Sinop", "karadeniz"),
    58: ("Sivas", "ic-anadolu"), 59: ("Tekirdağ", "marmara"), 60: ("Tokat", "karadeniz"),
    61: ("Trabzon", "karadeniz"), 62: ("Tunceli", "dogu-anadolu"), 63: ("Şanlıurfa", "guneydogu-anadolu"),
    64: ("Uşak", "ege"), 65: ("Van", "dogu-anadolu"), 66: ("Yozgat", "ic-anadolu"),
    67: ("Zonguldak", "karadeniz"), 68: ("Aksaray", "ic-anadolu"), 69: ("Bayburt", "karadeniz"),
    70: ("Karaman", "ic-anadolu"), 71: ("Kırıkkale", "ic-anadolu"), 72: ("Batman", "guneydogu-anadolu"),
    73: ("Şırnak", "guneydogu-anadolu"), 74: ("Bartın", "karadeniz"), 75: ("Ardahan", "dogu-anadolu"),
    76: ("Iğdır", "dogu-anadolu"), 77: ("Yalova", "marmara"), 78: ("Karabük", "karadeniz"),
    79: ("Kilis", "guneydogu-anadolu"), 80: ("Osmaniye", "akdeniz"), 81: ("Düzce", "karadeniz"),
}

_BY_NAME = {fold(ad): plaka for plaka, (ad, _) in ILLER.items()}
_ISO = re.compile(r"^TR-(\d{2})$")

# Türkiye'nin kabaca sınırları: konum doğrulaması için
TURKIYE = [[35.7, 25.5], [42.3, 45.0]]


def plaka_bul(value) -> int | None:
    """Plaka kodu, il adı ya da "TR-34" biçiminden plakayı bulur."""
    if value is None:
        return None
    if isinstance(value, int):
        return value if value in ILLER else None
    text = str(value).strip()
    m = _ISO.match(text)
    if m:
        n = int(m.group(1))
        return n if n in ILLER else None
    if text.isdigit():
        n = int(text)
        return n if n in ILLER else None
    return _BY_NAME.get(fold(text))


def il_adi(plaka: int | None) -> str | None:
    return ILLER[plaka][0] if plaka in ILLER else None


def bolge(plaka: int | None) -> str | None:
    return ILLER[plaka][1] if plaka in ILLER else None


def turkiye_icinde(lat: float, lon: float) -> bool:
    (s, w), (n, e) = TURKIYE
    return s <= lat <= n and w <= lon <= e


def panel_listesi() -> list[dict]:
    """Panelin bölge filtreleri ve yakınlaştırma için kullandığı liste."""
    return [{"id": i, "ad": ad, "sinir": sinir, "etiket": etiket} for i, ad, sinir, etiket in BOLGELER]
