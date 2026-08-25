"""Bounded, crash-safe owner-private restore operation journal."""

from __future__ import annotations

import json
import os
import tempfile
import time
import uuid
from pathlib import Path

MAX_JOURNAL_ENTRIES = 25
MAX_JOURNAL_BYTES = 2 * 1024 * 1024


class RestoreJournal:
    def __init__(self, root: Path) -> None:
        self.directory = root / "restore-journal"

    def _ensure(self) -> None:
        if self.directory.is_symlink():
            raise ValueError("Refusing symbolic-link restore journal storage")
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.directory.chmod(0o700)

    def begin(self, source: str, plan: list[dict[str, object]]) -> str:
        self._ensure()
        identifier = f"restore-{int(time.time())}-{uuid.uuid4().hex[:12]}"
        self._write(identifier, {
            "id": identifier,
            "state": "in-progress",
            "source": str(source)[:512],
            "started_at": time.time(),
            "finished_at": 0,
            "plan": plan[:512],
            "actions": [],
            "summary": {},
        })
        self._prune()
        return identifier

    def finish(
        self,
        identifier: str,
        *,
        actions: list[dict[str, object]],
        summary: dict[str, object],
        error: str = "",
    ) -> None:
        current = self.get(identifier) or {"id": identifier, "started_at": time.time()}
        current.update({
            "state": "failed" if error else "completed",
            "finished_at": time.time(),
            "actions": actions[:1024],
            "summary": summary,
            "error": str(error)[:1024],
        })
        self._write(identifier, current)

    def _path(self, identifier: str) -> Path:
        if not identifier.startswith("restore-") or not identifier.replace("-", "").isalnum():
            raise ValueError("Invalid restore journal identifier")
        return self.directory / f"{identifier}.json"

    def _write(self, identifier: str, value: dict[str, object]) -> None:
        self._ensure()
        payload = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        if len(payload) > MAX_JOURNAL_BYTES:
            raise ValueError("Restore journal entry exceeds the safety limit")
        descriptor, name = tempfile.mkstemp(prefix=".restore-", dir=self.directory)
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(payload)
                output.flush()
                os.fsync(output.fileno())
            temporary.chmod(0o600)
            os.replace(temporary, self._path(identifier))
            self._path(identifier).chmod(0o600)
        finally:
            temporary.unlink(missing_ok=True)

    def get(self, identifier: str) -> dict[str, object] | None:
        try:
            path = self._path(identifier)
            if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_JOURNAL_BYTES:
                return None
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else None
        except (OSError, ValueError, json.JSONDecodeError):
            return None

    def list(self) -> list[dict[str, object]]:
        if not self.directory.is_dir() or self.directory.is_symlink():
            return []
        values = []
        for path in sorted(
            self.directory.glob("restore-*.json"),
            key=lambda candidate: candidate.stat().st_mtime_ns,
            reverse=True,
        )[:MAX_JOURNAL_ENTRIES]:
            value = self.get(path.stem)
            if value:
                values.append(value)
        return values

    def _prune(self) -> None:
        paths = sorted(
            self.directory.glob("restore-*.json"),
            key=lambda candidate: candidate.stat().st_mtime_ns,
            reverse=True,
        )
        for path in paths[MAX_JOURNAL_ENTRIES:]:
            if path.is_file() and not path.is_symlink():
                path.unlink(missing_ok=True)
