from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


def _safe_subject_key(value: str | None) -> str:
    raw = str(value or "anonymous").strip() or "anonymous"
    return re.sub(r"[^A-Za-z0-9_.@-]+", "_", raw)[:96] or "anonymous"


def workspace_root_for_user(base_workdir: str | Path, user_id: str | None) -> Path:
    base = Path(base_workdir).resolve()
    key = _safe_subject_key(user_id)
    return base / "anonymous" if key == "anonymous" else base / "users" / key


@dataclass(frozen=True, slots=True)
class WorkspacePaths:
    root: Path

    def __init__(self, root: str | Path):
        object.__setattr__(self, "root", Path(root).resolve())

    @property
    def uploads(self) -> Path:
        return self.root / "uploads"

    @property
    def plots(self) -> Path:
        return self.root / "plots"

    @property
    def derived(self) -> Path:
        return self.root / "derived"

    @property
    def temp(self) -> Path:
        return self.root / "temp"

    @property
    def exports(self) -> Path:
        return self.root / "exports"

    @property
    def database(self) -> Path:
        return self.root / "workspace.db"

    def ensure(self) -> "WorkspacePaths":
        self.root.mkdir(parents=True, exist_ok=True)
        for path in (self.uploads, self.plots, self.derived, self.temp, self.exports):
            path.mkdir(parents=True, exist_ok=True)
        return self
