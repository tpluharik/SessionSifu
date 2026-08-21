"""Atomic local-only storage for named sessions and rolling history."""

from __future__ import annotations

import json
import os
import platform
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .model import SessionSnapshot

HISTORY_LIMIT = 5
MAX_SESSION_BYTES = 16 * 1024 * 1024
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,63}$")


def default_data_dir() -> Path:
    system = platform.system()
    if system == "Windows":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming")) / "SessionSifu"
    if system == "Darwin":
        return Path.home() / "Library/Application Support/SessionSifu"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "sessionsifu-portable"


class SessionStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or default_data_dir()
        self.named_dir = self.root / "sessions"
        self.history_dir = self.root / "history"
        self.named_dir.mkdir(parents=True, exist_ok=True)
        self.history_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def validate_name(name: str) -> str:
        name = name.strip()
        if not NAME_RE.fullmatch(name):
            raise ValueError("Session names may use letters, numbers, spaces, dots, dashes and underscores")
        return name

    @staticmethod
    def _write(path: Path, session: SessionSnapshot) -> Path:
        payload = json.dumps(session.to_dict(), ensure_ascii=False, indent=2) + "\n"
        if len(payload.encode("utf-8")) > MAX_SESSION_BYTES:
            raise ValueError("Session is too large to store safely")
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as output:
            output.write(payload)
            temporary = Path(output.name)
        try:
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        return path

    def save_named(self, name: str, session: SessionSnapshot) -> Path:
        return self._write(self.named_dir / f"{self.validate_name(name)}.json", session)

    def save_history(self, session: SessionSnapshot) -> Path:
        stamp = datetime.now(timezone.utc).strftime("auto-%Y%m%d-%H%M%S-%f")
        path = self.history_dir / f"{stamp}.json"
        collision = 0
        while path.exists():
            collision += 1
            path = self.history_dir / f"{stamp}-{collision}.json"
        path = self._write(path, session)
        for old in self.list_history()[HISTORY_LIMIT:]:
            old.unlink(missing_ok=True)
        return path

    def _list(self, directory: Path) -> list[Path]:
        return sorted(
            (path for path in directory.glob("*.json") if path.is_file() and not path.is_symlink()),
            key=lambda path: path.stat().st_mtime_ns,
            reverse=True,
        )

    def list_named(self) -> list[Path]:
        return self._list(self.named_dir)

    def list_history(self) -> list[Path]:
        return self._list(self.history_dir)

    def load(self, path: Path) -> SessionSnapshot:
        if path.is_symlink():
            raise ValueError("Refusing to load a symbolic link")
        resolved = path.resolve()
        allowed = (self.named_dir.resolve(), self.history_dir.resolve())
        if not any(resolved.parent == directory for directory in allowed):
            raise ValueError("Session path is outside SessionSifu storage")
        if not resolved.is_file():
            raise ValueError("Session file is unavailable")
        if resolved.stat().st_size > MAX_SESSION_BYTES:
            raise ValueError("Session file is too large")
        return SessionSnapshot.from_dict(json.loads(resolved.read_text(encoding="utf-8")))

    def load_named(self, name: str) -> SessionSnapshot:
        return self.load(self.named_dir / f"{self.validate_name(name)}.json")

    def delete_named(self, name: str) -> None:
        path = self.named_dir / f"{self.validate_name(name)}.json"
        if path.is_symlink():
            raise ValueError("Refusing to remove a symbolic link")
        path.unlink(missing_ok=True)
