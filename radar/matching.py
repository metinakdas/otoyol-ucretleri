"""Geçiş adı eşleme ve haber/duyuru sınıflandırma."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .config import CrossingCfg
from .textutil import fold, sentences, shorten

KIND_PRICE = "ucret_degisikligi"
KIND_FREE = "ucretsiz_gecis"

_FREE = [r"ucretsiz", r"ucret alinmayacak", r"ucret alinmaz", r"bedava", r"ucret odemeden"]
# Güçlü ücret ifadeleri: tek başına yeterli
_PRICE_STRONG = [
    r"\bzam\w*", r"\btarife\w*", r"yeni ucret\w*",
    r"\bucret\w*\s+(?:artis\w*|guncelle\w*|belirlen\w*|degis\w*)",
]
# Zayıf ücret ifadeleri: ceza, ihale gibi gürültü kelimeleriyle birlikteyse sayılmaz
_PRICE_WEAK = [r"gecis ucret\w*", r"\bfiyat\w*", r"\bindirim\w*"]
_NOISE = [r"\bceza\w*", r"\bihlal\w*", r"\bkacak\w*", r"\bbakiye\w*", r"\bihale\w*", r"\bkaza\w*"]
_PRICE = _PRICE_STRONG + _PRICE_WEAK
# İptal yalnızca başlıktan okunur; gövdedeki "uygulanmayacak" gibi ifadeler çoğu zaman kapsam dışını anlatır.
_CANCEL = [r"\biptal\w*", r"\berte(?:le|len)\w*", r"vazgec\w*", r"geri cekil\w*"]
_EXCLUDE = re.compile(
    r"haric|dahil degil|kapsam disi|kapsamina girmiyor|ucretli olacak|ucretli olmaya devam|"
    r"uygulanmayacak|gecerli olmayacak"
)
_YID = re.compile(r"yap[- ]?islet[- ]?devret|\byid\b")


def _any(patterns: list[str], text: str) -> bool:
    return any(re.search(p, text) for p in patterns)


@dataclass
class Classification:
    kind: str | None            # KIND_PRICE | KIND_FREE | None
    cancel: bool
    crossings: list[str]        # metinde adı geçen geçişler
    generic: bool               # "köprü ve otoyollar" gibi genel ifade var mı
    excluded: list[str] = field(default_factory=list)


class Matcher:
    def __init__(self, crossings: list[CrossingCfg], generic_phrases: list[str]):
        self.crossings = crossings
        pairs = []
        for c in crossings:
            for alias in [c.name, *c.aliases]:
                fa = fold(alias)
                if fa and c.aliases:  # adı listesi boş olanlar (ör. KGM otoyolları) yalnızca genel ifadeyle eşleşir
                    pairs.append((fa, c.id))
        # Uzun ad önce: "1915 çanakkale köprüsü" kısa addan önce denenir
        self._aliases = sorted(set(pairs), key=lambda p: -len(p[0]))
        self._generic = [fold(p) for p in generic_phrases if p]

    @staticmethod
    def _position(haystack: str, needle: str) -> int:
        m = re.search(r"(?<![a-z0-9])" + re.escape(needle) + r"(?![a-z0-9])", haystack)
        return m.start() if m else -1

    def find_crossings(self, text: str) -> list[str]:
        """Metinde adı geçen geçişler, metindeki sırasıyla."""
        t = fold(text)
        first: dict[str, int] = {}
        for alias, cid in self._aliases:
            pos = self._position(t, alias)
            if pos >= 0 and (cid not in first or pos < first[cid]):
                first[cid] = pos
        return sorted(first, key=first.get)

    def is_generic(self, text: str) -> bool:
        t = fold(text)
        return any(p in t for p in self._generic)

    def find_excluded(self, text: str) -> list[str]:
        """"... hariç" gibi cümlelerde adı geçen geçişler."""
        out: list[str] = []
        for sentence in sentences(text):
            fs = fold(sentence)
            if not _EXCLUDE.search(fs):
                continue
            ids = self.find_crossings(sentence)
            if _YID.search(fs):  # "yap-işlet-devret ile yapılanlar hariç" → tüm YİD geçişleri
                ids += [c.id for c in self.crossings if fold(c.operator) == "yid"]
            for cid in ids:
                if cid not in out:
                    out.append(cid)
        return out

    def classify(self, text: str, default_crossings: list[str] | tuple = ()) -> Classification | None:
        """İlgisiz metinler için None döner."""
        t = fold(text)
        crossings = self.find_crossings(text)
        generic = self.is_generic(text)
        if not (crossings or generic or default_crossings):
            return None
        free = _any(_FREE, t)
        price = _any(_PRICE_STRONG, t) or (_any(_PRICE_WEAK, t) and not _any(_NOISE, t))
        cancel = _any(_CANCEL, t)
        kind = KIND_FREE if free else (KIND_PRICE if price else None)
        if kind is None and not cancel:
            return None
        return Classification(kind=kind, cancel=cancel, crossings=crossings, generic=generic,
                              excluded=self.find_excluded(text))

    def crossings_for_document(self, link_text: str, url: str) -> list[CrossingCfg]:
        """KGM tarife PDF'inin hangi geçişlere ait olduğunu tariff_match ifadeleriyle bulur."""
        hay = fold(link_text) + " " + fold(url.rsplit("/", 1)[-1])
        out = []
        for c in self.crossings:
            if any(fold(m) and fold(m) in hay for m in c.tariff_match):
                out.append(c)
        return out


def best_quote(text: str, limit: int = 280) -> str:
    """Kanıt olarak en anlamlı cümle: ücret/ücretsiz/tarih geçen ilk cümle."""
    for s in sentences(text):
        fs = fold(s)
        if _any(_FREE + _PRICE + _CANCEL, fs) and len(s) > 25:
            return shorten(s, limit)
    return shorten(text, limit)
