"""Application-facing orchestration for capture, history and restore."""

from __future__ import annotations

from pathlib import Path

from .adapters import PlatformAdapter, select_adapter
from .storage import SessionStore


class SessionController:
    def __init__(
        self,
        adapter: PlatformAdapter | None = None,
        store: SessionStore | None = None,
    ) -> None:
        self.adapter = adapter or select_adapter()
        self.store = store or SessionStore()

    def save_named(self, name: str) -> Path:
        session = self.adapter.capture()
        if not session.windows:
            raise RuntimeError(
                "No restorable windows were visible to this platform backend; the previous session was not replaced."
            )
        return self.store.save_named(name, session)

    def save_history(self) -> Path:
        session = self.adapter.capture()
        if not session.windows:
            raise RuntimeError(
                "No restorable windows were visible to this platform backend; history was left unchanged."
            )
        return self.store.save_history(session)

    def restore_named(self, name: str) -> dict[str, int]:
        return self.adapter.restore(self.store.load_named(name))

    def restore_path(self, path: Path) -> dict[str, int]:
        return self.adapter.restore(self.store.load(path))

    def named_sessions(self) -> list[Path]:
        return self.store.list_named()

    def history(self) -> list[Path]:
        return self.store.list_history()

    def diagnostics(self) -> dict[str, object]:
        return {
            **self.adapter.diagnostics(),
            "storage": str(self.store.root),
            "named_sessions": len(self.named_sessions()),
            "history_snapshots": len(self.history()),
        }
