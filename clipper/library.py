"""Perpustakaan proyek & template merek (tersimpan di ~/.clipper)."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict, List

from .models import Style
from .paths import data_dir


# ------------------------------------------------------------------ proyek
def _projects_file() -> Path:
    return data_dir() / "projects.json"


def list_projects() -> List[dict]:
    try:
        items = json.loads(_projects_file().read_text(encoding="utf-8"))
    except Exception:
        return []
    return [i for i in items if Path(i.get("list_file", "")).exists()]


def register_project(list_file: Path, video: Path, n_clips: int) -> None:
    items = [i for i in list_projects() if i["list_file"] != str(list_file)]
    items.insert(0, {"name": video.stem, "video": str(video), "list_file": str(list_file),
                     "clips": n_clips, "updated": time.time()})
    _projects_file().write_text(json.dumps(items[:40], ensure_ascii=False, indent=1), encoding="utf-8")


# ------------------------------------------------------------------ template merek
def _tpl_dir() -> Path:
    d = data_dir() / "templates"
    d.mkdir(exist_ok=True)
    return d


def _tpl_path(name: str) -> Path:
    safe = "".join(c for c in name if c.isalnum() or c in " -_").strip() or "template"
    return _tpl_dir() / f"{safe}.json"


def list_templates() -> List[str]:
    return sorted(p.stem for p in _tpl_dir().glob("*.json"))


def save_template(name: str, st: Style) -> None:
    _tpl_path(name).write_text(json.dumps(st.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8")


def load_template(name: str) -> Style:
    return Style.from_dict(json.loads(_tpl_path(name).read_text(encoding="utf-8")))


def delete_template(name: str) -> None:
    _tpl_path(name).unlink(missing_ok=True)
