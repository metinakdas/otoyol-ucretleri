"""Otoyol gişeden gişeye ücret tabloları: KGM tarife PDF'lerindeki ücret matrisleri.

KGM'nin "UcretlerYeni.aspx" sayfasındaki otoyol PDF'lerinde her giriş-çıkış gişesi çifti için 1–6. sınıf
ücretleri vardır. Bu modül o tabloları okuyup data/ucret-tablosu.json dosyasına yazar; panel "Adapazarı'ndan
girdim, Akyazı'dan çıktım, 1. sınıf ne kadar?" sorusunu bu dosyadan yanıtlar.

İki tablo biçimi var:

- Üçgen tablo (KGM'nin kendi işlettiği otoyollar): her istasyon için bir "km" satırı ve altında 6 sınıf
  satırı; sütunlar önceki istasyonlardır. İstasyonun kendi sütunundaki (köşegen) değer, giriş bilgisi
  bulunamazsa alınan en uzak mesafe ücretidir ("azami"). Hangi istasyonun hangi sütun olduğu bu köşegenden
  bulunur: bazı istasyonların kendi sütunu yoktur (ör. Gebze OSB), bazı sütunların da satırı yoktur.
- Kare tablo (yap-işlet-devret otoyolları): satırlar giriş, sütunlar çıkış gişeleridir. Köşegen yine
  "giriş bilgisi yoksa / U dönüşünde en uzak mesafe ücreti"dir. Bazı tablolarda ücret yöne göre değişir.

Yenileme günde bir (ya da radar tarife belgesinin değiştiğini görünce) yapılır. Bir PDF okunamazsa o
otoyolun önceki verisi korunur ve hata state.json'a yazılır; iyi veri hiçbir zaman silinmez.

Gişe konumları, illeri ve bölgeleri yalnızca bizim tuttuğumuz config/giseler.yaml kaydından gelir
(otoyol kimliği + istasyon adıyla eşlenir). Radar çalışırken dışarıdan konum alınmaz. Kayıtta olmayan
istasyon tabloda kalır ama konumsuzdur; state.json'a yazılır ve teknik gruba bir kez bildirilir. Serbest
geçiş (SGS) satırlarının konumları ve tablolar arası bağlantılar da aynı kayıttan gelir:

- "serbest_gecis": tablonun sabit ücretli serbest geçiş satırlarına lat/lon/il/bolge yazılır; serbest geçiş
  noktası olan istasyona "serbest": true eklenir. Kayıtta olmayan satır da teknik gruba bir kez bildirilir.
- "baglantilar": farklı tabloların otoyoldan çıkmadan birbirine geçilen gişe çiftleri, dosyanın en üstünde
  {"a": {otoyol, i, ad}, "b": {...}, "ara_serbest": {"ab": [...], "ba": [...]}, ...} olarak yayımlanır.
  KGM belgelerinde aktarma indirimi yoktur: her tablo kendi ücretini ayrı alır ("ucretlendirme": "ayri").
"""

from __future__ import annotations

import copy
import hashlib
import io
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from difflib import SequenceMatcher

import httpx

from .config import Config
from .guvenlik import redact
from .store import Store
from .textutil import clean_spaces, fold, slugify, tr_lower
from .timeutil import hours_since, to_iso

log = logging.getLogger(__name__)

SCHEMA = 1
STATE_KEY = "_ucret_tablosu"
DOSYA = "ucret-tablosu.json"
KAYNAK = "KGM geçiş ücreti tarifeleri"

YENILEME_SAAT = 24          # belgeler en fazla bu sıklıkla yeniden indirilir
TEKRAR_DENEME_SAAT = 6      # sayfa okunamazsa en erken bu kadar sonra yeniden denenir

# Araç sınıfları: KGM'nin 15 Temmuz/FSM tarifesinde (1 numaralı PDF) yazan tanımlar.
SINIFLAR = {
    "1": "Aks aralığı 3,20 m'den küçük iki akslı araçlar (otomobil)",
    "2": "Aks aralığı 3,20 m ve daha büyük iki akslı araçlar",
    "3": "Üç akslı araçlar",
    "4": "Dört ve beş akslı araçlar",
    "5": "Altı ve daha fazla akslı araçlar",
    "6": "Motosikletler",
}

# Bilinen belgeler: düzgün ad ve yol numarası. Eşleşme, bağlantı metni + adresinin katlanmış hâlinde
# anahtar kelimelerin hepsi geçerse yapılır (sıra önemli: ilk eşleşen alınır).
_BILINEN: list[tuple[tuple[str, ...], str, str, str | None]] = [
    (("cesmeli",), "cesmeli-kizkalesi", "Çeşmeli – Kızkalesi Otoyolu", "O-51"),
    (("anadolu", "camlica"), "anadolu-camlica-akinci", "Anadolu Otoyolu (Çamlıca – Akıncı)", "O-4"),
    (("izmir", "cesme"), "izmir-cesme", "İzmir – Çeşme Otoyolu", "O-32"),
    (("izmir", "aydin"), "izmir-aydin", "İzmir – Aydın Otoyolu (Işıkkent – Aydın Batı)", "O-31"),
    (("adana", "gaziantep"), "cukurova-adana-gaziantep", "Çukurova Otoyolu (Adana Doğu – Gaziantep Batı)", "O-52"),
    (("gaziantep", "sanliurfa"), "cukurova-gaziantep-sanliurfa", "Çukurova Otoyolu (Gaziantep Doğu – Şanlıurfa)", "O-52"),
    (("nigde", "mersin"), "cukurova-nigde-mersin-adana", "Çukurova Otoyolu (Niğde – Mersin – Adana Batı)", "O-21"),
    (("mahmutbey", "edirne"), "avrupa-mahmutbey-edirne", "Avrupa Otoyolu (Mahmutbey – Edirne)", "O-3"),
    (("gebze", "izmir"), "gebze-orhangazi-izmir", "Gebze – Orhangazi – İzmir Otoyolu", "O-5"),
    (("kuzey", "cevre"), "yss-kuzey-cevre", "Yavuz Sultan Selim Köprüsü ve Kuzey Çevre Otoyolu", "O-7"),
    (("kinali", "odayeri"), "kmo-kinali-odayeri", "Kuzey Marmara Otoyolu (Kınalı – Odayeri)", "O-7"),
    (("kurtkoy", "akyazi"), "kmo-kurtkoy-akyazi", "Kuzey Marmara Otoyolu (Kurtköy – Akyazı)", "O-7"),
    (("menemen", "candarli"), "menemen-aliaga-candarli", "Menemen – Aliağa – Çandarlı Otoyolu", "O-33"),
    (("ankara", "nigde"), "ankara-nigde", "Ankara – Niğde Otoyolu", "O-21"),
    (("malkara", "canakkale"), "malkara-canakkale", "Malkara – Çanakkale Otoyolu (1915 Çanakkale Köprüsü dahil)", "O-6"),
    (("aydin", "denizli"), "aydin-denizli", "Aydın – Denizli Otoyolu", "O-31"),
]


class UcretTablosuHatasi(Exception):
    pass


# ============================================================================ hücre okuma

_ZW = re.compile("[\u200b-\u200f\u2060\ufeff\u00ad]")
_UCRET = re.compile(r"^(\d{1,3}(?:\.\d{3})+|\d+),(\d{2})$")
_KM = re.compile(r"^(\d+),(\d{1,3})\s*km$", re.IGNORECASE)
_SINIF = re.compile(r"^[1-6]$")


def _hucre(cell) -> str:
    return clean_spaces(_ZW.sub("", cell or ""))


def _sayi(value: float) -> int | float:
    return int(value) if float(value).is_integer() else round(float(value), 2)


