"""E-posta gövdeleri: radar/eposta_sablon/ içindeki tasarım şablonlarını doldurur.

Şablonlar tasarımcının dosyalarıdır ve olduğu gibi kullanılır; burada yalnızca {{alan}} yerleri doldurulur,
"TEKRAR" blokları satır sayısınca çoğaltılır ve verisi olmayan bölümler çıkarılır.

"Sayı", "Tarih" ve panel bağlantısı gönderim anında bitir() ile yazılır: e-posta bir turda gidemeyip
sonraki turda gönderilirse numara ve tarih gönderildiği anı gösterir.
"""

from __future__ import annotations

import html
import re
from datetime import datetime, timedelta
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from .config import Config
from .guvenlik import safe_url
from .matching import KIND_FREE
from .messages import FLAG_NOTES, money
from .models import STATUS_LABELS
from .timeutil import MONTHS_TR, aware, days_until, fmt_date, from_iso

SABLONLAR = Path(__file__).parent / "eposta_sablon"
GUNLER = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
SINIF_NOTU = "Ücretler 1. sınıf (otomobil) araçlar içindir. Diğer sınıflar paneldedir."
SINIF_ALT = "1. sınıf (otomobil)"
CIZGI = "border-top:1px solid #e1e8e4;"
IMZA_URL = "https://metinakdas.github.io/otoyol-ucretleri/"  # şablondaki imza bağlantısı; panel adresiyle değiştirilir
KURUMLAR = {
    "kgm.gov.tr": "Karayolları Genel Müdürlüğü",
    "uab.gov.tr": "Ulaştırma ve Altyapı Bakanlığı",
    "avrasyatuneli.com": "Avrasya Tüneli",
}
# 08 şablonundaki not: liste boşsa yerine bu bileşen gelir (tasarımın örnek dosyasından aynen alındı)
BOS_DURUM = (
    "\n<!-- ▼ BİLEŞEN: bos_durum -->\n"
    '<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="border-collapse:separate;">'
    '<tr><td bgcolor="#f2f5f3" class="ob-bg-soft ob-c-muted" style="background-color:#f2f5f3;border-radius:10px;'
    "padding:14px 16px;font-family:Inter,'Segoe UI',Arial,sans-serif;font-size:14px;line-height:21px;color:#5f716b;\">"
    "{{bos_metin}}</td></tr></table>\n"
    "<!-- ▲ BİLEŞEN: bos_durum -->\n\n"
)


class Ham(str):
    """Kaçışsız yazılacak (önceden güvenli hâle getirilmiş) HTML."""


# --------------------------------------------------------------------------- şablon motoru

@lru_cache(maxsize=None)
def sablon(ad: str) -> str:
    return next(SABLONLAR.glob(f"{ad}-*.html")).read_text(encoding="utf-8")


def _deger(v) -> str:
    if isinstance(v, Ham):
        return str(v)
    # Değer içinde "{{" kalırsa sonraki doldurma onu alan sanmasın
    return html.escape("" if v is None else str(v), quote=True).replace("{{", "{&#123;")


def doldur(t: str, degerler: dict) -> str:
    for k, v in degerler.items():
        t = t.replace("{{" + k + "}}", _deger(v))
    return t


def _tekrar_deseni(ad: str) -> re.Pattern:
    return re.compile(rf"(<!-- ▼ TEKRAR: {ad} -->\n?)(.*?)(<!-- ▲ TEKRAR: {ad} -->)", re.S)


def tekrarla(t: str, ad: str, listeler: list[list[dict]]) -> str:
    """Adı geçen TEKRAR bloklarını (şablondaki sırayla) verilen satırlarla çoğaltır."""
    sira = iter(listeler)

    def satirlar(m: re.Match) -> str:
        ic, out = m.group(2), []
        for i, satir in enumerate(next(sira)):
            r = ic
            if i:  # ikinci satırdan itibaren üstte ince çizgi (tasarımın örnek dosyalarındaki gibi)
                r = re.sub(r"(padding:12px 0(?: 12px 12px)?;)(?!border-top)", r"\1" + CIZGI, r)
            r = r.replace(">1.</td>", f">{i + 1}.</td>")  # numaralı adımlar
            out.append(doldur(r, satir))
        return m.group(1) + "".join(out) + m.group(3)

    return _tekrar_deseni(ad).sub(satirlar, t)


def _bolum(t: str, isaret: str) -> tuple[int, int] | None:
    """İşareti içeren gövde bölümünün (<tr><td style="padding:…">…</td></tr>) sınırları."""
    i = t.find(isaret)
    if i < 0:
        return None
    bas = t.rfind('<tr><td style="padding:', 0, i)
    sonlar = [x for x in (t.find('<tr><td style="padding:', i), t.find("<!-- ▼ BİLEŞEN: kapanis_ve_imza", i)) if x >= 0]
    son = min(sonlar)
    # Bölüm "</td></tr>" ile biter; sonrasındaki boşluk/yorum bir sonraki bölüme aittir
    son = t.rfind("</td></tr>", bas, son) + len("</td></tr>")
    return bas, son


def bolum_sil(t: str, isaret: str) -> str:
    sinir = _bolum(t, isaret)
    return t if sinir is None else t[:sinir[0]] + t[sinir[1]:]


