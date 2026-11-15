"""İzleme: her radar turunun yapılandırılmış kayıtlarını Grafana Cloud'a (Loki) gönderir.

Gönderilen her satır tek bir JSON olaydır: tur özeti, kaynak kontrolleri, bildirim
sonuçları ve notlar. Grafana bu kayıtlardan durum ekranını çizer ve alarm üretir
(ör. "90 dakikadır tur yok", "e-posta gönderilemiyor", "kaynak okunamıyor", "tur çöktü").

Ayarlar .env/ortamdan gelir; LOKI_URL boşsa (ya da https değilse) izleme kapalıdır ve
radarın çalışmasını hiçbir biçimde etkilemez. Her alan JSON'a çevrilmeden önce
guvenlik.redact ile gizli bilgilerden arındırılır; e-posta adresleri ayrıca maskelenir.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time

import httpx

from .guvenlik import MASK, redact

APP = "tarife-radari"

# Ayarlarda tanımlı olmayan e-posta adresleri de Loki'ye gitmesin (ör. bir SMTP hata mesajındaki adres)
_EPOSTA = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")

# Satırın girişinde bu sözcüklerden biri varsa işlem başarısız sayılır
_HATA_SOZCUKLERI = ("gönderilemedi", "bildirilemedi", "alınamadı", "yapılamadı", "okunamadı",
                    "indirilemedi", "bırakıldı")


def _ayar() -> tuple[str, str, str]:
    url = os.environ.get("LOKI_URL", "").strip()
    if url and not url.rstrip("/").endswith("/loki/api/v1/push"):
        url = url.rstrip("/") + "/loki/api/v1/push"
    return url, os.environ.get("LOKI_USER", "").strip(), os.environ.get("LOKI_TOKEN", "").strip()


def _https(url: str) -> bool:
    # Basic Auth şifresiz bağlantıda açık metin gider; yalnızca https kabul edilir
    return url.lower().startswith("https://")


def aktif() -> bool:
    url, user, token = _ayar()
    return bool(url and user and token and _https(url))


def tetik() -> str:
    """Turu neyin başlattığı: dış zamanlayıcı, elle, GitHub cron'u ya da yerel çalıştırma."""
    return (os.environ.get("RADAR_TETIK", "").strip() or os.environ.get("GITHUB_EVENT_NAME", "").strip()
            or "yerel")


def kaynak_kullanimi() -> dict:
    """Bu sürecin harcadığı CPU süresi ve en yüksek bellek kullanımı."""
    t = os.times()
    out: dict = {"cpu_sn": round(t.user + t.system, 1)}
    try:
        import resource  # Windows'ta yok
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        out["bellek_mb"] = round(rss / (1024 * 1024 if sys.platform == "darwin" else 1024), 1)
    except Exception:
        pass
    return out


def _bas(satir: str) -> str:
    return satir.split(":", 1)[0].lower()


def _kanal(satir: str) -> str:
    # Yalnızca satırın girişine bakılır: konu metnindeki kanal adları yanıltmasın
    bas = _bas(satir)
    if "(email)" in bas:
        return "email"
    if "(telegram)" in bas or "(tech)" in bas:
        return "telegram"
    for ad, anahtarlar in (("whatsapp", ("whatsapp",)), ("telegram", ("telegram",)), ("email", ("e-posta", "email"))):
        if any(a in bas for a in anahtarlar):
            return ad
    return "diger"


def _hata_mi(satir: str) -> bool:
    # Yalnızca satırın girişine bakılır; bildirim konusundaki "HATASI" gibi sözcükler yanıltmasın
    bas = _bas(satir)
    return any(k in bas for k in _HATA_SOZCUKLERI)


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
    if not kaynak_hata:
        durum = "tamam"
    elif kaynak_hata < len(report.sources):
        durum = "kismi"
    else:
        durum = "hata"
    out.append(("error" if (kaynak_hata or bildirim_hata) else "info", {
        "olay": "tur", "durum": durum, "sure_sn": round(sure_sn, 1), "tetik": tetik(),
        "kaynak": len(report.sources), "kaynak_hata": kaynak_hata,
        "bildirim_hata": bildirim_hata, "yeni_kayit": report.new_events,
        "aday": report.candidates, "yazilan": len(report.written), "ilk_calisma": report.first_run,
        **kaynak_kullanimi(),
    }))
    return out


def _temizle(deger, settings):
    """Bir alanı JSON'a çevrilmeden önce maskeler (kaçışlanmış karakterler maskeyi atlatamasın)."""
    if isinstance(deger, str):
        return _EPOSTA.sub(MASK, redact(deger, settings))
    return deger


def _yaz(cfg, olaylar: list[tuple[str, dict]], client: httpx.Client | None) -> str | None:
    """Olayları Loki'ye yazar. Ayar yoksa None; başarı/hata kısa not döndürür, asla istisna atmaz."""
    url, user, token = _ayar()
    if not (url and user and token):
        return None
    if not _https(url):
        return "İzleme: LOKI_URL https ile başlamıyor; kayıtlar gönderilmedi."
    ortam = "github" if os.environ.get("GITHUB_ACTIONS") else "yerel"
    ns = time.time_ns()
    akimlar: dict[str, list[list[str]]] = {}
    try:
        for i, (seviye, olay) in enumerate(olaylar):
            temiz = {k: _temizle(v, cfg.settings) for k, v in olay.items()}
            akimlar.setdefault(seviye, []).append([str(ns + i), json.dumps(temiz, ensure_ascii=False)])
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


def gonder(cfg, report, sure_sn: float, client: httpx.Client | None = None) -> str | None:
    """Turun kayıtlarını Loki'ye yazar."""
    try:
        olaylar = kayitlar(report, sure_sn)
    except Exception as exc:
        return f"İzleme: kayıtlar hazırlanamadı ({redact(exc, cfg.settings)[:200]})"
    return _yaz(cfg, olaylar, client)


def cokme(cfg, exc: BaseException, sure_sn: float, client: httpx.Client | None = None) -> str | None:
    """Tur yarıda kesilince tek bir "coktu" kaydı gönderir; Grafana bunu hemen alarma çevirir."""
    olay = {"olay": "tur", "durum": "coktu", "sure_sn": round(sure_sn, 1), "tetik": tetik(),
            "hata": f"{type(exc).__name__}: {exc}"[:500], **kaynak_kullanimi()}
    return _yaz(cfg, [("error", olay)], client)
