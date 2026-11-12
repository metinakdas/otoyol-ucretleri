"""Dünya saat dilimi değişikliklerini izler; bir ülkenin saat farkı değişince bildirir.

Kaynak: IANA saat dilimi veritabanı (tz). Windows, Android, iOS ve Linux da bu kaydı izler; hükümetlerin
saat kararları önce buraya girer. Python'daki karşılığı PyPI'daki `tzdata` paketidir; GitHub Actions her turda
paketi en son sürüme günceller.

Yöntem: Her bölgenin (zone.tab: ülke başına bir ya da birkaç bölge) önümüzdeki PENCERE_GUN gündeki UTC farkı
geçişleriyle birlikte data/saat-dilimleri.json'a yazılır. Paket sürümü yükselince aynı pencere yeni kurallarla
yeniden hesaplanır; bugünden sonra farklılaşan bölgeler bildirilir (ör. "15 Ekim'den itibaren UTC-03:00,
eski kurala göre UTC-04:00 olacaktı"). Paket eskiyse (ör. yerel bilgisayar) hiçbir şey yapılmaz.
"""

from __future__ import annotations

import html
import importlib.metadata
import importlib.resources
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .config import Config
from .notify import Message
from .store import Store
from .timeutil import MONTHS_TR, hours_since, to_iso

DOSYA = "saat-dilimleri.json"
STATE_KEY = "_saat_dilimi"
PENCERE_GUN = 400          # bugünden bu kadar gün sonrasına kadarki geçişler karşılaştırılır
YENILE_GUN = 300           # pencerenin kalan kısmı bundan kısalınca (sürüm aynıyken) sessizce yenilenir
GECMIS = 12                # panelde ve kayıtta tutulan değişiklik sayısı
BEKLEME_GUN = 30           # gönderilemeyen bildirim bu kadar gün yeniden denenir
EN_FAZLA_SATIR = 25
NEWS_URL = "https://data.iana.org/time-zones/tzdb/NEWS"
UTC = timezone.utc
SEMA = 2                   # görüntü biçimi; değişince dosya sessizce yeniden yazılır


# ---------------------------------------------------------------------------- tzdata paketi

def surum() -> tuple[str, str]:
    """(paket sürümü, IANA sürümü), ör. ("2026.5", "2026e")."""
    import tzdata
    return importlib.metadata.version("tzdata"), str(getattr(tzdata, "IANA_VERSION", ""))


def _vkey(v: str | None) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v or ""))


def _dosya(*parts: str):
    return importlib.resources.files("tzdata.zoneinfo").joinpath(*parts)


def bolgeler() -> dict[str, str]:
    """Bölge → ülke kodu (zone.tab)."""
    out: dict[str, str] = {}
    for line in _dosya("zone.tab").read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#"):
            cols = line.split("\t")
            if len(cols) >= 3:
                out[cols[2]] = cols[0]
    return out


def ulkeler() -> dict[str, str]:
    out: dict[str, str] = {}
    for line in _dosya("iso3166.tab").read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#"):
            cc, _, name = line.partition("\t")
            out[cc] = name.strip()
    return out


def bolge(name: str) -> ZoneInfo:
    """Bölgeyi doğrudan tzdata paketinden yükler (Linux'taki eski sistem verisi değil)."""
    with _dosya(*name.split("/")).open("rb") as f:
        return ZoneInfo.from_file(f, key=name)


# ---------------------------------------------------------------------------- geçişler

def _an(z: ZoneInfo, t: datetime) -> tuple[int, bool]:
    local = t.astimezone(z)
    return int(local.utcoffset().total_seconds()), bool(local.dst())


def _iso(t: datetime) -> str:
    return t.astimezone(UTC).isoformat(timespec="minutes")


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


def gecisler(z: ZoneInfo, start: datetime, end: datetime) -> list[list]:
    """[[utc_iso, fark_saniye, yaz_saati], ...]; ilk öğe pencerenin başındaki durumdur."""
    cur = _an(z, start)
    out = [[_iso(start), *cur]]
    t, step = start, timedelta(days=1)
    while t < end:
        n = min(t + step, end)
        v = _an(z, n)
        if v != cur:
            lo, hi = t, n
            while hi - lo > timedelta(minutes=1):
                mid = lo + (hi - lo) / 2
                if _an(z, mid) == cur:
                    lo = mid
                else:
                    hi = mid
            floor = hi.replace(second=0, microsecond=0)
            hi = floor if _an(z, floor) == v else floor + timedelta(minutes=1)
            out.append([_iso(hi), *v])
            cur = v
        t = n
    return out


def _deger(gs: list[list], at: datetime) -> tuple[int, bool]:
    val = (gs[0][1], gs[0][2])
    for t, off, dst in gs:
        if _dt(t) <= at:
            val = (off, dst)
        else:
            break
    return val