def ucret_oku(cell) -> int | float | None:
    """'1 .480,00', '₺ 9 25,00', '4 8 0 , 0 0', '40,00 TL' → sayı (TL). Boş hücre None.

    Sayı olmayan dolu hücre hata verir: yanlış hizalanmış bir tabloyu sessizce kabul etmemek için.
    """
    text = _hucre(cell)
    if not text:
        return None
    t = re.sub(r"\s+", "", text.replace("₺", "").replace("TL", "").replace("tl", ""))
    if t.isdigit():                      # "0" gibi kuruşsuz yazılmış tutar
        return int(t)
    m = _UCRET.match(t)
    if not m:
        raise UcretTablosuHatasi(f"ücret okunamadı: {text[:30]!r}")
    return _sayi(float(m.group(1).replace(".", "") + "." + m.group(2)))


def km_oku(cell) -> float | None:
    text = _hucre(cell)
    if not text:
        return None
    m = _KM.match(text.replace(" ,", ","))
    if not m:
        raise UcretTablosuHatasi(f"mesafe okunamadı: {text[:30]!r}")
    return round(float(f"{m.group(1)}.{m.group(2)}"), 3)


# ============================================================================ adlar

# Büyük harfle bırakılan kısaltmalar
_KISALTMA = {"osb", "sgs", "kmo", "tem", "gkm", "hgs", "ogs", "ab", "d100", "d-100"}
_TR_UPPER = {"i": "İ", "ı": "I"}


def _ilk_buyuk(word: str) -> str:
    if not word:
        return word
    low = tr_lower(word)
    if fold(low) in _KISALTMA:
        return fold(low).upper()
    if re.fullmatch(r"[a-zçğıöşü]", low):   # "Serbest B." gibi tek harfli kısaltma
        return _TR_UPPER.get(low, low.upper())
    if re.fullmatch(r"g-?\d+", low):          # gişe kodu: G-1, G11
        return low.upper()
    first = _TR_UPPER.get(low[0], low[0].upper())
    return first + low[1:]


def baslik_harfi(text: str) -> str:
    """KGM'nin BÜYÜK HARF adlarını Türkçe kurallarla başlık biçimine çevirir.

    "ADAPAZARI" → "Adapazarı", "Ş.PINAR" → "Ş.Pınar", "DÜZCE (GÖLYAKA)" → "Düzce (Gölyaka)",
    "İSKENDERUN OSB" → "İskenderun OSB". Zaten küçük harf içeren adlara dokunulmaz.
    """
    text = clean_spaces(text)
    letters = [c for c in text if c.isalpha()]
    if letters and any(c.islower() for c in letters):
        return text
    parts = re.split(r"([\s\-./()]+)", text)
    return "".join(p if re.fullmatch(r"[\s\-./()]*", p) else _ilk_buyuk(p) for p in parts)


def _harfler(text: str | None) -> str:
    """Karşılaştırma anahtarı: yalnızca harf ve rakam (Türkçe katlanmış)."""
    return re.sub(r"[^a-z0-9]", "", fold(text))


def _ad_benzer(a: str, b: str) -> float:
    ka, kb = _harfler(re.sub(r"\(G-?\d+\)", "", a, flags=re.I)), _harfler(re.sub(r"\(G-?\d+\)", "", b, flags=re.I))
    if not ka or not kb:
        return 0.0
    if ka == kb:
        return 1.0
    if ka in kb or kb in ka:
        return 0.9
    return SequenceMatcher(None, ka, kb).ratio()


# ============================================================================ tablo çözümleme

@dataclass
class _Blok:
    ad: str
    satirlar: list[list]                 # 6 sınıf satırı (ham hücreler)
    km_satiri: list | None = None


@dataclass
class _Tablo:
    """Ayrıştırılmış tek bir otoyol tablosu (JSON'a dönüşmeden önce)."""
    tur: str                             # "ucgen" | "kare"
    adlar: list[str]
    ucret: list[list]
    km: list[list]
    azami: list
    ucret_geri: list[list] | None = None
    uyarilar: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "tur": self.tur,
            "istasyonlar": self.adlar,
            "ucret": self.ucret,
            "ucret_geri": self.ucret_geri,
            "yonlu": self.ucret_geri is not None,
            "km": self.km,
            "azami": self.azami,
            "uyarilar": self.uyarilar,
        }


def _sinif_sutunu(table: list[list]) -> int | None:
    best, best_n = None, 0
    width = max((len(r) for r in table), default=0)
    for c in range(min(4, width)):
        n = sum(1 for r in table if c < len(r) and _SINIF.match(_hucre(r[c])))
        if n > best_n:
            best, best_n = c, n
    return best if best_n >= 12 else None


def _bloklar(table: list[list], c: int) -> tuple[int, list[_Blok]]:
    """Sınıf sütunu c olan tablodaki 1–6 satır bloklarını ve başlık satırını bulur."""
    width = max(len(x) for x in table)
    rows = [list(r) + [None] * (width - len(r)) for r in table]
    is_cls = [_SINIF.match(_hucre(r[c])) is not None for r in rows]
    first = is_cls.index(True)
    # Başlık: ilk bloktan önce, c'den sonraki sütunlarda en çok sayı olmayan metin içeren satır
    header, best = None, 0
    for i in range(first):
        cells = [_hucre(x) for x in rows[i][c + 1:]]
        n = sum(1 for x in cells if x and not re.search(r"\d+,\d", x))
        if n > best:
            header, best = i, n
    if header is None or best < 2:
        raise UcretTablosuHatasi("tablo başlığı (istasyon adları) bulunamadı")

    name_col = c - 1
    blocks: list[_Blok] = []
    i = header + 1
    used_label: set[int] = set()
    while i < len(rows):
        if not is_cls[i]:
            i += 1
            continue
        classes = [_hucre(rows[i + k][c]) if i + k < len(rows) else "" for k in range(6)]
        if classes != ["1", "2", "3", "4", "5", "6"]:
            raise UcretTablosuHatasi(f"{i}. satırda 1–6 sınıf sırası bozuk: {classes}")
        label = i - 1 if i - 1 > header and not is_cls[i - 1] and i - 1 not in used_label else None
        parts = []
        if label is not None:
            used_label.add(label)
            parts.append(_hucre(rows[label][name_col]) if name_col >= 0 else "")
        parts += [_hucre(rows[i + k][name_col]) if name_col >= 0 else "" for k in range(6)]
        name = clean_spaces(" ".join(p for p in parts if p))
        km_row = None
        if label is not None and any("km" in _hucre(x) for x in rows[label][c + 1:]):
            km_row = rows[label][c + 1:]
        blocks.append(_Blok(ad=name, satirlar=[r[c + 1:] for r in rows[i:i + 6]], km_satiri=km_row))
        i += 6
    return header, blocks


def _son_dolu(row: list) -> int:
    idx = [k for k, x in enumerate(row) if _hucre(x)]
    return idx[-1] if idx else -1


