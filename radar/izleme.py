"""İzleme: her radar turunun yapılandırılmış kayıtlarını Grafana Cloud'a (Loki) gönderir.

Gönderilen her satır tek bir JSON olaydır: tur özeti, kaynak kontrolleri, bildirim
sonuçları ve notlar. Grafana bu kayıtlardan durum ekranını çizer ve alarm üretir
(ör. "90 dakikadır tur yok", "e-posta gönderilemiyor", "kaynak okunamıyor").

Ayarlar .env/ortamdan gelir; LOKI_URL boşsa izleme tamamen kapalıdır ve radarın
çalışmasını hiçbir biçimde etkilemez. Satırlar guvenlik.redact ile gizli
bilgilerden arındırılır; telefon, e-posta adresi ve anahtarlar gönderilmez.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime

import httpx

from .guvenlik import redact

APP = "tarife-radari"


def _ayar() -> tuple[str, str, str]:
    url = os.environ.get("LOKI_URL", "").strip()
    if url and not url.rstrip("/").endswith("/loki/api/v1/push"):
        url = url.rstrip("/") + "/loki/api/v1/push"
    return url, os.environ.get("LOKI_USER", "").strip(), os.environ.get("LOKI_TOKEN", "").strip()


def aktif() -> bool:
    url, user, token = _ayar()
    return bool(url and user and token)


def _kanal(satir: str) -> str:
    low = satir.lower()
    for ad, anahtarlar in (("telegram", ("telegram",)), ("whatsapp", ("whatsapp",)), ("email", ("e-posta", "email"))):
        if any(a in low for a in anahtarlar):
            return ad
    return "diger"


def _hata_mi(satir: str) -> bool:
    # Yalnızca satırın girişine bakılır; bildirim konusundaki "HATASI" gibi sözcükler yanıltmasın
    bas = satir.split(":", 1)[0].lower()
    return any(k in bas for k in ("gönderilemedi", "bildirilemedi", "alınamadı", "yapılamadı", "okunamadı",
                                  "bırakıldı", "hatası"))


def kayitlar(report, sure_sn: float) -> list[tuple[str, dict]]:
    """RunReport → (seviye, olay) listesi. Olaylar JSON'a çevrilip Loki'ye yazılır."""
    out: list[tuple[str, dict]] = []
    kaynak_hata = 0
    for sid, durum, bilgi in report.sources:
        ok = durum == "tamam"
        kaynak_hata += 0 if ok else 1
        out.append(("info" if ok else "error",
                    {"olay": "kaynak", "kaynak": sid, "durum": durum, "bilgi": bilgi[:300]}))
    bildirim_hata = 0
    for satir in report.messages:
        hata = _hata_mi(satir)
        bildirim_hata += 1 if hata else 0
        out.append(("error" if hata else "info",
                    {"olay": "bildirim", "kanal": _kanal(satir), "durum": "hata" if hata else "tamam",
                     "mesaj": satir[:400]}))
    for not_ in report.notes:
        out.append(("error" if _hata_mi(not_) else "info", {"olay": "not", "mesaj": not_[:400]}))
    for degisim in report.status_changes:
        out.append(("info", {"olay": "durum", "mesaj": degisim[:400]}))
    out.append(("error" if (kaynak_hata or bildirim_hata) else "info", {
        "olay": "tur", "durum": "tamam", "sure_sn": round(sure_sn, 1),
        "kaynak": len(report.sources), "kaynak_hata": kaynak_hata,
        "bildirim_hata": bildirim_hata, "yeni_kayit": report.new_events,
        "aday": report.candidates, "yazilan": len(report.written), "ilk_calisma": report.first_run,
    }))
    return out


def gonder(cfg, report, sure_sn: float, client: httpx.Client | None = None) -> str | None:
    """Kayıtları Loki'ye yazar. Ayar yoksa None; başarı/hata kısa not döndürür, asla istisna atmaz."""
    url, user, token = _ayar()
    if not (url and user and token):
        return None
    ortam = "github" if os.environ.get("GITHUB_ACTIONS") else "yerel"
    ns = time.time_ns()
    akimlar: dict[str, list[list[str]]] = {}
    try:
        for i, (seviye, olay) in enumerate(kayitlar(report, sure_sn)):
            satir = redact(json.dumps(olay, ensure_ascii=False), cfg.settings)
            akimlar.setdefault(seviye, []).append([str(ns + i), satir])
        govde = {"streams": [{"stream": {"app": APP, "ortam": ortam, "level": seviye}, "values": degerler}
                             for seviye, degerler in akimlar.items()]}
        own = client is None
        client = client or httpx.Client(timeout=10)
        try:
            r = client.post(url, json=govde, auth=(user, token))
            r.raise_for_status()
        finally:
            if own:
                client.close()
        return f"İzleme: {sum(len(v) for v in akimlar.values())} kayıt Grafana'ya gönderildi."
    except Exception as exc:  # izleme hatası radar turunu asla durdurmaz
        return f"İzleme: Grafana'ya gönderilemedi ({redact(exc, cfg.settings)[:200]})"
