"""Panel verisi (data/panel.json) ve yerel önizleme sunucusu."""

from __future__ import annotations

import functools
import http.server
import json
import socketserver
import threading
import webbrowser
from datetime import datetime, timedelta
from pathlib import Path

from . import bolgeler, saat_dilimi
from . import calendar as cal
from . import prices as ledger
from .config import Config
from .models import FLAG_LABELS, KIND_LABELS, STATUS_LABELS
from .timeutil import from_iso, to_iso

SCHEMA = 1


def _event_summary(cfg: Config, ev: dict) -> dict:
    return {
        "id": ev["id"],
        "kind": ev["kind"],
        "kind_label": KIND_LABELS.get(ev["kind"], ev["kind"]),
        "status": ev["status"],
        "status_label": STATUS_LABELS.get(ev["status"], ev["status"]),
        "title": ev["title"],
        "crossings": [{"id": c, "name": cfg.crossing_name(c)} for c in ev.get("crossings", [])],
        "excluded": [{"id": c, "name": cfg.crossing_name(c)} for c in ev.get("excluded", [])],
        "effective_from": ev.get("effective_from"),
        "effective_to": ev.get("effective_to"),
        "prices": ev.get("prices", {}),
        "flags": [{"id": f, "label": FLAG_LABELS.get(f, f)} for f in ev.get("flags", [])],
        "updated_at": ev["updated_at"],
        "created_at": ev["created_at"],
        "sources": [
            {"url": e["url"], "publisher": e.get("publisher"), "tier": e["tier"], "quote": e.get("quote", "")}
            for e in ev.get("evidence", [])[-3:]
        ],
    }


def crossing_place(c) -> dict:
    """Geçişin harita bilgisi: tür, konum, il(ler) ve bölge."""
    return {
        "tur": c.kind,
        "diger_adlar": [a for a in c.aliases if a != c.name],
        "konum": list(c.location) if c.location else None,
        "iller": [bolgeler.il_adi(p) for p in c.provinces],
        "bolge": bolgeler.bolge(c.provinces[0]) if c.provinces else None,
    }


def build(cfg: Config, *, events: dict, rules: dict, crossings_data: dict, state: dict,
          health: dict, now: datetime, last_run: str | None) -> dict:
    crossings = []
    for c in cfg.crossings:
        if not c.panel:
            continue
        current = ledger.entry_at(crossings_data, c.id, now)
        upcoming = ledger.upcoming_entry(crossings_data, c.id, now)
        free_now = next(
            (r for r in rules.values() if not r.get("cancelled") and c.id in r["crossings"]
             and from_iso(r["valid_from"]) <= now <= (from_iso(r.get("valid_to")) or now)),
            None,
        )
        crossings.append({
            "id": c.id,
            "name": c.name,
            "operator": c.operator,
            "current": current,
            "upcoming": upcoming,
            "history": [
                {"valid_from": e["valid_from"], "valid_to": e.get("valid_to"), "class1": e["classes"].get("1")}
                for e in ledger.entries(crossings_data, c.id)
            ],
            "free_now": {"title": free_now["title"], "valid_to": free_now.get("valid_to")} if free_now else None,
            **crossing_place(c),
        })

    evs = sorted(events.values(), key=lambda e: e["updated_at"], reverse=True)
    upcoming_events = sorted(
        (e for e in events.values() if e["status"] == "karar_cikti" and e.get("effective_from")
         and from_iso(e["effective_from"]) > now),
        key=lambda e: e["effective_from"],
    )
    active_rules = [r for r in rules.values() if not r.get("cancelled")
                    and from_iso(r["valid_from"]) <= now <= (from_iso(r.get("valid_to")) or now + timedelta(days=1))]
    next_rules = sorted((r for r in rules.values() if not r.get("cancelled") and from_iso(r["valid_from"]) > now),
                        key=lambda r: r["valid_from"])

    documents = []
    for src in cfg.sources:
        if src.type != "tarife_listesi":
            continue
        for key, d in (state.get(src.id, {}).get("docs") or {}).items():
            documents.append({
                "key": key,
                "title": d.get("title"),
                "url": d.get("url"),
                "changed_at": d.get("changed_at"),
                "checked_at": d.get("checked_at"),
                "effective_from": d.get("effective_from"),
                "crossings": [cfg.crossing_name(x) for x in d.get("crossings", [])],
                "removed": bool(d.get("removed_at")),
                "error": d.get("error"),
            })
    documents.sort(key=lambda d: (d["removed"], d["title"] or ""))

    sources = []
    for src in cfg.sources:
        h = health.get(src.id) or {}
        sources.append({
            "id": src.id,
            "name": src.name,
            "tier": src.tier,
            "type": src.type,
            "url": src.url,
            "enabled": src.enabled,
            "ok": h.get("ok") if src.enabled else None,
            "last_success": h.get("last_success"),
            "failing_since": h.get("failing_since"),
            "error": h.get("error"),
            "info": h.get("info"),
        })

    periods = [{
        "id": p.id, "name": p.name, "kind": p.kind,
        "start": p.start.isoformat(), "end": p.end.isoformat(),
        "watch_start": to_iso(cal.watch_start(p)),
    } for p in cal.upcoming(cfg, now)]

    return {
        "schema": SCHEMA,
        "ornek": False,
        "last_run": last_run,
        "run_interval_minutes": cfg.settings.run_interval_minutes,
        "panel_url": cfg.settings.panel_url,
        "names": {c.id: c.name for c in cfg.crossings},
        "crossings": crossings,
        "upcoming": [_event_summary(cfg, e) for e in upcoming_events],
        "active_rules": active_rules,
        "next_rules": next_rules,
        "events": [_event_summary(cfg, e) for e in evs[:40]],
        "documents": documents,
        "sources": sources,
        "calendar": periods,
        "bolgeler": bolgeler.panel_listesi(),
        "saat_dilimi": saat_dilimi.panel_ozeti(state),
    }


