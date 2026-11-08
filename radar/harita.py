"""Haritadaki otoyol gişeleri: OpenStreetMap verisi (Overpass API, ücretsiz).

Her il için gişe (barrier=toll_booth) ve serbest geçiş (highway=toll_gantry) noktaları ile bağlı
oldukları yol (ör. O-4 Anadolu Otoyolu) alınır. Aynı gişenin şeritleri tek noktada birleştirilir ve
sonuç data/harita.json dosyasına yazılır. Veri © OpenStreetMap katkıcıları, ODbL lisanslıdır.

Sorgu ayda bir çalışır (settings.yaml: harita_yenileme_gun). Başarısız olursa eski veri korunur ve
radarın asıl işi (ücret ve duyuru takibi) etkilenmez.
"""

from __future__ import annotations

import logging
import math
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

import httpx

from . import bolgeler
from .config import Config
from .guvenlik import redact
from .store import Store
from .textutil import clean_spaces, fold
from .timeutil import from_iso, hours_since, to_iso

log = logging.getLogger(__name__)

SCHEMA = 1
STATE_KEY = "_harita"
LISANS = "© OpenStreetMap katkıcıları (ODbL)"

# İller tek tek dolaşılır; her il alanının etiketleri, ardından o ildeki her gişe noktası ve
# noktanın üzerinde bulunduğu yolların etiketleri yazdırılır. Böylece her nokta ili ve yoluyla gelir.
QUERY = """[out:json][timeout:240];
rel["boundary"="administrative"]["ISO3166-2"~"^TR-[0-9][0-9]$"];
map_to_area->.iller;
foreach.iller->.il(
  .il out tags;
  (
    node(area.il)["barrier"="toll_booth"];
    node(area.il)["highway"="toll_gantry"];
  )->.noktalar;
  .noktalar out;
  way(bn.noktalar)["highway"];
  out body;
  way(area.il)["barrier"="toll_booth"];
  out tags center;
);"""

# "Gişe" gibi tek başına ad sayılmayacak etiketler
_GENERIC_NAMES = {"gise", "giseler", "gise noktasi", "toll booth", "toll", "hgs", "ogs", "hgs/ogs", "hgs ogs"}
_ROAD_RANK = {"motorway": 0, "trunk": 1, "motorway_link": 2, "trunk_link": 3, "primary": 4}

# Aynı gişeye ait sayılacak uzaklıklar (metre)
JOIN_NAMED_M = 3000      # aynı adlı noktalar
JOIN_UNNAMED_M = 600     # adsız noktalar (aynı yol)
ATTACH_UNNAMED_M = 400   # adsız noktayı yakındaki adlı gişeye bağlama


class HaritaHatasi(Exception):
    pass


@dataclass
class Booth:
    osm: str
    lat: float
    lon: float
    kind: str                       # "gise" | "serbest"
    name: str | None
    plaka: int | None
    operator: str | None = None
    roads: list[dict] = field(default_factory=list)

    def road(self) -> dict:
        """Noktanın bağlı olduğu en anlamlı yol: otoyol > ana yol > bağlantı; numarası olan önce."""
        if not self.roads:
            return {}
        return sorted(self.roads, key=lambda r: (_ROAD_RANK.get(r.get("highway"), 9), not r.get("ref")))[0]


def _name(tags: dict) -> str | None:
    name = clean_spaces(tags.get("name:tr") or tags.get("name") or "")
    if not name or fold(name) in _GENERIC_NAMES:
        return None
    return name


def _road_info(tags: dict) -> dict:
    ref = clean_spaces(tags.get("ref") or "")
    return {
        "ref": ref.split(";")[0].strip() or None,
        "name": clean_spaces(tags.get("name:tr") or tags.get("name") or "") or None,
        "highway": tags.get("highway"),
        "operator": clean_spaces(tags.get("operator") or "") or None,
    }


