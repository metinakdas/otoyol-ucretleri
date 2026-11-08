"""Yapılandırma: config/*.yaml dosyaları ve .env içindeki gizli bilgiler."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent

SOURCE_TYPES = {"tarife_listesi", "liste", "rss", "sayfa"}
TIERS = {"resmi", "haber"}
CROSSING_KINDS = {"kopru", "tunel", "otoyol"}
DEFAULT_OVERPASS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]


class ConfigError(Exception):
    pass


@dataclass
class Source:
    id: str
    name: str
    type: str
    tier: str
    url: str
    enabled: bool = True
    crossings: list[str] = field(default_factory=list)
    selector: str | None = None


@dataclass
class CrossingCfg:
    id: str
    name: str
    operator: str = "KGM"
    aliases: list[str] = field(default_factory=list)
    tariff_match: list[str] = field(default_factory=list)
    parse: str | None = None
    panel: bool = True
    kind: str = "kopru"
    location: tuple[float, float] | None = None
    provinces: list[int] = field(default_factory=list)  # plaka kodları


@dataclass
class Period:
    id: str
    name: str
    kind: str
    start: date
    end: date
    watch_days: int = 14


@dataclass
class Settings:
    user_agent: str = "Mozilla/5.0 (compatible; TarifeRadari/0.1)"
    request_delay: float = 2.0
    doc_recheck_hours: float = 24
    signal_close_days: int = 14
    reminder_days: list[int] = field(default_factory=lambda: [7, 1])
    digest_hour: int = 8
    source_error_hours: float = 24
    heartbeat_minutes: int = 180
    run_interval_minutes: int = 30
    unusual_increase_pct: float = 100
    map_refresh_days: int = 30          # 0: gişe verisini otomatik yenileme
    map_retry_hours: float = 24
    overpass_urls: list[str] = field(default_factory=lambda: list(DEFAULT_OVERPASS))
    # .env'den gelenler
    telegram_token: str = ""
    telegram_chat_id: str = ""
    telegram_tech_chat_id: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_ssl: bool = False
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    email_to: list[str] = field(default_factory=list)
    panel_url: str = ""

    @property
    def telegram_ready(self) -> bool:
        return bool(self.telegram_token and self.telegram_chat_id)

    @property
    def email_ready(self) -> bool:
        return bool(self.smtp_host and self.email_to and (self.smtp_from or self.smtp_user))


@dataclass
class Config:
    root: Path
    data_dir: Path
    sources: list[Source]
    crossings: list[CrossingCfg]
    generic_phrases: list[str]
    generic_scope: list[str]
    periods: list[Period]
    settings: Settings

    def crossing(self, crossing_id: str) -> CrossingCfg | None:
        return next((c for c in self.crossings if c.id == crossing_id), None)

    def crossing_name(self, crossing_id: str) -> str:
        c = self.crossing(crossing_id)
        return c.name if c else crossing_id

    def source(self, source_id: str) -> Source | None:
        return next((s for s in self.sources if s.id == source_id), None)


def load_dotenv(path: Path) -> None:
    """Basit .env okuyucu. Ortamda zaten tanımlı değişkenlerin üzerine yazmaz."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _read_yaml(path: Path) -> dict:
    if not path.exists():
        raise ConfigError(f"Yapılandırma dosyası bulunamadı: {path}")
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _as_date(value, field_name: str) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ConfigError(f"Geçersiz tarih ({field_name}): {value}") from exc


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.environ.get(name, "")
    if not value:
        return default
    return value.strip().lower() in {"1", "true", "evet", "yes", "on"}


def _crossing(c: dict) -> CrossingCfg:
    from .bolgeler import plaka_bul, turkiye_icinde

    cid = str(c["id"])
    kind = str(c.get("tur", "kopru"))
    if kind not in CROSSING_KINDS:
        raise ConfigError(f"{cid}: tur 'kopru', 'tunel' ya da 'otoyol' olmalı")
    location = None
    if c.get("konum") is not None:
        try:
            lat, lon = (float(v) for v in c["konum"])
        except (TypeError, ValueError) as exc:
            raise ConfigError(f"{cid}: konum [enlem, boylam] biçiminde olmalı") from exc
        if not turkiye_icinde(lat, lon):
            raise ConfigError(f"{cid}: konum Türkiye sınırları dışında görünüyor ({lat}, {lon})")
        location = (lat, lon)
    raw_il = c.get("il") or []
    provinces = []
    for name in raw_il if isinstance(raw_il, list) else [raw_il]:
        plaka = plaka_bul(name)
        if plaka is None:
            raise ConfigError(f"{cid}: bilinmeyen il '{name}'")
        provinces.append(plaka)
    return CrossingCfg(
        id=cid,
        name=str(c["name"]),
        operator=str(c.get("operator", "KGM")),
        aliases=[str(a) for a in c.get("aliases") or []],
        tariff_match=[str(a) for a in c.get("tariff_match") or []],
        parse=c.get("parse"),
        panel=bool(c.get("panel", True)),
        kind=kind,
        location=location,
        provinces=provinces,
    )


