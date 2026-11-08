"""data/ klasöründeki JSON kayıtları. Dosyalar yalnızca içerik değiştiğinde yazılır;
böylece Git'te gereksiz kayıt (commit) oluşmaz."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path


def dumps(data) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=False) + "\n"


class Store:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.events_dir = self.root / "events"
        self.rules_dir = self.root / "rules"

    # -- temel okuma/yazma ---------------------------------------------------

    def path(self, name: str) -> Path:
        return self.root / name

    def read(self, name: str, default):
        p = self.path(name)
        if not p.exists():
            return default
        with p.open(encoding="utf-8") as fh:
            return json.load(fh)

    def write(self, name: str, data) -> bool:
        return self._write_path(self.path(name), data)

    @staticmethod
    def _write_path(path: Path, data) -> bool:
        text = dumps(data)
        if path.exists() and path.read_text(encoding="utf-8") == text:
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(text, encoding="utf-8", newline="\n")  # Windows'ta da LF: Git'te sahte fark oluşmaz
        for attempt in range(5):
            try:
                os.replace(tmp, path)
                break
            except PermissionError:  # Windows: dosya o an başka bir programda açıksa kısa bekle
                if attempt == 4:
                    raise
                time.sleep(0.2)
        return True

    @property
    def exists(self) -> bool:
        return self.path("state.json").exists()

    # -- olaylar ve kurallar ------------------------------------------------

    def _load_dir(self, folder: Path) -> dict[str, dict]:
        out: dict[str, dict] = {}
        if not folder.exists():
            return out
        for p in sorted(folder.glob("*.json")):
            with p.open(encoding="utf-8") as fh:
                item = json.load(fh)
            out[item["id"]] = item
        return out

    def load_events(self) -> dict[str, dict]:
        return self._load_dir(self.events_dir)

    def save_events(self, events: dict[str, dict]) -> int:
        return sum(self._write_path(self.events_dir / f"{eid}.json", ev) for eid, ev in events.items())

    def load_rules(self) -> dict[str, dict]:
        return self._load_dir(self.rules_dir)

    def save_rules(self, rules: dict[str, dict]) -> int:
        return sum(self._write_path(self.rules_dir / f"{rid}.json", r) for rid, r in rules.items())