def bos_liste(t: str, sira: int, metin: str) -> str:
    """sira'ncı liste_satiri tablosunu "boş durum" kutusuyla değiştirir."""
    desen = re.compile(r'<table role="presentation"[^>]*>\n<!-- ▼ TEKRAR: liste_satiri -->.*?<!-- ▲ TEKRAR: liste_satiri -->\n</table>\n', re.S)
    eslesmeler = list(desen.finditer(t))
    m = eslesmeler[sira]
    return t[:m.start()] + doldur(BOS_DURUM, {"bos_metin": metin}) + t[m.end():]


def sayac_yaz(t: str, baslik: str, sayi: int) -> str:
    i = t.find(f">{baslik} <span")
    j = t.find("(1)</span>", i)
    return t[:j] + f"({sayi})</span>" + t[j + len("(1)</span>"):]


def rozet_yaz(t: str, eski: str, yeni: str) -> str:
    i = t.find("<!-- ▼ BİLEŞEN: durum_rozeti -->")
    j = t.find(f">{eski}</td>", i)
    return t[:j] + f">{_deger(yeni)}</td>" + t[j + len(eski) + 6:]


def bitir(t: str, *, ref: str, tarih: datetime, panel_url: str | None) -> str:
    """Gönderim anında: sayı, tarih ve panel bağlantısı."""
    t = doldur(t, {"referans_no": ref or "—", "tarih": uzun(tarih)})
    url = safe_url(panel_url)
    if url:
        gorunen = re.sub(r"^https?://", "", url).rstrip("/")
        t = doldur(t, {"panel_url": url})
        t = t.replace(f'href="{IMZA_URL}"', f'href="{_deger(url)}"').replace(
            f">{IMZA_URL[8:].rstrip('/')}</a>", f">{_deger(gorunen)}</a>")
    else:
        t = bolum_sil(t, "<!-- ▼ BİLEŞEN: dugme -->")
        t = re.sub(rf'<p [^>]*><a href="{re.escape(IMZA_URL)}"[^>]*>[^<]*</a></p>\n', "", t)
    return t


# --------------------------------------------------------------------------- biçimler

def uzun(dt: datetime | None) -> str:
    """15 Kasım 2026 Pazar, 10:30"""
    if dt is None:
        return "Belirsiz"
    dt = aware(dt)
    return f"{dt.day} {MONTHS_TR[dt.month - 1]} {dt.year} {GUNLER[dt.weekday()]}, {dt:%H:%M}"


def kisa(dt: datetime | None) -> str:
    """1 Ocak 2027, 00:00"""
    if dt is None:
        return "Belirsiz"
    dt = aware(dt)
    return f"{fmt_date(dt)}, {dt:%H:%M}"


def tarih_saat(dt: datetime) -> str:
    """1 Ocak 2027 Cuma 00:00 (önizleme metni)"""
    dt = aware(dt)
    return f"{dt.day} {MONTHS_TR[dt.month - 1]} {dt.year} {GUNLER[dt.weekday()]} {dt:%H:%M}"


def aralik(bas: datetime, son: datetime) -> str:
    """9–15 Kasım 2026 · 30 Kasım – 6 Aralık 2026 · 28 Aralık 2026 – 3 Ocak 2027"""
    if bas.year != son.year:
        return f"{fmt_date(bas)} – {fmt_date(son)}"
    if bas.month != son.month:
        return f"{bas.day} {MONTHS_TR[bas.month - 1]} – {fmt_date(son)}"
    return f"{bas.day}–{fmt_date(son)}"


def haftalik_donem(now: datetime) -> str:
    """Haftalık özet pazartesi gider ve bir önceki haftayı (pazartesi–pazar) özetler."""
    pazartesi = now - timedelta(days=now.weekday() + 7)
    return aralik(pazartesi, pazartesi + timedelta(days=6))


def kalan(eff: datetime | None, now: datetime) -> str:
    if eff is None:
        return "—"
    d = days_until(eff, now)
    if d > 1:
        return f"{d} gün"
    return {1: "Yarın", 0: "Bugün"}.get(d, "Yürürlükte")


def once(eff: datetime, now: datetime) -> str:
    d = -days_until(eff, now)
    return {0: "Bugün", 1: "Dün"}.get(d, f"{d} gün önce")


def degisim(old, new) -> str:
    if old is None or new is None or Decimal(str(old)) == 0:
        return "—"
    pct = ((Decimal(str(new)) - Decimal(str(old))) / Decimal(str(old)) * 100).quantize(Decimal("0.1"))
    isaret = "+" if pct > 0 else "−" if pct < 0 else ""
    return f"{isaret}%{abs(pct)}".replace(".", ",")