def load_config(root: Path | None = None, data_dir: Path | None = None) -> Config:
    root = Path(root) if root else ROOT
    load_dotenv(root / ".env")
    cfg_dir = root / "config"

    raw_sources = _read_yaml(cfg_dir / "sources.yaml").get("sources", [])
    sources: list[Source] = []
    seen: set[str] = set()
    for item in raw_sources:
        src = Source(
            id=str(item["id"]),
            name=str(item.get("name") or item["id"]),
            type=str(item["type"]),
            tier=str(item.get("tier", "haber")),
            url=str(item["url"]),
            enabled=bool(item.get("enabled", True)),
            crossings=[str(c) for c in item.get("crossings") or []],
            selector=item.get("selector"),
        )
        if src.id in seen:
            raise ConfigError(f"Aynı kaynak kimliği iki kez kullanılmış: {src.id}")
        if src.type not in SOURCE_TYPES:
            raise ConfigError(f"{src.id}: bilinmeyen kaynak türü '{src.type}'")
        if src.tier not in TIERS:
            raise ConfigError(f"{src.id}: tier 'resmi' ya da 'haber' olmalı")
        seen.add(src.id)
        sources.append(src)

    raw_crossings = _read_yaml(cfg_dir / "crossings.yaml")
    crossings = [_crossing(c) for c in raw_crossings.get("crossings", [])]
    crossing_ids = {c.id for c in crossings}
    generic_scope = [str(c) for c in raw_crossings.get("generic_scope") or []]
    for cid in generic_scope + [c for s in sources for c in s.crossings]:
        if cid not in crossing_ids:
            raise ConfigError(f"Tanımsız geçiş kimliği: {cid} (config/crossings.yaml)")

    raw_cal = _read_yaml(cfg_dir / "calendar.yaml").get("periods", []) if (cfg_dir / "calendar.yaml").exists() else []
    periods = [
        Period(
            id=str(p["id"]),
            name=str(p["name"]),
            kind=str(p.get("kind", "bayram")),
            start=_as_date(p["start"], f"{p['id']}.start"),
            end=_as_date(p.get("end", p["start"]), f"{p['id']}.end"),
            watch_days=int(p.get("watch_days", 14)),
        )
        for p in raw_cal
    ]

    raw_settings = _read_yaml(cfg_dir / "settings.yaml") if (cfg_dir / "settings.yaml").exists() else {}
    s = Settings(
        user_agent=str(raw_settings.get("user_agent", Settings.user_agent)),
        request_delay=float(raw_settings.get("istek_araligi_saniye", 2)),
        doc_recheck_hours=float(raw_settings.get("belge_kontrol_saat", 24)),
        signal_close_days=int(raw_settings.get("sinyal_kapanma_gun", 14)),
        reminder_days=[int(d) for d in raw_settings.get("hatirlatma_gun", [7, 1])],
        digest_hour=int(raw_settings.get("ozet_saati", 8)),
        source_error_hours=float(raw_settings.get("kaynak_hata_saat", 24)),
        heartbeat_minutes=int(raw_settings.get("heartbeat_dakika", 180)),
        run_interval_minutes=int(raw_settings.get("calisma_araligi_dakika", 30)),
        unusual_increase_pct=float(raw_settings.get("olagan_disi_artis_yuzde", 100)),
        map_refresh_days=int(raw_settings.get("harita_yenileme_gun", 30)),
        map_retry_hours=float(raw_settings.get("harita_tekrar_deneme_saat", 24)),
        overpass_urls=[str(u) for u in raw_settings.get("harita_overpass") or DEFAULT_OVERPASS],
        telegram_token=os.environ.get("TELEGRAM_BOT_TOKEN", "").strip(),
        telegram_chat_id=os.environ.get("TELEGRAM_CHAT_ID", "").strip(),
        telegram_tech_chat_id=os.environ.get("TELEGRAM_TECH_CHAT_ID", "").strip(),
        smtp_host=os.environ.get("SMTP_HOST", "").strip(),
        smtp_port=int(os.environ.get("SMTP_PORT", "587") or 587),
        smtp_ssl=_bool_env("SMTP_SSL"),
        smtp_user=os.environ.get("SMTP_USER", "").strip(),
        smtp_password=os.environ.get("SMTP_PASSWORD", ""),
        smtp_from=os.environ.get("SMTP_FROM", "").strip(),
        email_to=[e.strip() for e in os.environ.get("EMAIL_TO", "").split(",") if e.strip()],
        panel_url=(os.environ.get("PANEL_URL") or str(raw_settings.get("panel_url", "") or "")).strip(),
    )

    return Config(
        root=root,
        data_dir=Path(data_dir) if data_dir else root / "data",
        sources=sources,
        crossings=crossings,
        generic_phrases=[str(p) for p in raw_crossings.get("generic_phrases") or []],
        generic_scope=generic_scope,
        periods=periods,
        settings=s,
    )