def _ucgen(header_names: list[str], blocks: list[_Blok]) -> _Tablo:
    """KGM üçgen tablosu: her bloğun kendi sütunu, 1. sınıf satırındaki son dolu hücredir (köşegen)."""
    ncol = len(header_names)
    uyarilar: list[str] = []
    diags = []
    for b in blocks:
        ds = {_son_dolu(r) for r in b.satirlar}
        if len(ds) != 1 or -1 in ds:
            raise UcretTablosuHatasi(f"{b.ad}: sınıf satırlarının uzunluğu farklı, köşegen belirsiz")
        d = ds.pop()
        if d >= ncol:
            raise UcretTablosuHatasi(f"{b.ad}: köşegen sütunu başlıkta yok")
        diags.append(d)
    if any(b < a for a, b in zip(diags, diags[1:])):
        raise UcretTablosuHatasi("istasyon sırası sütun sırasıyla uyuşmuyor")

    # Her sütunun sahibi: o köşegene sahip bloklardan adı başlıkla uyuşan, yoksa sonuncusu
    owner: dict[int, int] = {}
    for d in sorted(set(diags)):
        group = [k for k, x in enumerate(diags) if x == d]
        named = [k for k in group if _ad_benzer(blocks[k].ad, header_names[d]) >= 0.9]
        owner[d] = named[-1] if named else group[-1]
        if len(group) > 1:
            for k in group:
                if k != owner[d]:
                    uyarilar.append(f"{baslik_harfi(blocks[k].ad)}: tabloda kendi sütunu yok; yalnızca önceki "
                                    "istasyonlardan gelen ücretler var (sonraki istasyonlarla ücret yazılmamış)")
        elif header_names[d] and _ad_benzer(blocks[owner[d]].ad, header_names[d]) < 0.75:
            uyarilar.append(f"{baslik_harfi(blocks[owner[d]].ad)}: sütun başlığında "
                            f"'{baslik_harfi(header_names[d])}' yazıyor; satırdaki ad kullanıldı")

    # İstasyon sırası: sütun sırası; sütunsuz bloklar sahiplerinden hemen önce
    order: list[tuple[str, int]] = []    # ("blok", k) | ("sutun", d)
    for d in range(ncol):
        group = [k for k, x in enumerate(diags) if x == d]
        order += [("blok", k) for k in group if k != owner.get(d)]
        if d in owner:
            order.append(("blok", owner[d]))
        elif header_names[d]:
            order.append(("sutun", d))
            uyarilar.append(f"{baslik_harfi(header_names[d])}: tabloda satırı yok; yalnızca sonraki "
                            "istasyonlardan gelen ücretler var")
    col_station = {}
    for idx, (kind, ref) in enumerate(order):
        if kind == "blok" and owner.get(diags[ref]) == ref:
            col_station[diags[ref]] = idx
        elif kind == "sutun":
            col_station[ref] = idx

    n = len(order)
    adlar, ucret, kms, azami = [], [], [], []
    for idx, (kind, ref) in enumerate(order):
        row_u: list = [None] * idx
        row_k: list = [None] * idx
        if kind == "sutun":
            adlar.append(baslik_harfi(header_names[ref]))
            azami.append(None)
        else:
            b = blocks[ref]
            d = diags[ref]
            adlar.append(baslik_harfi(b.ad))
            for col in range(d):
                vals = [ucret_oku(r[col]) for r in b.satirlar]
                kmv = km_oku(b.km_satiri[col]) if b.km_satiri is not None and col < len(b.km_satiri) else None
                if all(v is None for v in vals) and kmv is None:
                    continue
                j = col_station.get(col)
                if j is None or j >= idx:
                    raise UcretTablosuHatasi(f"{b.ad}: {col + 1}. sütunun istasyonu bulunamadı")
                row_u[j] = None if all(v is None for v in vals) else vals
                row_k[j] = kmv
            diag = [ucret_oku(r[d]) for r in b.satirlar]
            azami.append(None if all(v is None for v in diag) else diag)
        ucret.append(row_u)
        kms.append(row_k)
    assert len(adlar) == n
    return _Tablo(tur="ucgen", adlar=adlar, ucret=ucret, km=kms, azami=azami, uyarilar=uyarilar)


def _kare_matris(header_names: list[str], blocks: list[_Blok]) -> tuple[list[str], dict[int, list[list]], list[str]]:
    """Kare tabloda her giriş bloğunu bir çıkış sütununa bağlar (ada göre, olmazsa sıraya göre)."""
    ncol = len(header_names)
    uyarilar: list[str] = []
    mapping: dict[int, int] = {}
    for k, b in enumerate(blocks):
        scores = [(_ad_benzer(b.ad, h), d) for d, h in enumerate(header_names)]
        score, d = max(scores)
        if score >= 0.8 and d not in mapping.values():
            mapping[k] = d
    if len(mapping) != len(blocks):
        if len(blocks) == ncol:
            mapping = {k: k for k in range(ncol)}
            uyarilar.append("satır adları sütun adlarıyla eşleşmedi; satır ve sütunlar sırayla eşlendi")
        else:
            bad = [blocks[k].ad for k in range(len(blocks)) if k not in mapping]
            raise UcretTablosuHatasi(f"giriş satırı çıkış sütunlarıyla eşlenemedi: {', '.join(bad)[:120]}")
    if sorted(mapping.values()) != sorted(set(mapping.values())) or any(
            b < a for a, b in zip(list(mapping.values()), list(mapping.values())[1:])):
        raise UcretTablosuHatasi("giriş satırlarının sırası çıkış sütunlarının sırasıyla uyuşmuyor")

    adlar = []
    rows: dict[int, list[list]] = {}
    by_col = {d: k for k, d in mapping.items()}
    for d in range(ncol):
        k = by_col.get(d)
        header = header_names[d]
        if k is None:
            adlar.append(baslik_harfi(header))
            uyarilar.append(f"{baslik_harfi(header)}: tabloda giriş satırı yok; bu gişeden girişin ücreti yazılmamış")
            continue
        row = blocks[k].ad
        # Satır adı sütun adıyla harf harf aynıysa (tireleme farkı vb.) satırdaki tek satırlık ad alınır
        adlar.append(baslik_harfi(row if (not header or _harfler(row) == _harfler(header)) else header))
        if len(blocks[k].satirlar[0]) < ncol:
            raise UcretTablosuHatasi(f"{row}: satırda eksik sütun var")
        rows[d] = [[ucret_oku(r[col]) for r in blocks[k].satirlar] for col in range(ncol)]
    return adlar, rows, uyarilar


def _kare(header_names: list[str], blocks: list[_Blok]) -> _Tablo:
    adlar, rows, uyarilar = _kare_matris(header_names, blocks)
    return _kare_tablo(adlar, rows, uyarilar)


def _bos(v: list | None) -> list | None:
    return None if v is None or all(x is None for x in v) else v


def _kare_tablo(adlar: list[str], rows: dict[int, list[list]], uyarilar: list[str]) -> _Tablo:
    """M[giriş][çıkış] → ucret (ileri: önceki gişeden girip sonrakinden çıkış) ve gerekirse ucret_geri."""
    n = len(adlar)

    def m(g: int, c: int) -> list | None:
        return _bos(rows[g][c]) if g in rows else None

    # Yönlü: iki yönün ücreti farklıysa ya da yalnızca bir yön yazılmışsa
    yonlu = any(m(i, j) != m(j, i) for i in range(n) for j in range(i))
    ucret, geri, kms, azami = [], [], [], []
    for i in range(n):
        ileri_row, geri_row = [], []
        for j in range(i):
            a, b = m(j, i), m(i, j)          # a: j'den gir, i'den çık · b: i'den gir, j'den çık
            if yonlu:
                ileri_row.append(a)
                geri_row.append(b)
            else:
                ileri_row.append(a if a is not None else b)
        ucret.append(ileri_row)
        geri.append(geri_row)
        kms.append([None] * i)
        azami.append(m(i, i))
    if yonlu:
        uyarilar.append("Ücretler yöne göre değişiyor: 'ucret' önceki istasyondan girip sonrakinden çıkışı, "
                        "'ucret_geri' ters yönü verir")
    return _Tablo(tur="kare", adlar=adlar, ucret=ucret, km=kms, azami=azami,
                  ucret_geri=geri if yonlu else None, uyarilar=uyarilar)


def tablo_coz(table: list[list]) -> _Tablo | None:
    """pdfplumber tablosunu çözer. Ücret matrisi değilse None, matris olup okunamıyorsa hata."""
    if not table or len(table) < 8:
        return None
    c = _sinif_sutunu(table)
    if c is None or c < 1:
        return None
    header, blocks = _bloklar(table, c)
    header_names = [_hucre(x).replace("\n", " ") for x in table[header][c + 1:]]
    while header_names and not header_names[-1]:
        header_names.pop()
    if len(header_names) < 2 or len(blocks) < 2:
        return None
    if any(b.km_satiri is not None for b in blocks):
        return _ucgen(header_names, blocks)
    return _kare(header_names, blocks)