def anlik_goruntu(now: datetime, paket: str, iana: str) -> dict:
    start = now.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
    end = start + timedelta(days=PENCERE_GUN)
    zones = {}
    for name, cc in bolgeler().items():  # zone.tab sırası (ülke içinde doğudan batıya), panel grupları için
        try:
            zones[name] = {"cc": cc, "t": gecisler(bolge(name), start, end)}
        except Exception:  # paket bozuksa tek bölge yüzünden durma
            continue
    names = ulkeler()
    return {"sema": SEMA, "tzdata": paket, "iana": iana, "start": _iso(start), "end": _iso(end),
            "ulkeler": {cc: names[cc] for cc in sorted({z["cc"] for z in zones.values()}) if cc in names},
            "zones": zones}


# ---------------------------------------------------------------------------- karşılaştırma

def utc(sec: int) -> str:
    sign = "+" if sec >= 0 else "-"
    s = abs(sec)
    return f"UTC{sign}{s // 3600:02d}:{s % 3600 // 60:02d}"


def _yerel(t: datetime, z: ZoneInfo) -> str:
    d = t.astimezone(z)
    return f"{d.day} {MONTHS_TR[d.month - 1]} {d.year} {d:%H:%M}"


def _takvim(gs: list[list], after: datetime, z: ZoneInfo) -> str:
    sonraki = [g for g in gs[1:] if _dt(g[0]) > after][:3]
    if not sonraki:
        return "Yaz saati yok, sabit."
    return "Sonraki geçişler: " + ", ".join(
        f"{_yerel(_dt(t), z).rsplit(' ', 1)[0]} → {utc(off)}{' (yaz saati)' if dst else ''}" for t, off, dst in sonraki) + "."


def karsilastir(eski: dict, now: datetime) -> list[dict]:
    """Eski görüntüyü bu paketin kurallarıyla aynı pencerede yeniden hesaplar; farklılaşanları döndürür."""
    start, end = _dt(eski["start"]), _dt(eski["end"])
    simdi = max(now.astimezone(UTC), start)
    out = []
    yeni_bolgeler = bolgeler()
    for name, cc in sorted(yeni_bolgeler.items()):
        try:
            z = bolge(name)
        except Exception:
            continue
        if name not in eski["zones"]:
            gs = gecisler(z, simdi, simdi + timedelta(days=PENCERE_GUN))
            out.append({"zone": name, "cc": cc, "yeni_bolge": True, "simdi": gs[0][1], "takvim": _takvim(gs, simdi, z)})
            continue
        eg = eski["zones"][name]["t"]
        yg = gecisler(z, start, end)
        if eg == yg:
            continue
        noktalar = sorted({simdi} | {_dt(t) for t, _, _ in eg + yg if simdi <= _dt(t) < end})
        fark = next((p for p in noktalar if _deger(eg, p) != _deger(yg, p)), None)
        if fark is None:
            continue
        out.append({
            "zone": name, "cc": cc, "yeni_bolge": False,
            "tarih": None if fark == simdi else _yerel(fark, z),
            "eski": _deger(eg, fark)[0], "yeni": _deger(yg, fark)[0], "yaz": _deger(yg, fark)[1],
            "takvim": _takvim(yg, fark, z),
        })
    return out


def satirlar(farklar: list[dict]) -> list[str]:
    names = ulkeler()
    out = []
    for f in farklar:
        ulke = f"{names.get(f['cc'], f['cc'])} ({f['zone']})"
        if f["yeni_bolge"]:
            out.append(f"{ulke}: yeni saat dilimi bölgesi, şu an {utc(f['simdi'])}. {f['takvim']}")
            continue
        ne_zaman = f"{f['tarih']} itibarıyla" if f["tarih"] else "Şu andan itibaren"
        yaz = " (yaz saati)" if f["yaz"] else ""
        out.append(f"{ulke}: {ne_zaman} {utc(f['yeni'])}{yaz}; eski kurala göre {utc(f['eski'])} olacaktı. {f['takvim']}")
    return out


# ---------------------------------------------------------------------------- radar turu

def _bildirim(key: str, subject: str, lines: list[str], at: datetime, channels: tuple[str, ...], kind: str,
              iana: str, farklar: list[dict] | None = None) -> dict:
    out = {"key": key, "kind": kind, "at": to_iso(at), "iana": iana, "subject": subject, "lines": lines,
           "channels": list(channels)}
    if farklar:  # panelde "eski → yeni" gösterimi için
        out["farklar"] = [{"zone": f["zone"], "cc": f["cc"], "eski": None if f["yeni_bolge"] else f["eski"],
                           "yeni": f["simdi"] if f["yeni_bolge"] else f["yeni"], "tarih": f.get("tarih")}
                          for f in farklar]
    return out


