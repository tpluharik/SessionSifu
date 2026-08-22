"""Privacy-first, local-only activity recall storage.

The initial implementation intentionally records sanitized observable desktop
metadata rather than screenshots.  Visual capture stays unavailable until the
project can provide OS-backed encryption and reliable sensitive-content
exclusions on every supported platform.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .model import SessionSnapshot, WindowSnapshot

RECALL_SCHEMA = 1
RECALL_MAX_ENTRIES = 500
MAX_RECALL_BYTES = 2 * 1024 * 1024
DEFAULT_RETENTION_HOURS = 24
DEFAULT_EXCLUSIONS = ("sessionsifu",)


def _private_mode(path: Path, mode: int) -> None:
    try:
        path.chmod(mode)
    except OSError:
        # Windows applies access control through the user's profile directory.
        pass


def _matches_exclusion(window: WindowSnapshot, exclusions: tuple[str, ...]) -> bool:
    identity = "\n".join((window.app_id, window.app_name, Path(window.executable).name)).casefold()
    return any(token and token in identity for token in exclusions)


class RecallStore:
    """Bounded metadata timeline stored below SessionSifu's private data root."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.recall_dir = root / "recall"

    def _ensure_directory(self) -> None:
        if self.recall_dir.is_symlink():
            raise ValueError("Refusing to use a symbolic link for Privacy Recall storage")
        self.recall_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        _private_mode(self.recall_dir, 0o700)

    @staticmethod
    def _exclusions(values: list[str] | tuple[str, ...]) -> tuple[str, ...]:
        normalized = {token.strip().casefold()[:256] for token in (*DEFAULT_EXCLUSIONS, *values)}
        return tuple(sorted(token for token in normalized if token))

    def save(
        self,
        session: SessionSnapshot,
        *,
        retention_hours: int = DEFAULT_RETENTION_HOURS,
        excluded_apps: list[str] | tuple[str, ...] = (),
        include_file_paths: bool = False,
    ) -> Path:
        self._ensure_directory()
        exclusions = self._exclusions(excluded_apps)
        windows = []
        for window in session.windows:
            if _matches_exclusion(window, exclusions):
                continue
            item = {
                "app_id": window.app_id,
                "app_name": window.app_name,
                "title": window.title,
                "geometry": list(window.geometry),
                "workspace": window.workspace,
                "monitor": window.monitor,
            }
            if include_file_paths:
                item["open_files"] = list(window.open_files)
            windows.append(item)
        if not windows:
            raise RuntimeError("No non-excluded windows were available for Privacy Recall")

        payload = {
            "recall_schema": RECALL_SCHEMA,
            "captured_at": session.captured_at,
            "platform": session.platform,
            "desktop": session.desktop,
            "include_file_paths": bool(include_file_paths),
            "windows": windows,
        }
        contents = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        if len(contents.encode("utf-8")) > MAX_RECALL_BYTES:
            raise ValueError("Privacy Recall entry is too large to store safely")

        stamp = datetime.now(timezone.utc).strftime("recall-%Y%m%d-%H%M%S-%f")
        path = self.recall_dir / f"{stamp}.json"
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=self.recall_dir, delete=False
        ) as output:
            output.write(contents)
            temporary = Path(output.name)
        try:
            _private_mode(temporary, 0o600)
            os.replace(temporary, path)
            _private_mode(path, 0o600)
        finally:
            temporary.unlink(missing_ok=True)
        self.prune(retention_hours)
        return path

    def _paths(self) -> list[Path]:
        if not self.recall_dir.is_dir() or self.recall_dir.is_symlink():
            return []
        return sorted(
            (
                path
                for path in self.recall_dir.glob("recall-*.json")
                if path.is_file() and not path.is_symlink()
            ),
            key=lambda path: path.stat().st_mtime_ns,
            reverse=True,
        )

    def prune(self, retention_hours: int) -> None:
        hours = max(1, min(24 * 30, int(retention_hours)))
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        for index, path in enumerate(self._paths()):
            modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
            if index >= RECALL_MAX_ENTRIES or modified < cutoff:
                path.unlink(missing_ok=True)

    @staticmethod
    def _load_summary(path: Path) -> dict[str, object] | None:
        try:
            if path.stat().st_size > MAX_RECALL_BYTES:
                return None
            payload = json.loads(path.read_text(encoding="utf-8"))
            if int(payload.get("recall_schema", 0)) != RECALL_SCHEMA:
                return None
            raw_windows = payload.get("windows")
            if not isinstance(raw_windows, list):
                return None
            apps: list[str] = []
            titles: list[str] = []
            files: list[str] = []
            search_parts: list[str] = []
            for item in raw_windows[:512]:
                if not isinstance(item, dict):
                    continue
                app = str(item.get("app_name") or item.get("app_id") or "")[:512]
                title = str(item.get("title") or "")[:4096]
                paths = [str(value)[:4096] for value in list(item.get("open_files") or [])[:32]]
                if app and app not in apps:
                    apps.append(app)
                if title and title not in titles:
                    titles.append(title)
                for value in paths:
                    if value and value not in files:
                        files.append(value)
                search_parts.extend((app, title, *paths))
            return {
                "name": path.name,
                "captured_at": str(payload.get("captured_at") or "")[:128],
                "apps": apps,
                "titles": titles,
                "files": files,
                "search_text": "\n".join(search_parts).casefold(),
            }
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return None

    def search(self, query: str = "", limit: int = 100) -> list[dict[str, object]]:
        needle = query.strip().casefold()[:256]
        results = []
        for path in self._paths():
            summary = self._load_summary(path)
            if summary is None or (needle and needle not in summary.pop("search_text")):
                continue
            summary.pop("search_text", None)
            results.append(summary)
            if len(results) >= max(1, min(100, int(limit))):
                break
        return results

    def clear(self) -> int:
        removed = 0
        for path in self._paths():
            path.unlink(missing_ok=True)
            removed += 1
        return removed
