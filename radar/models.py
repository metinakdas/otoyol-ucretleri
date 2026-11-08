"""Toplayıcıların ürettiği aday kayıtlar."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

STATUS_LABELS = {
    "sinyal": "Sinyal",
    "gundemde": "Gündemde",
    "karar_cikti": "Karar çıktı",
    "yururlukte": "Yürürlükte",
    "kapandi": "Kapandı",
    "iptal_ertelendi": "İptal / ertelendi",
}
RANK = {"sinyal": 0, "gundemde": 1, "karar_cikti": 2, "yururlukte": 3}
OPEN = ("sinyal", "gundemde", "karar_cikti")

KIND_LABELS = {
    "ucret_degisikligi": "Geçiş ücreti değişikliği",
    "ucretsiz_gecis": "Ücretsiz geçiş",
}

FLAG_LABELS = {
    "kontrol_et": "Kontrol et",
    "kacirildi": "Kaçırıldı",
    "tarih_belirsiz": "Tarih belirsiz",
    "tarih_degisti": "Tarih değişti",
    "degerler_okunamadi": "Değerler okunamadı",
    "kapsam_kontrol": "Kapsamı kontrol et",
    "saat_kontrol": "Saatleri kontrol et",
    "olagan_disi": "Olağan dışı değişim",
    "iptal_iddiasi": "İptal haberi var",
    "takvim": "Takvim uyarısı",
    "sona_erdi": "Sona erdi",
}


@dataclass
class Candidate:
    kind: str                    # ucret_degisikligi | ucretsiz_gecis
    title: str
    source_id: str
    tier: str                    # resmi | haber
    url: str
    publisher: str
    crossings: list[str] = field(default_factory=list)
    generic: bool = False        # kapsam genel ifadeden mi geldi
    cancel: bool = False
    quote: str = ""
    published: str | None = None
    prices: dict[str, dict[str, str]] = field(default_factory=dict)   # geçiş → {"1": "59.00"}
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    excluded: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    documents: list[str] = field(default_factory=list)
