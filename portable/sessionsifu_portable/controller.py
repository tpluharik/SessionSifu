"""Application-facing orchestration for capture, history and restore."""

from __future__ import annotations

from pathlib import Path

from .adapters import PlatformAdapter, select_adapter
from .recall import RecallStore
from .storage import SessionStore


class SessionController:
    def __init__(
        self,
        adapter: PlatformAdapter | None = None,
        store: SessionStore | None = None,
    ) -> None:
        self.adapter = adapter or select_adapter()
        self.store = store or SessionStore()
        self.recall_store = RecallStore(self.store.root)

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

    def save_recall(
        self,
        *,
        retention_hours: int = 24,
        excluded_apps: list[str] | tuple[str, ...] = (),
        include_file_paths: bool = False,
    ) -> Path:
        session = self.adapter.capture(include_files=include_file_paths)
        return self.recall_store.save(
            session,
            retention_hours=retention_hours,
            excluded_apps=excluded_apps,
            include_file_paths=include_file_paths,
        )

    def search_recall(self, query: str = "") -> list[dict[str, object]]:
        return self.recall_store.search(query)

    def clear_recall(self) -> int:
        return self.recall_store.clear()

    def diagnostics(self) -> dict[str, object]:
        return {
            **self.adapter.diagnostics(),
            "storage": str(self.store.root),
            "named_sessions": len(self.named_sessions()),
            "history_snapshots": len(self.history()),
            "privacy_recall_entries": len(self.search_recall()),
        }