def parse_elements(elements: list[dict]) -> list[Booth]:
    """Overpass çıktısını sırayla okur: il alanı → nokta → noktanın yolları."""
    plaka: int | None = None
    booths: dict[str, Booth] = {}
    last: Booth | None = None
    for el in elements:
        etype = el.get("type")
        tags = el.get("tags") or {}
        if etype == "area":
            plaka = bolgeler.plaka_bul(tags.get("ISO3166-2"))
            last = None
        elif etype == "node" and "lat" in el:
            key = f"node/{el['id']}"
            if key in booths:          # il sınırındaki nokta iki kez gelebilir
                last = booths[key]
                continue
            kind = "serbest" if tags.get("highway") == "toll_gantry" and tags.get("barrier") != "toll_booth" else "gise"
            last = booths[key] = Booth(
                osm=key, lat=float(el["lat"]), lon=float(el["lon"]), kind=kind, name=_name(tags),
                plaka=plaka, operator=clean_spaces(tags.get("operator") or "") or None,
            )
        elif etype == "way":
            if "center" in el and tags.get("barrier") == "toll_booth":
                key = f"way/{el['id']}"
                if key not in booths:
                    booths[key] = Booth(
                        osm=key, lat=float(el["center"]["lat"]), lon=float(el["center"]["lon"]), kind="gise",
                        name=_name(tags), plaka=plaka, operator=clean_spaces(tags.get("operator") or "") or None,
                    )
                last = None
            elif "nodes" in el:  # yol: üzerindeki gişe noktalarına bağlanır
                info = _road_info(tags)
                for nid in el["nodes"]:
                    b = booths.get(f"node/{nid}")
                    if b is not None and info not in b.roads:
                        b.roads.append(info)
            elif last is not None:  # eski biçim: yol, hemen önceki noktaya aittir
                info = _road_info(tags)
                if info not in last.roads:
                    last.roads.append(info)
    return list(booths.values())


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


@dataclass
class _Group:
    kind: str
    name_key: str
    ref: str | None
    members: list[Booth] = field(default_factory=list)

    @property
    def lat(self) -> float:
        return sum(b.lat for b in self.members) / len(self.members)

    @property
    def lon(self) -> float:
        return sum(b.lon for b in self.members) / len(self.members)

    def near(self, b: Booth, limit: float) -> bool:
        return any(distance_m(m.lat, m.lon, b.lat, b.lon) <= limit for m in self.members)


def group_booths(booths: list[Booth]) -> list[_Group]:
    """Aynı gişenin şeritlerini (ve iki yön noktalarını) tek gruba toplar."""
    groups: list[_Group] = []
    named = sorted((b for b in booths if b.name), key=lambda b: (fold(b.name), b.lat, b.lon, b.osm))
    unnamed = sorted((b for b in booths if not b.name), key=lambda b: (b.lat, b.lon, b.osm))
    for b in named:
        key = fold(b.name)
        target = next((g for g in groups if g.kind == b.kind and g.name_key == key and g.near(b, JOIN_NAMED_M)), None)
        if target is None:
            target = _Group(kind=b.kind, name_key=key, ref=b.road().get("ref"))
            groups.append(target)
        target.members.append(b)
    for b in unnamed:
        ref = b.road().get("ref")
        target = next((g for g in groups if g.kind == b.kind and g.name_key
                       and (not ref or not g.ref or g.ref == ref) and g.near(b, ATTACH_UNNAMED_M)), None)
        if target is None:
            target = next((g for g in groups if g.kind == b.kind and not g.name_key and g.ref == ref
                           and g.near(b, JOIN_UNNAMED_M)), None)
        if target is None:
            target = _Group(kind=b.kind, name_key="", ref=ref)
            groups.append(target)
        target.members.append(b)
    return groups


def _most_common(values) -> str | None:
    values = [v for v in values if v]
    return Counter(values).most_common(1)[0][0] if values else None


def _point(g: _Group) -> dict:
    members = sorted(g.members, key=lambda b: b.osm)
    roads = [b.road() for b in members]
    ref = _most_common(r.get("ref") for r in roads)
    road_name = _most_common(r.get("name") for r in roads if not ref or r.get("ref") == ref)
    name = _most_common(b.name for b in members)
    plaka = Counter(b.plaka for b in members if b.plaka).most_common(1)
    plaka = plaka[0][0] if plaka else None
    kind_label = "Serbest geçiş noktası" if g.kind == "serbest" else "Gişe"
    if not name:
        name = f"{kind_label} ({ref})" if ref else kind_label
    return {
        "id": "osm-" + members[0].osm.replace("/", "-"),
        "ad": name,
        "adsiz": not g.name_key,
        "tur": g.kind,
        "lat": round(g.lat, 5),
        "lon": round(g.lon, 5),
        "plaka": plaka,
        "il": bolgeler.il_adi(plaka),
        "bolge": bolgeler.bolge(plaka),
        "yol": ref,
        "yol_adi": road_name,
        "isletmeci": _most_common([b.operator for b in members] + [r.get("operator") for r in roads]),
        "osm": members[0].osm,
        "nokta_sayisi": len(members),
    }