# ---------------------------------------------------------------------------- metin yedeği

_METIN_SATIR = re.compile(r"^(?P<on>.*?)(?:^|\s)(?P<s>[1-6])\s+(?P<tutar>₺.*)$")


def metin_coz(text: str) -> _Tablo | None:
    """Tablo çizgileri bozuk PDF'ler için: "3 ₺ 590,00 ₺ 90,00 …" satırlarından kare matris.

    Satırlar giriş gişeleridir; sütunların satırlarla aynı sırada olduğu varsayılır (kare tablo).
    İstasyon adı, bloğun 1. ve 6. sınıf satırları arasındaki harfli satırlardan alınır.
    """
    blocks: list[_Blok] = []
    cur: list[list] = []
    names: list[str] = []
    width = None
    for raw in text.splitlines():
        line = clean_spaces(_ZW.sub("", raw))
        m = _METIN_SATIR.match(line)
        if not m:
            if cur and line and not re.search(r"\d", line):
                names.append(line)
            continue
        if m.group("s") != str(len(cur) + 1):
            if cur:
                raise UcretTablosuHatasi(f"metinde sınıf sırası bozuk: {line[:40]!r}")
            continue
        values = [p for p in m.group("tutar").split("₺") if p.strip()]
        width = width or len(values)
        if len(values) != width:
            raise UcretTablosuHatasi(f"metin satırında {len(values)} tutar var, {width} bekleniyordu")
        names.append(m.group("on"))
        cur.append(values)
        if len(cur) == 6:
            # Dikey "GİRİŞ GİŞELERİ" yazısından kalan tek harfleri at
            words = [w for w in " ".join(names).split() if len(w) > 1 or w.isdigit()]
            blocks.append(_Blok(ad=clean_spaces(" ".join(words)), satirlar=cur))
            cur, names = [], []
    if width is None or width < 2 or not blocks:
        return None
    if len(blocks) != width:
        raise UcretTablosuHatasi(f"metinde {len(blocks)} giriş satırı ama {width} çıkış sütunu var")
    adlar = [b.ad for b in blocks]
    if any(not a for a in adlar) or len(set(adlar)) != len(adlar):
        raise UcretTablosuHatasi("metinden istasyon adları okunamadı")
    return _kare(list(adlar), blocks)


# ============================================================================ PDF

_NOT = re.compile(r"^(?:\*|not\s*\d*\s*:?|açıklamalar)", re.IGNORECASE)


def _notlar(text: str) -> list[str]:
    out = []
    for line in text.splitlines():
        line = clean_spaces(_ZW.sub("", line))
        if _NOT.match(line) and len(line) > 12 and not fold(line).startswith("aciklamalar"):
            line = re.sub(r"^(?:\*\s*|Not\s*\d*\s*:?\s*)", "", line, flags=re.IGNORECASE)
            if line and line not in out:
                out.append(line)
    return out


def _serbest_gecis(table: list[list]) -> list[dict] | None:
    """Serbest geçiş (SGS) noktalarının tek tutarlı ücret tablosu: ad, yön, 1–6. sınıf."""
    if not table or len(table) < 2:
        return None
    head = [_hucre(x) for x in table[0]]
    if len(head) < 7 or [re.sub(r"\D", "", h) for h in head[-6:]] != ["1", "2", "3", "4", "5", "6"]:
        return None
    out = []
    for row in table[1:]:
        cells = [_hucre(x).replace("\n", " ") for x in row]
        if len(cells) < 7 or not cells[0]:
            continue
        try:
            fares = [ucret_oku(x) for x in cells[-6:]]
        except UcretTablosuHatasi:
            return None
        if len(cells) >= 8:
            ad, yon = cells[0], cells[1]
        else:
            m = re.search(r"\(?\s*(K\s*uzey|G\s*üney|KUZEY|GÜNEY)\s*-\s*(Kuzey|Güney|KUZEY|GÜNEY)\s*\)?\s*$", cells[0])
            ad, yon = (cells[0][:m.start()], m.group(0)) if m else (cells[0], "")
        yon = baslik_harfi(re.sub(r"\s+", "", yon.strip("() ")).replace("-", " - "))
        out.append({"ad": baslik_harfi(clean_spaces(ad)), "yon": yon or None, "ucret": fares})
    return out or None


_TARIH = re.compile(r"(?<!\d)(\d{1,2})[./](\d{1,2})[./](\d{4})(?!\d)")


def _gecerlilik(text: str, ref: datetime) -> datetime | None:
    """Tarifenin geçerlilik başlangıcı: "… 01/07/2026 saat 00:00'dan itibaren geçerlidir" satırı.

    Yılı açık yazılmış tarihler tercih edilir; "01.01.2022 tarihinden itibaren iki yönlü ücret" gibi
    başka bir konuyu anlatan satırlar atlanır.
    """
    from .extract import find_effective_from
    from .timeutil import TZ

    groups: list[list[datetime]] = [[], []]
    for line in text.splitlines():
        f = fold(line)
        if "tarihinden" in f:
            continue
        rank = 0 if "gecerli" in f else 1 if "itibar" in f else None
        if rank is None:
            continue
        for m in _TARIH.finditer(line):
            try:
                groups[rank].append(datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)), tzinfo=TZ))
            except ValueError:
                continue
    for g in groups:
        if g:
            return max(g)
    return find_effective_from(text, ref)


_KESIM = re.compile(r"([A-ZÇĞİÖŞÜ]{3,}(?:\s*-\s*[A-ZÇĞİÖŞÜ]{3,})+)\s+ARASI")


def _baslik(text: str) -> str:
    for line in text.splitlines():
        line = clean_spaces(_ZW.sub("", line))
        if len(line) > 8 and re.search(r"[A-Za-zÇĞİÖŞÜçğıöşü]{4}", line) and "TARİFESİ" not in line.upper()[:3]:
            return line
    return ""


def parse_matrix_pdf(data: bytes, *, ref: datetime | None = None) -> list[dict]:
    """KGM otoyol tarife PDF'indeki gişeden gişeye ücret tablolarını okur.

    Her tablo için bir sözlük döner (bir PDF'te birden fazla otoyol tablosu olabilir). Ücret matrisi
    içermeyen PDF'ler (ör. tek ücretli köprüler) için boş liste döner. Matris bulunup okunamazsa
    UcretTablosuHatasi verir.
    """
    import pdfplumber  # yavaş yüklenen bağımlılık

    from .timeutil import now as tz_now

    results: list[dict] = []
    texts: list[str] = []
    sgs: list[dict] = []
    errors: list[str] = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages[:10]:
            text = page.extract_text() or ""
            texts.append(text)
            tables = page.extract_tables() or []
            found: list[_Tablo] = []
            page_errors: list[str] = []
            for table in tables:
                try:
                    t = tablo_coz(table)
                except UcretTablosuHatasi as exc:
                    page_errors.append(str(exc))
                    continue
                if t is not None:
                    found.append(t)
                    continue
                s = _serbest_gecis(table)
                if s:
                    sgs.extend(s)
            if not found and text.count("₺") >= 30:
                # Tablo çizgileri bozuksa (hücreler birleşmiş) satır satır metinden dene
                try:
                    t = metin_coz(page.extract_text(y_tolerance=1, x_tolerance=1.5) or "")
                except UcretTablosuHatasi as exc:
                    page_errors.append(f"metin: {exc}")
                    t = None
                if t is not None:
                    found.append(t)
                    page_errors = []
            errors.extend(page_errors)
            kesimler = [baslik_harfi(k).replace(" - ", " – ") for k in _KESIM.findall(text)]
            for k, t in enumerate(found):
                d = t.to_dict()
                d["kesim"] = kesimler[k] if len(kesimler) == len(found) and len(found) > 1 else None
                results.append(d)
    full = "\n".join(texts)
    if errors and not results:
        raise UcretTablosuHatasi("; ".join(dict.fromkeys(errors))[:300])
    if errors:
        raise UcretTablosuHatasi("tablolardan biri okunamadı: " + "; ".join(dict.fromkeys(errors))[:250])
    eff = _gecerlilik(full, ref or tz_now())
    title = baslik_harfi(_baslik(full))
    notes = _notlar(full)
    for r in results:
        r["baslik"] = title
        r["gecerlilik"] = to_iso(eff)
        r["notlar"] = notes
        r["serbest_gecis"] = sgs if len(results) == 1 else []
    if sgs and len(results) > 1:
        results[0]["serbest_gecis"] = sgs
    return results