def sure(delta: timedelta, uzun_bicim: bool = False) -> str:
    """8 sa 15 dk · 8 saat 15 dakika"""
    dk = max(0, int(delta.total_seconds() // 60))
    gun, saat, dakika = dk // 1440, dk % 1440 // 60, dk % 60
    adlar = ("gün", "saat", "dakika") if uzun_bicim else ("gün", "sa", "dk")
    parca = [f"{n} {a}" for n, a in zip((gun, saat, dakika), adlar) if n]
    return " ".join(parca[:2]) or f"0 {adlar[2]}"


def sure_ekli(delta: timedelta) -> str:
    """8 saat 15 dakikadır · 2 gün 3 saattir · 1 gündür"""
    s = sure(delta, True)
    return s + {"dakika": "dır", "saat": "tir", "gün": "dür"}[s.rsplit(" ", 1)[1]]


def utc(deger: str) -> str:
    """UTC-04:00 → UTC−04:00 (tasarımdaki eksi işareti)"""
    return deger.replace("UTC-", "UTC−")


def eski_yeni(old, new) -> str:
    """52,00 → 66,50 TL"""
    if old is None:
        return money(new)
    return f"{money(old)[:-3]} → {money(new)}"


# --------------------------------------------------------------------------- olaydan alanlar

def _fiyatlar(cfg: Config, ev: dict) -> list[tuple[str, object, object]]:
    out = []
    for cid, change in (ev.get("prices") or {}).items():
        new = (change.get("new") or {}).get("1")
        old = (change.get("old") or {}).get("1")
        if new is not None:
            out.append((cfg.crossing_name(cid), old, new))
    return out


def _ucret_satirlari(cfg: Config, ev: dict) -> list[dict]:
    rows = [{"gecis": ad, "eski": money(old) if old is not None else "—", "yeni": money(new), "degisim": degisim(old, new)}
            for ad, old, new in _fiyatlar(cfg, ev)]
    if not rows:  # ücretler okunamadıysa geçişler yine listelenir
        rows = [{"gecis": cfg.crossing_name(c), "eski": "—", "yeni": "—", "degisim": "—"} for c in ev.get("crossings") or []]
    return rows


def _sinif_notu(cfg: Config, ev: dict) -> str:
    belge = len(ev.get("documents") or [])
    if belge and belge > len(_fiyatlar(cfg, ev)):
        return f"{SINIF_NOTU} Değişen tarife belgesi: {belge}; tümü paneldedir."
    return SINIF_NOTU


def _notlar(ev: dict) -> str:
    return " ".join(FLAG_NOTES[f] for f in ev.get("flags", []) if f in FLAG_NOTES)


def _ekle(metin: str, ek: str) -> str:
    return f"{metin} {ek}".strip() if ek else metin


def _kaynak(ev: dict) -> tuple[str, str] | None:
    if not ev.get("evidence"):
        return None
    son = ev["evidence"][-1]
    url = safe_url(son.get("url"))
    if not url:
        return None
    alan = (urlsplit(url).hostname or "").removeprefix("www.")
    ad = next((v for k, v in KURUMLAR.items() if alan == k or alan.endswith("." + k)), None)
    return ad or son.get("publisher") or alan, url


def _adlar(cfg: Config, ids: list[str]) -> list[str]:
    return [cfg.crossing_name(i) for i in ids or []]


def _kisa_liste(adlar: list[str], n: int = 2) -> str:
    """A · A ve B · A, B ve C · A, B ve 3 geçiş daha"""
    if len(adlar) > n:
        return ", ".join(adlar[:n]) + f" ve {len(adlar) - n} geçiş daha"
    return " ve ".join(filter(None, [", ".join(adlar[:-1]), adlar[-1] if adlar else ""]))


def _ortak(t: str, *, konu: str, onizleme: str, baslik: str, giris) -> str:
    return doldur(t, {"konu": konu, "onizleme": onizleme, "baslik": baslik, "giris": giris})


def _kaynak_yaz(t: str, ev: dict) -> str:
    k = _kaynak(ev)
    if k is None:
        return bolum_sil(t, 'Kaynak: <a href="{{kaynak_url}}"')
    return doldur(t, {"kaynak": k[0], "kaynak_url": k[1]})


def _bildirim_tarihi(bildirim: datetime | None, varsayilan: str) -> str:
    return f"{fmt_date(bildirim)} tarihli bildirimimizde yer alan" if bildirim else varsayilan


# --------------------------------------------------------------------------- bildirim türleri

def karar(cfg: Config, ev: dict, now: datetime) -> str:
    """01 karar çıktı · 02 acil (kaçırıldı) · 05 ücretsiz geçiş"""
    if ev["kind"] == KIND_FREE:
        return _ucretsiz(cfg, ev, now)
    eff = from_iso(ev.get("effective_from"))
    fiyat = _fiyatlar(cfg, ev)
    if "kacirildi" in ev.get("flags", []):
        return _acil(cfg, ev, now, eff, fiyat)
    t = sablon("01")
    on = ", ".join(f"{ad} {money(new)}" for ad, _, new in fiyat[:2])
    gecerli = f"Yeni ücretler {fmt_date(eff)} {eff:%H:%M} itibarıyla geçerli." if eff else "Yürürlük tarihi henüz açıklanmadı."
    kaynak = _kaynak(ev)
    giris = (f"{kaynak[0]} tarafından yayımlanan karar ile" if kaynak else "Yayımlanan karar ile") + \
        " aşağıdaki geçişlerin ücretleri yeniden belirlenmiştir."
    t = _ortak(t, konu=ev["title"], onizleme=(f"{on}. " if on else "") + gecerli,
               baslik=f"Yeni geçiş ücretleri {fmt_date(eff)} tarihinde yürürlüğe giriyor" if eff else "Yeni geçiş ücretleri belirlendi",
               giris=_ekle(giris, _notlar(ev)))
    t = doldur(t, {"yururluk": uzun(eff), "kalan": kalan(eff, now), "sinif_notu": _sinif_notu(cfg, ev)})
    t = tekrarla(t, "ucret_satiri", [_ucret_satirlari(cfg, ev)])
    return _kaynak_yaz(t, ev)


def _acil(cfg: Config, ev: dict, now: datetime, eff: datetime | None, fiyat: list) -> str:
    t = sablon("02")
    gecikme = (now - eff) if eff else timedelta(0)
    adlar = [ad for ad, _, _ in fiyat] or _adlar(cfg, ev.get("crossings"))
    tek = len(adlar) == 1
    ozne = f"{adlar[0]} yeni ücreti" if tek else "Yeni ücretler"
    t = _ortak(
        t, konu=f"{ev['title']} bildirimden önce yürürlüğe girdi",
        onizleme=(f"{ozne} {fmt_date(eff)} {eff:%H:%M} itibarıyla uygulanıyor. " if eff else f"{ozne} uygulanıyor. ")
        + f"Bildirim {sure(gecikme, True)} gecikti.",
        baslik=f"{ozne} {sure_ekli(gecikme)} uygulanıyor" if eff else f"{ozne} uygulanıyor",
        giris=_ekle("Aşağıdaki ücret değişikliği yürürlük anından sonra tespit edilmiştir. Bu süre içinde yapılan "
                    "geçişler yeni ücretten ücretlendirilmiş olabilir.", _notlar(ev)))
    t = doldur(t, {"durum_bandi": "Yürürlük anı geçmiş; ilgili taksimetreleri hemen kontrol edin.",
                   "yururluk": kisa(eff), "tespit": kisa(now), "gecikme": sure(gecikme),
                   "sinif_notu": _sinif_notu(cfg, ev)})
    t = tekrarla(t, "liste_satiri", [[{}]])
    t = tekrarla(t, "ucret_satiri", [_ucret_satirlari(cfg, ev)])
    hedef = f"{adlar[0]} tutarını" if tek else "değişen geçişlerin tutarlarını"
    saat = f"{eff:%H:%M}" if eff and gecikme < timedelta(days=1) else "Yürürlük anı"
    t = tekrarla(t, "adim", [[
        {"adimlar": f"Taksimetre ve ücret tablolarındaki {hedef} güncelleyin."},
        {"adimlar": f"{saat} ile bildirim saati arasındaki geçişlerin ücretlendirmesini kontrol edin."},
    ]])
    return _kaynak_yaz(t, ev)


def _ucretsiz(cfg: Config, ev: dict, now: datetime) -> str:
    t = sablon("05")
    bas, son = from_iso(ev.get("effective_from")), from_iso(ev.get("effective_to"))
    kapsam, disi = _adlar(cfg, ev.get("crossings")), _adlar(cfg, ev.get("excluded"))
    bayram = "bayram" in ev["title"].lower()
    t = _ortak(
        t, konu=ev["title"],
        onizleme=f"{ev['title']}: {_kisa_liste(kapsam, 3)} ücretsiz." if kapsam else f"{ev['title']}.",
        baslik="Bayram süresince seçili köprü ve otoyollar ücretsiz" if bayram else "Belirtilen süre boyunca seçili geçişler ücretsiz",
        giris="Aşağıda belirtilen tarih ve saatler arasında ücretsiz geçiş uygulanacaktır.")
    t = doldur(t, {"baslangic": uzun(bas), "bitis": uzun(son)})
    if not disi:
        t = bolum_sil(t, ">Kapsam dışı geçişler</p>")
    t = tekrarla(t, "liste_satiri", [[{"kapsamda": a} for a in kapsam or ["Kaynakta belirtilen geçişler"]]]
                 + ([[{"kapsam_disi": a} for a in disi]] if disi else []))
    not_ = _ekle("Kapsam dışındaki geçişlerde olağan ücretler uygulanır." if disi else "", _notlar(ev))
    t = doldur(t, {"not": not_}) if not_ else bolum_sil(t, "{{not}}")
    return _kaynak_yaz(t, ev)


def hatirlatma(cfg: Config, ev: dict, days: int, now: datetime, bildirim: datetime | None = None) -> str:
    """03 hatırlatma"""
    t = sablon("03")
    eff = from_iso(ev.get("effective_from"))
    ucretsiz = ev["kind"] == KIND_FREE
    yarin = days <= 1
    if ucretsiz:
        konu = "Ücretsiz geçiş uygulaması yarın başlıyor" if yarin else f"Ücretsiz geçiş uygulamasının başlamasına {days} gün kaldı"
        baslik = "Ücretsiz geçiş yarın başlıyor" if yarin else f"Ücretsiz geçiş {days} gün sonra başlıyor"
        konu_adi = "ücretsiz geçiş uygulamasının başlangıç tarihi yaklaşmaktadır."
    else:
        konu = "Yeni geçiş ücretleri yarın yürürlüğe giriyor" if yarin else f"Yeni geçiş ücretlerinin yürürlüğe girmesine {days} gün kaldı"
        baslik = "Yeni ücretler yarın yürürlükte" if yarin else f"Yeni ücretler {days} gün sonra geçerli"
        konu_adi = "ücret değişikliklerinin yürürlük tarihi yaklaşmaktadır."
    if yarin and eff and not ucretsiz:
        giris = (_bildirim_tarihi(bildirim, "Daha önce bildirilen") + " ücret değişiklikleri yarın saat "
                 f"{eff:%H:%M} itibarıyla uygulanmaya başlayacaktır.")
        onizleme = f"Yeni geçiş ücretleri yarın, {tarih_saat(eff)} itibarıyla uygulanmaya başlıyor."
    else:
        giris = _bildirim_tarihi(bildirim, "Daha önce bildirilen") + " " + konu_adi
        ne = "Ücretsiz geçiş" if ucretsiz else "Yeni geçiş ücretleri"
        onizleme = (f"{ne} {tarih_saat(eff)} itibarıyla geçerli. " if eff else "") + ("Yarın." if yarin else f"{days} gün kaldı.")
    t = _ortak(t, konu=konu, onizleme=onizleme, baslik=baslik, giris=_ekle(giris, _notlar(ev)))
    t = doldur(t, {"yururluk": uzun(eff), "sayac_etiket": "Kalan süre", "sayac": "Yarın" if yarin else f"{days} gün",
                   "sinif_notu": _sinif_notu(cfg, ev)})
    if ucretsiz:
        return bolum_sil(t, "<!-- ▼ BİLEŞEN: ucret_tablosu -->")
    return tekrarla(t, "ucret_satiri", [_ucret_satirlari(cfg, ev)])


def yururluk(cfg: Config, ev: dict, now: datetime, bildirim: datetime | None = None) -> str:
    """04 yürürlüğe girdi"""
    t = sablon("04")
    eff = from_iso(ev.get("effective_from"))
    bugun = eff is None or days_until(eff, now) == 0
    ucretsiz = ev["kind"] == KIND_FREE
    zaman = "bugün itibarıyla" if bugun else f"{fmt_date(eff)} itibarıyla"
    t = _ortak(
        t, konu=f"{ev['title']} yürürlüğe girdi",
        onizleme=f"{ev['title']} bugün {eff:%H:%M} itibarıyla uygulanıyor." if bugun and eff
        else f"{ev['title']} {zaman} uygulanıyor.",
        baslik=f"Ücretsiz geçiş {zaman} uygulanıyor" if ucretsiz else f"Yeni ücretler {zaman} uygulanıyor",
        giris=_ekle((f"{fmt_date(bildirim)} tarihinde bildirilen" if bildirim else "Daha önce bildirilen")
                    + (" ücretsiz geçiş uygulaması başlamıştır." if ucretsiz else " geçiş ücretleri yürürlüğe girmiştir."),
                    _notlar(ev)))
    t = doldur(t, {"rozet": "YÜRÜRLÜĞE GİRDİ", "yururluk": uzun(eff),
                   "durum": "Ücretsiz geçiş" if ucretsiz else "Uygulanıyor", "sinif_notu": _sinif_notu(cfg, ev)})
    if ucretsiz:
        return bolum_sil(t, "<!-- ▼ BİLEŞEN: ucret_tablosu -->")
    return tekrarla(t, "ucret_satiri", [_ucret_satirlari(cfg, ev)])


def _gecis_satirlari(cfg: Config, ev: dict) -> list[dict]:
    if ev["kind"] == KIND_FREE:
        return [{"gecis": a, "gecis_alt": "Ücretsiz geçiş", "ucret": "Ücretsiz"} for a in _adlar(cfg, ev.get("crossings"))]
    rows = [{"gecis": ad, "gecis_alt": SINIF_ALT, "ucret": eski_yeni(old, new)} for ad, old, new in _fiyatlar(cfg, ev)]
    return rows or [{"gecis": a, "gecis_alt": SINIF_ALT, "ucret": "—"} for a in _adlar(cfg, ev.get("crossings"))]


def tarih_degisti(cfg: Config, ev: dict, now: datetime) -> str:
    """06a tarih değişti"""
    t = sablon("06a")
    eff = from_iso(ev.get("effective_from"))
    onceki = from_iso(ev.get("onceki_yururluk"))
    ne = "ücretsiz geçiş uygulamasının" if ev["kind"] == KIND_FREE else "ücret değişikliğinin"
    t = _ortak(
        t, konu=f"{ev['title']}: yürürlük tarihi değişti",
        onizleme=f"{ev['title']} " + (f"{onceki.day} {MONTHS_TR[onceki.month - 1]} yerine " if onceki else "")
        + f"{fmt_date(eff)} tarihinde yürürlüğe girecek.",
        baslik=f"Yürürlük tarihi {fmt_date(eff)} olarak güncellendi",
        giris=_ekle(f"Daha önce bildirilen {ne} yürürlük tarihi değiştirilmiştir.", _notlar(ev)))
    t = doldur(t, {"eski_tarih": kisa(onceki) if onceki else "—", "yeni_tarih": uzun(eff)})
    rows = _gecis_satirlari(cfg, ev)
    return tekrarla(t, "liste_satiri", [rows]) if rows else bolum_sil(t, "<!-- ▼ TEKRAR: liste_satiri -->")


def iptal(cfg: Config, ev: dict, now: datetime, bildirim: datetime | None = None) -> str:
    """06b iptal / ertelendi"""
    t = sablon("06b")
    eff = from_iso(ev.get("effective_from"))
    baslik_l = ev["title"].lower()
    ertelendi = "ertele" in baslik_l and "iptal" not in baslik_l
    rozet = "ERTELENDİ" if ertelendi else "İPTAL EDİLDİ" if "iptal" in baslik_l else "İPTAL / ERTELENDİ"
    fiil = "ertelendi" if ertelendi else "iptal edildi" if "iptal" in baslik_l else "iptal edildi ya da ertelendi"
    ucretsiz = ev["kind"] == KIND_FREE
    ne = "Ücretsiz geçiş uygulaması" if ucretsiz else "Ücret değişikliği"
    fiyat = _fiyatlar(cfg, ev)
    if ucretsiz:
        mevcut = "Olağan ücretler"
    elif len(fiyat) == 1 and fiyat[0][1] is not None:
        mevcut = money(fiyat[0][1])
    else:
        mevcut = "Değişmedi"
    zaman = f"{fmt_date(eff)} tarihinde y" if eff else "Y"
    fiil_resmi = fiil.replace("edildi", "edilmiştir").replace("ertelendi", "ertelenmiştir")
    konu = ev["title"] if fiil.split()[0] in baslik_l else f"{ev['title']}: {fiil}"  # başlık zaten söylüyorsa yinelenmez
    t = _ortak(
        t, konu=konu,
        onizleme=f"{konu}. " + ("Olağan ücretler geçerli." if ucretsiz else "Mevcut ücret geçerli."),
        baslik=f"{'Uygulama' if ucretsiz else 'Değişiklik'} {fiil}; mevcut ücret geçerliliğini koruyor",
        giris=_ekle(f"{zaman}ürürlüğe gireceği bildirilen {ne.lower()} {fiil_resmi}. "
                    "Yeni tarih açıklandığında ayrıca bildirilecektir.", _notlar(ev)))
    t = doldur(t, {"rozet": rozet, "mevcut": mevcut, "yeni_tarih": "Açıklanmadı"})
    rows = [{"gecis": r["gecis"], "gecis_alt": r["gecis_alt"]} for r in _gecis_satirlari(cfg, ev)]
    return tekrarla(t, "liste_satiri", [rows]) if rows else bolum_sil(t, "<!-- ▼ TEKRAR: liste_satiri -->")


def sona_erdi(cfg: Config, ev: dict, now: datetime, bildirim: datetime | None = None) -> str:
    """06c sona erdi (ücretsiz geçiş bitti)"""
    t = sablon("06c")
    son = from_iso(ev.get("effective_to"))
    olagan = (son + timedelta(minutes=1)).replace(second=0, microsecond=0) if son and son.minute == 59 else son
    t = _ortak(
        t, konu=f"{ev['title']} sona erdi",
        onizleme=f"{ev['title']} " + (f"{fmt_date(son)} {son:%H:%M} itibarıyla " if son else "") + "sona erdi.",
        baslik="Olağan ücretler yeniden uygulanıyor",
        giris=_bildirim_tarihi(bildirim, "Daha önce bildirilen") + " ücretsiz geçiş uygulaması sona ermiştir.")
    return doldur(t, {"bitis": kisa(son), "olagan": kisa(olagan)})


def saat_dilimi(b: dict, ulke_adlari: dict[str, str], kaynak_url: str) -> str:
    """07 saat dilimi değişti. b: saat_dilimi._bildirim() kaydı."""
    from .saat_dilimi import utc as utc_yaz

    t = sablon("07")
    farklar = b.get("farklar") or []
    ulkeler = list(dict.fromkeys(ulke_adlari.get(f["cc"], f["cc"]) for f in farklar))
    iana = b.get("iana") or ""
    satirlar = []
    for f in farklar:
        tarih = f.get("tarih")
        if tarih and " " in tarih:  # "1 Ocak 2027 00:00" → "1 Ocak 2027, 00:00"
            g, s = tarih.rsplit(" ", 1)
            tarih = f"{g}, {s}"
        satirlar.append({"ulke": ulke_adlari.get(f["cc"], f["cc"]), "bolge": f["zone"],
                         "eski": utc(utc_yaz(f["eski"])) if f.get("eski") is not None else "—",
                         "yeni": utc(utc_yaz(f["yeni"])),
                         "yururluk": f"{tarih} (yerel saat)" if tarih else "Hemen (yerel saat)"})
    if len(farklar) == 1 and farklar[0].get("eski") is not None:
        f = satirlar[0]
        onizleme = f"IANA tzdata {iana}: {f['ulke']} {f['eski']} yerine {f['yeni']} kullanacak."
    else:
        onizleme = f"IANA tzdata {iana}: {len(ulkeler)} ülkenin saat farkı değişti."
    t = _ortak(t, konu=f"IANA tzdata {iana}: saat farkı değişen ülkeler", onizleme=onizleme,
               baslik=f"{len(ulkeler)} ülkenin saat farkı değişti",
               giris=f"IANA saat dilimi veritabanının {iana} sürümünde aşağıdaki ülkelerin UTC farkı değiştirilmiştir.")
    t = tekrarla(t, "saat_dilimi_satiri", [satirlar])
    return doldur(t, {"kaynak": f"IANA Time Zone Database, {iana} sürüm notları", "kaynak_url": kaynak_url})


def ozet(cfg: Config, events: dict, problems: list[str], now: datetime, haftalik: bool,
         izleme: dict | None = None) -> str:
    """08 haftalık özet (günlük özet de aynı tasarımla). izleme: izleme_ozeti() çıktısı."""
    izleme = izleme or {}
    # Tasarımcının şablondaki notu e-postaya girmez (örnek dosyada da yok)
    t = re.sub(r"<!-- NOT: .*?-->\n?", "", sablon("08"), flags=re.S)
    geri = timedelta(days=7 if haftalik else 1)

    def satir(ev: dict, sag: str | None) -> list[dict]:
        eff = from_iso(ev.get("effective_from"))
        if ev["kind"] == KIND_FREE:
            son = from_iso(ev.get("effective_to"))
            alt = "Ücretsiz geçiş · " + (aralik(eff, son) if eff and son else fmt_date(eff))
            return [{"ad": ev["title"], "alt": alt, **({"sag": sag} if sag is not None else {})}]
        rows = [{"ad": ad, "alt": f"{eski_yeni(old, new)} · {fmt_date(eff)}", **({"sag": sag} if sag is not None else {})}
                for ad, old, new in _fiyatlar(cfg, ev)]
        return rows or [{"ad": ev["title"], "alt": f"{STATUS_LABELS.get(ev['status'], ev['status'])} · {fmt_date(eff)}",
                         **({"sag": sag} if sag is not None else {})}]

    yaklasan = sorted((e for e in events.values() if e["status"] == "karar_cikti"),
                      key=lambda e: e.get("effective_from") or "9999")
    giren = sorted((e for e in events.values() if e["status"] == "yururlukte" and from_iso(e.get("effective_from"))
                    and now - geri <= from_iso(e["effective_from"]) <= now), key=lambda e: e["effective_from"])
    izlenen = sorted((e for e in events.values() if e["status"] in ("sinyal", "gundemde")),
                     key=lambda e: e["updated_at"], reverse=True)

    y_rows = [r for e in yaklasan for r in satir(e, kalan(from_iso(e.get("effective_from")), now))]
    y_rows += [{"ad": z["ad"], "alt": z["alt"], "sag": kalan(z["_tarih"], now)}
               for z in sorted(izleme.get("tz_yaklasan") or [], key=lambda z: z["_tarih"])]
    g_rows = [r for e in giren for r in satir(e, once(from_iso(e["effective_from"]), now))]
    i_rows = list(izleme.get("izlenen") or [])
    i_rows += [{"ad": e["title"], "alt": f"{STATUS_LABELS.get(e['status'], e['status'])} · son güncelleme "
                f"{fmt_date(from_iso(e['updated_at']))}"} for e in izlenen]
    i_rows.append({"ad": "Kaynak durumu", "alt": (f"{len(problems)} kaynak okunamıyor · " + "; ".join(problems))
                   if problems else f"Tümü okunuyor · son kontrol {kisa(now)}"})

    if haftalik:
        donem = haftalik_donem(now)
        konu, baslik = f"Haftalık tarife özeti · {donem}", f"{donem} haftasının özeti"
        giris = "Geçen hafta izlenen tarife ve saat dilimi gelişmeleri aşağıda özetlenmiştir."
        bos_giren, ne_zaman = "Bu hafta yürürlüğe giren değişiklik yok.", "bu hafta"
    else:
        konu, baslik = f"Günlük tarife özeti · {fmt_date(now)}", f"{fmt_date(now)} özeti"
        giris = "Son 24 saatte izlenen tarife ve saat dilimi gelişmeleri aşağıda özetlenmiştir."
        bos_giren, ne_zaman = "Bugün yürürlüğe giren değişiklik yok.", "bugün"
        t = rozet_yaz(t, "HAFTALIK ÖZET", "GÜNLÜK ÖZET")
    onizleme = (f"{len(y_rows)} yaklaşan değişiklik, "
                + (f"{ne_zaman} yürürlüğe giren yok." if not g_rows else f"{ne_zaman} {len(g_rows)} değişiklik yürürlüğe girdi.")
                + (" Tüm kaynaklar okunuyor." if not problems else f" {len(problems)} kaynak okunamıyor."))
    t = _ortak(t, konu=konu, onizleme=onizleme, baslik=baslik, giris=giris)
    t = sayac_yaz(t, "Yaklaşan değişiklikler", len(y_rows))
    t = sayac_yaz(t, "Yürürlüğe girenler", len(g_rows))
    # Boş listeler "boş durum" kutusuyla değişir; sıra kaymasın diye sondan başa
    if not g_rows:
        t = bos_liste(t, 1, bos_giren)
    if not y_rows:
        t = bos_liste(t, 0, "Yaklaşan değişiklik yok.")
    if (not g_rows or not y_rows) and ".ob-bg-soft{" not in t:
        # Boş durum kutusunun koyu tema rengi (örnek dosyadaki gibi, .ob-bg-gs satırlarının hemen altına)
        t = t.replace(".ob-bg-gs{background-color:#10302a !important;}\n",
                      ".ob-bg-gs{background-color:#10302a !important;}\n.ob-bg-soft{background-color:#15211d !important;}\n", 1)
        t = t.replace("[data-ogsb] .ob-bg-gs{background-color:#10302a !important;}\n",
                      "[data-ogsb] .ob-bg-gs{background-color:#10302a !important;}\n"
                      "[data-ogsb] .ob-bg-soft{background-color:#15211d !important;}\n", 1)
    return tekrarla(t, "liste_satiri", [x for x in (y_rows, g_rows, i_rows) if x])


def _uzaklik_m(a: dict, b: dict) -> float:
    import math
    r = 6371000.0
    p1, p2 = math.radians(a["lat"]), math.radians(b["lat"])
    dp, dl = p2 - p1, math.radians(b["lon"] - a["lon"])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def _gruplar(noktalar: list[dict]) -> list[list[dict]]:
    """Paneldeki gibi: her nokta, ilk noktasına 300 m'den yakın olan ilk gruba katılır."""
    out: list[list[dict]] = []
    for p in noktalar:
        if not (isinstance(p.get("lat"), (int, float)) and isinstance(p.get("lon"), (int, float))):
            continue
        g = next((g for g in out if _uzaklik_m(g[0], p) < 300), None)
        if g is None:
            out.append([p])
        else:
            g.append(p)
    return out


def _serbest_sayisi(yollar: list[dict]) -> int:
    """Panel haritasındaki "Serbest geçiş" sayısı (panel/harita.js: freeFlow + tümü serbest gişe grupları)."""
    n = sum(len(_gruplar(o.get("serbest_gecis") or [])) for o in yollar)
    istasyonlar = [s for o in yollar for s in o.get("istasyonlar") or [] if isinstance(s, dict)]
    return n + sum(1 for g in _gruplar(istasyonlar) if all(s.get("serbest") for s in g))


def izleme_ozeti(cfg: Config, ucret_tablosu: dict | None, saat_dilimleri: dict | None, tz_ozet: dict | None,
                 now: datetime) -> dict:
    """Özet e-postasındaki "İzlenenler" satırları ve yaklaşan saat dilimi değişiklikleri (pipeline verir)."""
    satirlar: list[dict] = []
    if ucret_tablosu:
        yollar = ucret_tablosu.get("otoyollar") or []
        sgs = _serbest_sayisi(yollar)
        kt = sum(1 for c in cfg.crossings if c.kind in ("kopru", "tunel"))
        satirlar.append({"ad": "Tarifeler", "alt": f"{len(yollar)} tarife tablosu · {kt} köprü ve tünel · {sgs} serbest geçiş noktası"})
    if saat_dilimleri:
        satirlar.append({"ad": "Saat dilimleri",
                         "alt": f"IANA tzdata {saat_dilimleri.get('iana') or saat_dilimleri.get('tzdata')} · "
                                f"{len(saat_dilimleri.get('zones') or {})} bölge"})
    tz_yaklasan = []
    from .saat_dilimi import ulkeler, utc as utc_yaz
    adlar = ulkeler() if tz_ozet else {}
    for b in (tz_ozet or {}).get("degisiklikler") or []:
        for f in b.get("farklar") or []:
            t = _tz_tarih(f.get("tarih"))
            if t and t > now and f.get("eski") is not None:
                tz_yaklasan.append({"ad": f"{adlar.get(f['cc'], f['cc'])} saat farkı",
                                    "alt": f"{utc(utc_yaz(f['eski']))} → {utc(utc_yaz(f['yeni']))} · {fmt_date(t)}",
                                    "_tarih": t})
    return {"izlenen": satirlar, "tz_yaklasan": tz_yaklasan}


def _tz_tarih(metin: str | None) -> datetime | None:
    """"1 Ocak 2027 00:00" → datetime (yerel saat; yalnızca sıralama ve kalan gün için)."""
    if not metin:
        return None
    m = re.match(r"(\d{1,2}) (\S+) (\d{4})(?: (\d{2}):(\d{2}))?", metin)
    if not m or m.group(2) not in MONTHS_TR:
        return None
    from .timeutil import TZ
    return datetime(int(m.group(3)), MONTHS_TR.index(m.group(2)) + 1, int(m.group(1)),
                    int(m.group(4) or 0), int(m.group(5) or 0), tzinfo=TZ)


def genel(baslik: str, govde_html: str) -> str:
    """Özel tasarımı olmayan e-postalar (ör. deneme) için: aynı tasarımın sade hâli."""
    t = sablon("01")
    t = rozet_yaz(t, "KARAR ÇIKTI", "BİLDİRİM")
    t = bolum_sil(t, "<!-- ▼ BİLEŞEN: bilgi_kutusu -->")
    t = bolum_sil(t, "<!-- ▼ BİLEŞEN: ucret_tablosu -->")
    t = bolum_sil(t, 'Kaynak: <a href="{{kaynak_url}}"')
    return _ortak(t, konu=baslik, onizleme=baslik, baslik=baslik, giris=Ham(govde_html))


def kalan_alanlar(t: str) -> list[str]:
    """Doldurulmamış alan adları (testler için)."""
    return re.findall(r"\{\{(\w+)\}\}", t)