def build_map(elements: list[dict], now: datetime) -> dict:
    points = [_point(g) for g in group_booths(parse_elements(elements))]
    order = {b[0]: i for i, b in enumerate(bolgeler.BOLGELER)}
    points.sort(key=lambda p: (order.get(p["bolge"], 99), fold(p["il"] or ""), p["adsiz"], fold(p["ad"]), p["id"]))
    per_region = Counter(p["bolge"] or "bilinmiyor" for p in points)
    return {
        "schema": SCHEMA,
        "olusturma": to_iso(now),
        "kaynak": "OpenStreetMap (Overpass API)",
        "lisans": LISANS,
        "ozet": {"toplam": len(points), "bolge": dict(sorted(per_region.items()))},
        "noktalar": points,
    }


# ---------------------------------------------------------------------------- indirme

def fetch_elements(cfg: Config, transport: httpx.BaseTransport | None = None) -> list[dict]:
    errors = []
    # Overpass tarayıcı gibi görünen istemcileri reddedebiliyor (HTTP 406); kendimizi açıkça tanıtırız.
    headers = {"User-Agent": "TarifeRadari/0.2 (gecis ucreti radari; OpenStreetMap gise verisi)", "Accept": "*/*"}
    timeout = httpx.Timeout(270.0, connect=20.0)
    with httpx.Client(headers=headers, timeout=timeout, transport=transport, follow_redirects=True) as client:
        for url in cfg.settings.overpass_urls:
            try:
                res = client.post(url, data={"data": QUERY})
                if res.status_code != 200:
                    raise HaritaHatasi(f"HTTP {res.status_code}")
                data = res.json()
                remark = str(data.get("remark") or "")
                if "error" in remark.lower() or "timed out" in remark.lower():
                    raise HaritaHatasi(f"sunucu sorguyu tamamlayamadı: {remark[:160]}")
                elements = data.get("elements")
                if not isinstance(elements, list):
                    raise HaritaHatasi("beklenmeyen yanıt")
                if not elements:
                    raise HaritaHatasi("boş yanıt")
                return elements
            except Exception as exc:  # sıradaki sunucuyu dene
                log.debug("Overpass hatası %s", url, exc_info=True)
                errors.append(f"{httpx.URL(url).host}: {exc}")
    raise HaritaHatasi("; ".join(errors) or "Overpass sunucusu tanımlı değil")


def needs_refresh(cfg: Config, state: dict, existing: dict | None, now: datetime) -> bool:
    days = cfg.settings.map_refresh_days
    if days <= 0:
        return False
    st = state.get(STATE_KEY) or {}
    if st.get("son_deneme") and hours_since(st["son_deneme"], now) < cfg.settings.map_retry_hours:
        return False
    if not existing or not existing.get("noktalar"):
        return True
    created = from_iso(existing.get("olusturma"))
    return created is None or (now - created).total_seconds() >= days * 86400


def refresh(cfg: Config, store: Store, state: dict, now: datetime, *, force: bool = False,
            transport: httpx.BaseTransport | None = None) -> str | None:
    """Gerekiyorsa gişe verisini yeniler. Bir not döner (yenileme yoksa None)."""
    existing = store.read("harita.json", None)
    if not force and not needs_refresh(cfg, state, existing, now):
        return None
    st = state.setdefault(STATE_KEY, {})
    st["son_deneme"] = to_iso(now)
    try:
        data = build_map(fetch_elements(cfg, transport), now)
        n_new = data["ozet"]["toplam"]
        n_old = len((existing or {}).get("noktalar") or [])
        if n_new == 0:
            raise HaritaHatasi("hiç gişe noktası bulunamadı; eski veri korundu")
        if n_old and n_new < n_old * 0.5:
            raise HaritaHatasi(f"veri eksik görünüyor ({n_new} nokta, önceki {n_old}); eski veri korundu")
    except Exception as exc:
        st["hata"] = redact(exc, cfg.settings)[:300]
        return f"Harita verisi alınamadı: {st['hata']}"
    store.write("harita.json", data)
    st.update(son_basari=to_iso(now), hata=None, nokta=data["ozet"]["toplam"])
    return f"Harita: {data['ozet']['toplam']} gişe noktası güncellendi (OpenStreetMap)"


def panel_info(state: dict) -> dict:
    st = state.get(STATE_KEY) or {}
    return {"hata": st.get("hata"), "son_basari": st.get("son_basari")}