# ============================================================================ gişe kaydı (konumlar)

class GiseKaydiHatasi(Exception):
    pass


# giseler.yaml'ın otoyol kimliği olmayan bölümleri
SERBEST_BOLUMU = "serbest_gecis"
BAGLANTI_BOLUMU = "baglantilar"
_AYRILMIS = {SERBEST_BOLUMU, BAGLANTI_BOLUMU}

# Ücretine bir köprünün geçiş ücreti dahil olan tablolar (otoyol kimliği → config/crossings.yaml kimlikleri).
# Bu tabloyla hesaplanan yolculuğa köprü ücreti ayrıca eklenmemeli; yoksa köprü iki kez sayılır.
#   yss-kuzey-cevre   : 13 numaralı PDF'in notu: "Köprü Geçiş Ücreti İçermektedir."
#   gebze-…-bursa     : tablonun ilk iki istasyonu Osmangazi Köprüsü'dür (kuzeye giderken köprüye kadar ücret
#                       köprüyü içerir; güneye giderken köprü ücreti "İzmir Yönü" istasyonunun köşegenidir)
#   malkara-canakkale : belgenin adı "(1915 Çanakkale Köprüsü dahil)"; G-5 istasyonu köprüdür
DAHIL_GECISLER = {
    "yss-kuzey-cevre": ["yavuz-sultan-selim"],
    "gebze-orhangazi-izmir-gebze-bursa": ["osmangazi"],
    "malkara-canakkale": ["1915-canakkale"],
}


def _ad_anahtari(name: str | None) -> str:
    """Kayıt eşleşmesi için ad: büyük/küçük harf, Türkçe harf, boşluk ve noktalama farkı önemsiz."""
    return re.sub(r"[^a-z0-9]+", "", fold(name))