def _mesaj(b: dict) -> Message:
    head, body = b["lines"][0], b["lines"][1:]
    h = "\n".join([f"<b>{html.escape(head)}</b>", *(html.escape(x) for x in body)])
    return Message(key=b["key"], channels=tuple(b["channels"]), subject=b["subject"], html=h, plain="\n".join(b["lines"]))


def kontrol(cfg: Config, store: Store, state: dict, sent: dict, now: datetime) -> tuple[list[Message], list[str], bool]:
    """Bildirilecek mesajları, günlük notlarını ve görüntü dosyasının yazılıp yazılmadığını döndürür."""
    if not cfg.settings.tz_watch:
        return [], [], False
    paket, iana = surum()
    info = state.setdefault(STATE_KEY, {})
    gecmis: list[dict] = info.setdefault("bildirimler", [])
    eski = store.read(DOSYA, None)
    notes: list[str] = []
    yazildi = False

    if not eski:
        snap = anlik_goruntu(now, paket, iana)
        yazildi = store.write(DOSYA, snap)
        tr = snap["zones"].get("Europe/Istanbul")
        lines = [f"[SAAT DİLİMİ İZLEME BAŞLADI] IANA tzdata {iana}",
                 f"{len(snap['zones'])} bölge, {len(set(z['cc'] for z in snap['zones'].values()))} ülke izleniyor.",
                 "Bir ülkenin saat farkı ya da yaz saati değişince bildirim gelir."]
        if tr:
            lines.append(f"Türkiye: {utc(tr['t'][0][1])}" + (", yaz saati yok." if len(tr["t"]) == 1 else "."))
        gecmis.append(_bildirim("saatdilimi:kurulum", "[Saat dilimi] İzleme başladı", lines, now, ("telegram",),
                                "kurulum", iana))
    elif _vkey(paket) > _vkey(eski.get("tzdata")):
        farklar = karsilastir(eski, now)
        if farklar:
            ls = satirlar(farklar)
            ulke_sayisi = len({f["cc"] for f in farklar})
            body = ls[:EN_FAZLA_SATIR] + ([f"…ve {len(ls) - EN_FAZLA_SATIR} bölge daha (panelde)"] if len(ls) > EN_FAZLA_SATIR else [])
            lines = [f"[SAAT DİLİMİ DEĞİŞTİ] {ulke_sayisi} ülke · IANA tzdata {iana}", *body, f"Kaynak: {NEWS_URL}"]
            gecmis.append(_bildirim(f"saatdilimi:{iana or paket}", f"[Saat dilimi] {ulke_sayisi} ülkede değişiklik",
                                    lines, now, ("telegram", "email"), "degisim", iana, farklar))
            notes.append(f"Saat dilimi: tzdata {iana}, {len(farklar)} bölgede değişiklik")
        else:
            notes.append(f"Saat dilimi: tzdata {iana} geldi; gelecekteki saat farklarında değişiklik yok")
        yazildi = store.write(DOSYA, anlik_goruntu(now, paket, iana))
    elif _vkey(paket) == _vkey(eski.get("tzdata")) and (
            _dt(eski["end"]) - now < timedelta(days=YENILE_GUN) or eski.get("sema") != SEMA):
        yazildi = store.write(DOSYA, anlik_goruntu(now, paket, iana))

    if _vkey(paket) >= _vkey(info.get("tzdata")):
        info.update(tzdata=paket, iana=iana)
    del gecmis[:-GECMIS]
    mesajlar = [_mesaj(b) for b in gecmis
                if b["key"] not in sent and hours_since(b["at"], now) < BEKLEME_GUN * 24]
    return mesajlar, notes, yazildi


def panel_ozeti(state: dict) -> dict | None:
    """Panel özeti. Bölgelerin tam listesi data/saat-dilimleri.json'dadır (pencere açılınca yüklenir)."""
    info = state.get(STATE_KEY)
    if not info:
        return None
    son = [b for b in reversed(info.get("bildirimler") or []) if b["kind"] == "degisim"][:6]
    farklar: dict[str, dict] = {}
    for b in reversed(son):  # en yeni değişiklik kazanır
        for f in b.get("farklar") or []:
            farklar[f["zone"]] = {**f, "iana": b["iana"], "at": b["at"]}
    return {
        "iana": info.get("iana"),
        "kaynak": NEWS_URL,
        "degisiklikler": [{"at": b["at"], "iana": b["iana"], "lines": b["lines"][1:-1], "farklar": b.get("farklar") or []}
                          for b in son],
        "farklar": farklar,
    }