# Yerel sunucunun verebileceği dosyalar: panel klasörü ve iki veri dosyası. Proje kökündeki
# .env (anahtarlar) ya da data/ altındaki diğer kayıtlar hiçbir koşulda sunulmaz.
_SERVE_DATA = {"/data/panel.json", "/data/ucret-tablosu.json"}
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "[::1]"}


def _allowed_path(raw: str) -> str | None:
    """İstenen yolu denetler; izin verilen normal yolu ya da None döndürür."""
    from posixpath import normpath
    from urllib.parse import unquote, urlsplit

    path = unquote(urlsplit(raw).path)
    if "\\" in path or "\x00" in path or any(part in ("..", ".") for part in path.split("/")):
        return None
    clean = normpath(path) if path not in ("", "/") else "/"
    if clean == "/":
        return "/"
    if clean in _SERVE_DATA or clean == "/panel" or clean.startswith("/panel/"):
        return clean + ("/" if path.endswith("/") and not clean.endswith("/") else "")
    return None


class _PanelHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _guard(self) -> bool:
        host = (self.headers.get("Host") or "").strip().lower()
        hostname = host.rsplit(":", 1)[0] if not host.startswith("[") else host.split("]")[0] + "]"
        if hostname not in _LOCAL_HOSTS:  # DNS yeniden bağlama saldırılarına karşı
            self.send_error(403, "Only local access is allowed")
            return False
        allowed = _allowed_path(self.path)
        if allowed is None:
            self.send_error(404)
            return False
        if allowed == "/":
            self.send_response(302)
            self.send_header("Location", "/panel/")
            self.end_headers()
            return False
        return True

    def do_GET(self):
        if self._guard():
            super().do_GET()

    def do_HEAD(self):
        if self._guard():
            super().do_HEAD()

    def list_directory(self, path):  # klasör içerikleri listelenmez
        self.send_error(404)
        return None

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def serve(root: Path, port: int = 8000, sample: bool = False, open_browser: bool = True) -> None:
    """Paneli yalnızca bu bilgisayardan erişilebilen yerel bir sunucuyla açar."""
    handler = functools.partial(_PanelHandler, directory=str(root))
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    socketserver.ThreadingTCPServer.daemon_threads = True
    # Tarayıcı aynı anda birçok dosya ister; tek iş parçacıklı sunucu bağlantıları reddedebiliyordu.
    with socketserver.ThreadingTCPServer(("127.0.0.1", port), handler) as httpd:
        url = f"http://localhost:{port}/panel/" + ("?ornek=1" if sample else "")
        print(f"Panel: {url}  (durdurmak için Ctrl+C)")
        if open_browser:
            threading.Timer(0.8, lambda: webbrowser.open(url)).start()
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nPanel kapatıldı.")


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