def _kayit_yaml(path) -> dict | None:
    """giseler.yaml'ın ham içeriği; dosya yoksa None."""
    import yaml

    try:
        with open(path, encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
    except FileNotFoundError:
        return None
    except yaml.YAMLError as exc:
        raise GiseKaydiHatasi(f"giseler.yaml okunamadı: {str(exc)[:200]}") from None
    if not isinstance(raw, dict):
        raise GiseKaydiHatasi("giseler.yaml: en üstte otoyol kimlikleri olmalı")
    return raw


def _nokta(item: dict, yer: str) -> dict:
    """Bir kayıt öğesinin konumu, ili ve bölgesi (doğrulanmış)."""
    from . import bolgeler

    lat = lon = None
    if item.get("konum") is not None:
        try:
            lat, lon = (float(v) for v in item["konum"])
        except (TypeError, ValueError):
            raise GiseKaydiHatasi(f"giseler.yaml: {yer}: konum [enlem, boylam] ya da null olmalı") from None
        if not bolgeler.turkiye_icinde(lat, lon):
            raise GiseKaydiHatasi(f"giseler.yaml: {yer}: konum Türkiye dışında ({lat}, {lon})")
    plaka = bolgeler.plaka_bul(item.get("il"))
    if item.get("il") and plaka is None:
        raise GiseKaydiHatasi(f"giseler.yaml: {yer}: bilinmeyen il '{item.get('il')}'")
    return {"lat": lat, "lon": lon, "il": bolgeler.il_adi(plaka), "bolge": bolgeler.bolge(plaka)}


def _ogeler(oid, items, ne: str) -> list[tuple[str, dict]]:
    """Bir otoyol listesindeki öğeler: (ad, öğe). Adı olmayan öğe hata verir."""
    if not isinstance(items, list):
        raise GiseKaydiHatasi(f"giseler.yaml: {oid} altında {ne} listesi olmalı")
    out = []
    for item in items:
        ad = clean_spaces(str((item or {}).get("ad") or "")) if isinstance(item, dict) else ""
        if not ad:
            raise GiseKaydiHatasi(f"giseler.yaml: {oid} altında adı olmayan kayıt var")
        out.append((ad, item))
    return out


def gise_kaydi_oku(path) -> dict[str, dict[str, dict]]:
    """config/giseler.yaml → {otoyol kimliği: {ad anahtarı: {ad, lat, lon, il, bolge, serbest}}}.

    "serbest_gecis" ve "baglantilar" bölümleri burada okunmaz (serbest_kaydi_oku, baglanti_kaydi_oku).
    Biçim hatası GiseKaydiHatasi verir; dosya yoksa boş kayıt döner (tüm gişeler "kayıtsız" sayılır).
    """
    raw = _kayit_yaml(path)
    if raw is None:
        return {}
    out: dict[str, dict[str, dict]] = {}
    for oid, items in raw.items():
        if oid in _AYRILMIS:
            continue
        gises: dict[str, dict] = {}
        for ad, item in _ogeler(oid, items, "gişe"):
            yer = f"{oid} / {ad}"
            key = _ad_anahtari(ad)
            if key in gises:
                raise GiseKaydiHatasi(f"giseler.yaml: {yer} iki kez yazılmış")
            if not isinstance(item.get("serbest", False), bool):
                raise GiseKaydiHatasi(f"giseler.yaml: {yer}: serbest true ya da false olmalı")
            gises[key] = {"ad": ad, **_nokta(item, yer), "serbest": bool(item.get("serbest"))}
        out[str(oid)] = gises
    return out


def serbest_kaydi_oku(path) -> dict[str, dict[str, dict]]:
    """giseler.yaml'ın "serbest_gecis" bölümü → {otoyol kimliği: {satır anahtarı: {ad, lat, lon, il, bolge}}}.

    Her öğe bir serbest geçiş noktasıdır (fiziksel gişe/köprü); "satirlar" o noktanın tarifedeki serbest
    geçiş satırlarıdır (ör. iki yönün "A"/"B" satırı). "satirlar" yazılmazsa satır adı öğenin adıdır.
    """
    raw = _kayit_yaml(path)
    bolum = (raw or {}).get(SERBEST_BOLUMU) or {}
    if not isinstance(bolum, dict):
        raise GiseKaydiHatasi(f"giseler.yaml: {SERBEST_BOLUMU} altında otoyol kimlikleri olmalı")
    out: dict[str, dict[str, dict]] = {}
    for oid, items in bolum.items():
        rows: dict[str, dict] = {}
        for ad, item in _ogeler(oid, items, "serbest geçiş noktası"):
            yer = f"{SERBEST_BOLUMU} / {oid} / {ad}"
            satirlar = item.get("satirlar", [ad])
            if not isinstance(satirlar, list) or not satirlar or not all(isinstance(x, str) and x.strip() for x in satirlar):
                raise GiseKaydiHatasi(f"giseler.yaml: {yer}: satirlar ad listesi olmalı")
            nokta = {"ad": ad, **_nokta(item, yer)}
            for satir in satirlar:
                key = _ad_anahtari(satir)
                if key in rows:
                    raise GiseKaydiHatasi(f"giseler.yaml: {yer}: '{satir}' satırı iki kez yazılmış")
                rows[key] = nokta
        out[str(oid)] = rows
    return out


def _uc(v, yer: str) -> dict:
    if not isinstance(v, dict) or not v.get("otoyol") or not v.get("ad"):
        raise GiseKaydiHatasi(f"giseler.yaml: {yer}: {{otoyol, ad}} olmalı")
    return {"otoyol": str(v["otoyol"]), "ad": clean_spaces(str(v["ad"]))}


def baglanti_kaydi_oku(path) -> list[dict]:
    """giseler.yaml'ın "baglantilar" bölümü: farklı tarife tabloları arasında otoyoldan çıkmadan geçilen
    gişe çiftleri. Her öğe: a, b ({otoyol, ad}), yol_km, not; isteğe bağlı tek_yon ve ara_serbest."""
    raw = _kayit_yaml(path)
    items = (raw or {}).get(BAGLANTI_BOLUMU) or []
    if not isinstance(items, list):
        raise GiseKaydiHatasi(f"giseler.yaml: {BAGLANTI_BOLUMU} bir liste olmalı")
    out, seen = [], set()
    for n, item in enumerate(items, 1):
        yer = f"{BAGLANTI_BOLUMU} #{n}"
        if not isinstance(item, dict):
            raise GiseKaydiHatasi(f"giseler.yaml: {yer}: a, b, yol_km ve not olmalı")
        a, b = _uc(item.get("a"), f"{yer} a"), _uc(item.get("b"), f"{yer} b")
        if a["otoyol"] == b["otoyol"]:
            raise GiseKaydiHatasi(f"giseler.yaml: {yer}: iki uç aynı tabloda ({a['otoyol']})")
        key = frozenset([(a["otoyol"], _ad_anahtari(a["ad"])), (b["otoyol"], _ad_anahtari(b["ad"]))])
        if key in seen:
            raise GiseKaydiHatasi(f"giseler.yaml: {yer}: aynı bağlantı iki kez yazılmış")
        seen.add(key)
        try:
            yol_km = float(item["yol_km"])
        except (KeyError, TypeError, ValueError):
            raise GiseKaydiHatasi(f"giseler.yaml: {yer}: yol_km (iki nokta arası yol uzunluğu) sayı olmalı") from None
        notu = clean_spaces(str(item.get("not") or ""))
        if not notu:
            raise GiseKaydiHatasi(f"giseler.yaml: {yer}: not yazılmalı (neden bağlantı olduğu)")
        if not isinstance(item.get("tek_yon", False), bool):
            raise GiseKaydiHatasi(f"giseler.yaml: {yer}: tek_yon true ya da false olmalı")
        ara_raw = item.get("ara_serbest") or {}
        if not isinstance(ara_raw, dict) or set(ara_raw) - {"ab", "ba"}:
            raise GiseKaydiHatasi(f"giseler.yaml: {yer}: ara_serbest yalnızca ab ve ba listeleri içerebilir")
        ara = {}
        for yon in ("ab", "ba"):
            rows = ara_raw.get(yon) or []
            if not isinstance(rows, list):
                raise GiseKaydiHatasi(f"giseler.yaml: {yer}: ara_serbest.{yon} liste olmalı")
            ara[yon] = []
            for r in rows:
                u = _uc(r, f"{yer} ara_serbest.{yon}")
                u["yon"] = clean_spaces(str(r.get("yon") or "")) or None
                ara[yon].append(u)
        out.append({"a": a, "b": b, "yol_km": yol_km, "tek_yon": bool(item.get("tek_yon")),
                    "ara_serbest": ara, "not": notu})
    return out


def _yuvarla(v):
    return round(v, 5) if v is not None else None


def konumlari_uygula(otoyollar: list[dict], kayit: dict[str, dict[str, dict]],
                     serbest: dict[str, dict[str, dict]] | None = None) -> list[dict]:
    """İstasyonlara gişe kaydındaki konumu, ili ve bölgeyi yazar. Kayıtta olmayanları döndürür.

    Kayıtta olmayan istasyon tabloda kalır (hesapta seçilebilir) ama konumu boştur, haritaya konmaz.
    Serbest geçiş noktası olan istasyona "serbest": true yazılır. serbest verilirse tabloların serbest
    geçiş satırlarına da konum yazılır; kayıtta olmayan satırlar "tur": "serbest" ile döner (aynı ad bir kez).
    """
    kayitsiz = []
    for o in otoyollar:
        gises = kayit.get(o["id"]) or {}
        for s in o["istasyonlar"]:
            g = gises.get(_ad_anahtari(s["ad"]))
            lat, lon = (g["lat"], g["lon"]) if g else (None, None)
            s.update(lat=_yuvarla(lat), lon=_yuvarla(lon), il=g["il"] if g else None, bolge=g["bolge"] if g else None)
            s.pop("serbest", None)
            if g and g.get("serbest"):
                s["serbest"] = True
            if g is None:
                kayitsiz.append({"otoyol": o["id"], "otoyol_adi": o.get("ad") or o["id"], "ad": s["ad"]})
        if serbest is None:
            continue
        rows = serbest.get(o["id"]) or {}
        eksik: list[str] = []
        for r in o.get("serbest_gecis") or []:
            p = rows.get(_ad_anahtari(r["ad"]))
            r.update(lat=_yuvarla(p["lat"]) if p else None, lon=_yuvarla(p["lon"]) if p else None,
                     il=p["il"] if p else None, bolge=p["bolge"] if p else None)
            if p is None and r["ad"] not in eksik:
                eksik.append(r["ad"])
        kayitsiz += [{"otoyol": o["id"], "otoyol_adi": o.get("ad") or o["id"], "ad": ad, "tur": "serbest"}
                     for ad in eksik]
    return kayitsiz


def _uzaklik(a: tuple[float, float], b: tuple[float, float]) -> float:
    """İki nokta arası kuş uçuşu km (haversine)."""
    import math

    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp, dl = p2 - p1, math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def baglantilari_coz(otoyollar: list[dict], baglantilar: list[dict]) -> tuple[list[dict], list[str]]:
    """Kayıttaki bağlantıları tablo sıralarına (istasyon ve serbest geçiş satırı indeksleri) çevirir.

    Ucu tabloda bulunamayan bağlantı yayımlanmaz; açıklaması ikinci listede döner.
    """
    by_id = {o["id"]: o for o in otoyollar}
    out, eksik = [], []

    def istasyon(u: dict) -> dict | None:
        o = by_id.get(u["otoyol"])
        if o is None:
            return None
        key = _ad_anahtari(u["ad"])
        i = next((k for k, s in enumerate(o["istasyonlar"]) if _ad_anahtari(s["ad"]) == key), None)
        return None if i is None else {"otoyol": o["id"], "i": i, "ad": o["istasyonlar"][i]["ad"]}

    def satir(u: dict) -> dict | None:
        o = by_id.get(u["otoyol"])
        rows = (o or {}).get("serbest_gecis") or []
        key = _ad_anahtari(u["ad"])
        j = next((k for k, r in enumerate(rows) if _ad_anahtari(r["ad"]) == key
                  and (u.get("yon") is None or _ad_anahtari(r.get("yon")) == _ad_anahtari(u["yon"]))), None)
        return None if j is None else {"otoyol": o["id"], "j": j, "ad": rows[j]["ad"], "yon": rows[j].get("yon")}

    for b in baglantilar:
        a_, b_ = istasyon(b["a"]), istasyon(b["b"])
        ara = {yon: [satir(u) for u in b["ara_serbest"][yon]] for yon in ("ab", "ba")}
        bulunamayan = [f"{u['otoyol']} / {u['ad']}" for u, x in ((b["a"], a_), (b["b"], b_)) if x is None]
        bulunamayan += [f"{u['otoyol']} / {u['ad']} (serbest geçiş)" for yon in ("ab", "ba")
                        for u, x in zip(b["ara_serbest"][yon], ara[yon]) if x is None]
        if bulunamayan:
            eksik.append(f"{b['a']['ad']} ↔ {b['b']['ad']}: tabloda yok: {', '.join(bulunamayan)}")
            continue
        sa = by_id[a_["otoyol"]]["istasyonlar"][a_["i"]]
        sb = by_id[b_["otoyol"]]["istasyonlar"][b_["i"]]
        uz = None
        if None not in (sa.get("lat"), sa.get("lon"), sb.get("lat"), sb.get("lon")):
            uz = round(_uzaklik((sa["lat"], sa["lon"]), (sb["lat"], sb["lon"])), 1)
        out.append({"a": a_, "b": b_, "tek_yon": b["tek_yon"], "yol_km": b["yol_km"], "uzaklik_km": uz,
                    "ara_serbest": ara, "ucretlendirme": "ayri", "not": b["not"]})
    return out, eksik


def kayitlari_yansit(data: dict, cfg: Config, existing: dict | None = None) -> tuple[list[dict], list[str], str | None]:
    """Gişe kaydını (konumlar, serbest geçiş noktaları, bağlantılar) tablo verisine yazar.

    Döner: (kayıtsız gişe/noktalar, çözülemeyen bağlantılar, kayıt hatası). Kayıt okunamazsa önceki
    tablodaki konumlar ve bağlantılar korunur.
    """
    for o in data["otoyollar"]:
        o["dahil_gecisler"] = list(DAHIL_GECISLER.get(o["id"], []))
    try:
        kayit = gise_kaydi_oku(cfg.gise_kaydi)
        serbest = serbest_kaydi_oku(cfg.gise_kaydi)
        baglantilar = baglanti_kaydi_oku(cfg.gise_kaydi)
    except GiseKaydiHatasi as exc:
        kayit, serbest = _kayit_tablodan(existing)
        kayitsiz = konumlari_uygula(data["otoyollar"], kayit, serbest)
        data["baglantilar"] = list((existing or {}).get("baglantilar") or [])
        return kayitsiz, [], str(exc)
    kayitsiz = konumlari_uygula(data["otoyollar"], kayit, serbest)
    data["baglantilar"], eksik = baglantilari_coz(data["otoyollar"], baglantilar)
    return kayitsiz, eksik, None


def _konum_ozeti(otoyollar: list[dict]) -> dict[str, str]:
    return {o["id"]: f"{sum(1 for s in o['istasyonlar'] if s.get('lat') is not None)}/{len(o['istasyonlar'])}"
            for o in otoyollar}


# ============================================================================ belge → otoyol kaydı

def _bilinen(text: str) -> tuple[str, str, str | None] | None:
    t = fold(text)
    for keys, oid, ad, yol in _BILINEN:
        if all(k in t for k in keys):
            return oid, ad, yol
    return None


def _belge_adi(link_text: str) -> str:
    return clean_spaces(link_text)


def otoyol_kayitlari(tablolar: list[dict], url: str, link_text: str) -> list[dict]:
    """parse_matrix_pdf çıktısını panelin okuduğu otoyol kayıtlarına çevirir."""
    known = _bilinen(link_text + " " + url.rsplit("/", 1)[-1])
    out = []
    for n, t in enumerate(tablolar, 1):
        if known:
            oid, ad, yol = known
        else:
            base = re.sub(r"^\s*\d+\s*[-.)]\s*|\b(?:KGM|Geçiş Ücretleri|Ücret Tarifesi)\b", "", link_text).strip(" -")
            oid, ad, yol = slugify(base or t.get("baslik") or "otoyol", 60), clean_spaces(base) or t.get("baslik"), None
        if len(tablolar) > 1:
            kesim = t.get("kesim") or f"{t['istasyonlar'][0]} – {t['istasyonlar'][-1]}"
            oid = f"{oid}-{slugify(kesim, 40)}"
            ad = f"{ad}: {kesim}"
        out.append({
            "id": oid,
            "ad": ad,
            "yol": yol,
            "belge": url,
            "belge_adi": _belge_adi(link_text),
            "gecerlilik": t.get("gecerlilik"),
            "tur": t["tur"],
            "yonlu": t["yonlu"],
            "istasyonlar": [{"ad": a, "lat": None, "lon": None, "il": None, "bolge": None} for a in t["istasyonlar"]],
            "ucret": t["ucret"],
            "ucret_geri": t["ucret_geri"],
            "km": t["km"],
            "azami": t["azami"],
            "serbest_gecis": t.get("serbest_gecis") or [],
            "notlar": t.get("notlar") or [],
            "uyarilar": t.get("uyarilar") or [],
        })
    return out


# ============================================================================ yenileme

def _imza(state: dict, cfg: Config) -> str:
    """Radarın kendi tarife izleyicisinin gördüğü PDF özetleri: değişince tablo hemen yenilenir."""
    parts = []
    for src in cfg.sources:
        if src.type == "tarife_listesi":
            docs = (state.get(src.id) or {}).get("docs") or {}
            parts += sorted(f"{k}:{d.get('sha256')}" for k, d in docs.items() if not d.get("removed_at"))
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16] if parts else ""


def needs_refresh(cfg: Config, state: dict, existing: dict | None, now: datetime) -> bool:
    st = state.get(STATE_KEY) or {}
    if not existing or not existing.get("otoyollar"):
        return hours_since(st.get("son_deneme"), now) >= TEKRAR_DENEME_SAAT
    if st.get("imza") != _imza(state, cfg) and hours_since(st.get("son_deneme"), now) >= 1:
        return True
    return hours_since(st.get("son_deneme"), now) >= YENILEME_SAAT


def _icerik(data: dict) -> dict:
    d = dict(data)
    d.pop("olusturma", None)
    return d


def refresh(cfg: Config, store: Store, state: dict, now: datetime, *, force: bool = False,
            transport: httpx.BaseTransport | None = None) -> str | None:
    """Gerekiyorsa gişeden gişeye ücret tablosunu yeniler. Bir not döner (yenileme yoksa None)."""
    from .collectors import PDF_RE, _is_tariff, doc_key
    from .extract import extract_links
    from .fetch import Fetcher

    src = next((s for s in cfg.sources if s.type == "tarife_listesi" and s.enabled), None)
    if src is None:
        return None
    existing = store.read(DOSYA, None)
    if not force and not needs_refresh(cfg, state, existing, now):
        return konumlari_tazele(cfg, store, state, existing)
    st = state.setdefault(STATE_KEY, {})
    st["son_deneme"] = to_iso(now)
    st["imza"] = _imza(state, cfg)
    belgeler: dict = st.setdefault("belgeler", {})
    # Kopya: önceki kayıtlar aşağıda güncellenir (konumlar), değişiklik karşılaştırması bozulmasın
    old_by_id = {o["id"]: copy.deepcopy(o) for o in (existing or {}).get("otoyollar") or []}

    delay = 0 if transport is not None else cfg.settings.request_delay
    hatalar: list[str] = []
    otoyollar: list[dict] = []
    try:
        with Fetcher(cfg.settings.user_agent, min_delay=delay, transport=transport) as fetcher:
            page = fetcher.get(src.url)
            links = [l for l in extract_links(page.text, page.final_url)
                     if PDF_RE.search(l.url) and _is_tariff(l.text, l.url)]
            if not links:
                raise UcretTablosuHatasi("sayfada PDF tarife bağlantısı bulunamadı")
            seen: set[str] = set()
            for link in links:
                key = doc_key(link)
                if key in seen:
                    continue
                seen.add(key)
                prev = belgeler.get(key) or {}
                entry = dict(prev)
                entry.update(url=link.url, ad=link.text, kontrol=to_iso(now))
                belgeler[key] = entry
                kept = [old_by_id[i] for i in prev.get("otoyollar") or [] if i in old_by_id]
                try:
                    same_url = prev.get("url") == link.url
                    r = fetcher.get(link.url, etag=prev.get("etag") if same_url and kept else None,
                                    last_modified=prev.get("last_modified") if same_url and kept else None)
                    if r.not_modified:
                        otoyollar += kept
                        continue
                    if not r.is_pdf:
                        raise UcretTablosuHatasi("bağlantı PDF döndürmedi")
                    digest = hashlib.sha256(r.content).hexdigest()[:32]
                    entry.update(etag=r.headers.get("etag"), last_modified=r.headers.get("last-modified"))
                    if digest == prev.get("sha256") and not prev.get("hata") and (kept or prev.get("matris") is False):
                        otoyollar += kept
                        continue
                    tablolar = parse_matrix_pdf(r.content, ref=now)
                    kayitlar = otoyol_kayitlari(tablolar, link.url, link.text)
                    entry.update(sha256=digest, matris=bool(kayitlar), otoyollar=[k["id"] for k in kayitlar], hata=None)
                    otoyollar += kayitlar
                except Exception as exc:
                    log.debug("Ücret tablosu okunamadı: %s", link.url, exc_info=True)
                    msg = redact(exc, cfg.settings)[:300]
                    entry["hata"] = msg
                    entry["hata_zamani"] = to_iso(now)
                    hatalar.append(f"{link.text}: {msg}")
                    otoyollar += kept          # önceki iyi veri korunur
            # Listeden kalkan belgeler: bu turda okunamayan belge varsa (ör. bağlantı adı değişti ve yeni
            # belge okunamadı) eski otoyollar korunur; her şey okunduysa kalkan belgenin verisi de kalkar.
            for key in [k for k in belgeler if k not in seen]:
                gone = belgeler[key]
                if hatalar:
                    gone["kaldirildi"] = gone.get("kaldirildi") or to_iso(now)
                    otoyollar += [old_by_id[i] for i in gone.get("otoyollar") or [] if i in old_by_id]
                else:
                    del belgeler[key]
    except Exception as exc:
        st["hata"] = redact(exc, cfg.settings)[:300]
        return f"Ücret tablosu alınamadı: {st['hata']}"

    # Aynı kimlik iki kez gelmesin (önceki veriyle yenisi)
    uniq: dict[str, dict] = {}
    for o in otoyollar:
        uniq.setdefault(o["id"], o)
    otoyollar = list(uniq.values())
    if not otoyollar:
        st["hata"] = "hiç ücret tablosu okunamadı" + (f" ({hatalar[0][:200]})" if hatalar else "")
        return f"Ücret tablosu alınamadı: {st['hata']}"

    for o in otoyollar:   # eski veride yol numarası boş kalmış olabilir
        if not o.get("yol"):
            o["yol"] = next((yol for _, oid, _, yol in _BILINEN if o["id"] == oid or o["id"].startswith(oid + "-")), None)

    data = {
        "schema": SCHEMA,
        "olusturma": to_iso(now),
        "kaynak": KAYNAK,
        "kaynak_adres": src.url,
        "siniflar": dict(SINIFLAR),
        "otoyollar": otoyollar,
        "baglantilar": [],
    }
    # Kayıt bozuksa ücretler yine güncellenir; konumlar ve bağlantılar öncekiler kalır
    kayitsiz, baglanti_eksik, kayit_hatasi = kayitlari_yansit(data, cfg, existing)
    kayit_notu = f"gişe kaydı okunamadı, önceki konumlar kullanıldı: {kayit_hatasi}" if kayit_hatasi else None
    st.update(hata=None, son_basari=to_iso(now), hatalar=hatalar, otoyol=len(otoyollar),
              konum=_konum_ozeti(otoyollar), kayitsiz=kayitsiz, baglanti_eksik=baglanti_eksik)
    if existing and _icerik(existing) == _icerik(data):
        if hatalar:
            return f"Ücret tablosu: {len(hatalar)} belge okunamadı, önceki veri korundu"
        return f"Ücret tablosu: {kayit_notu}" if kayit_notu else None
    store.write(DOSYA, data)
    note = f"Ücret tablosu: {len(otoyollar)} otoyol, {sum(len(o['istasyonlar']) for o in otoyollar)} istasyon güncellendi"
    if hatalar:
        note += f" ({len(hatalar)} belge okunamadı, önceki veri korundu)"
    note += _kayit_notlari(kayitsiz, baglanti_eksik)
    if kayit_notu:
        note += f"; {kayit_notu}"
    return note


def _kayit_tablodan(existing: dict | None) -> tuple[dict[str, dict[str, dict]], dict[str, dict[str, dict]]]:
    """Gişe kaydı okunamazsa yedek: mevcut tablodaki konumlar (gişeler ve serbest geçiş satırları)."""
    gises: dict[str, dict[str, dict]] = {}
    serbest: dict[str, dict[str, dict]] = {}
    for o in (existing or {}).get("otoyollar") or []:
        gises[o["id"]] = {_ad_anahtari(s["ad"]): {"ad": s["ad"], "lat": s.get("lat"), "lon": s.get("lon"),
                                                  "il": s.get("il"), "bolge": s.get("bolge"),
                                                  "serbest": bool(s.get("serbest"))} for s in o["istasyonlar"]}
        serbest[o["id"]] = {_ad_anahtari(r["ad"]): {"ad": r["ad"], "lat": r.get("lat"), "lon": r.get("lon"),
                                                    "il": r.get("il"), "bolge": r.get("bolge")}
                            for r in o.get("serbest_gecis") or [] if "lat" in r}
    return gises, serbest


def _kayitsiz_metni(kayitsiz: list[dict], limit: int = 5) -> str:
    adlar = [f"{k['ad']} ({k['otoyol']}{', serbest geçiş' if k.get('tur') == 'serbest' else ''})" for k in kayitsiz]
    return ", ".join(adlar[:limit]) + (f" ve {len(adlar) - limit} gişe daha" if len(adlar) > limit else "")


def _kayit_notlari(kayitsiz: list[dict], baglanti_eksik: list[str]) -> str:
    note = ""
    if kayitsiz:
        note += f"; gişe kaydında olmayan {len(kayitsiz)} gişe: " + _kayitsiz_metni(kayitsiz)
    if baglanti_eksik:
        note += f"; tabloda bulunamayan {len(baglanti_eksik)} bağlantı: " + "; ".join(baglanti_eksik[:3])
    return note


def konumlari_tazele(cfg: Config, store: Store, state: dict, existing: dict | None) -> str | None:
    """PDF'ler yeniden okunmadan, gişe kaydındaki değişikliği (config/giseler.yaml) tabloya yansıtır.

    Her radar turunda çağrılır; kayıt değişmediyse hiçbir şey yazılmaz.
    """
    if not existing or not existing.get("otoyollar"):
        return None
    st = state.setdefault(STATE_KEY, {})
    try:
        for oku in (gise_kaydi_oku, serbest_kaydi_oku, baglanti_kaydi_oku):
            oku(cfg.gise_kaydi)
    except GiseKaydiHatasi as exc:
        if st.get("kayit_hatasi") == str(exc):
            return None
        st["kayit_hatasi"] = str(exc)
        return f"Gişe kaydı okunamadı, konumlar değiştirilmedi: {exc}"
    st.pop("kayit_hatasi", None)
    data = copy.deepcopy(existing)
    kayitsiz, baglanti_eksik, _ = kayitlari_yansit(data, cfg, existing)
    st.update(konum=_konum_ozeti(data["otoyollar"]), kayitsiz=kayitsiz, baglanti_eksik=baglanti_eksik)
    if data == existing:
        return None
    store.write(DOSYA, data)
    return "Ücret tablosu: gişe konumları güncellendi (config/giseler.yaml)" + _kayit_notlari(kayitsiz, baglanti_eksik)
