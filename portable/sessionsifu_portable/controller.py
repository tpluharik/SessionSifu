"""Application-facing orchestration for capture, history and restore."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from .adapters import PlatformAdapter, select_adapter
from .model import SessionSnapshot
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

    def plan_named(self, name: str) -> list[dict[str, object]]:
        return self.adapter.plan_restore(self.store.load_named(name))

    def restore_named_selection(self, name: str, selected: set[str]) -> dict[str, int]:
        return self.adapter.restore(self.store.load_named(name), selected=selected)

    def restore_path(self, path: Path) -> dict[str, int]:
        return self.adapter.restore(self.store.load(path))

    def plan_path(self, path: Path) -> list[dict[str, object]]:
        return self.adapter.plan_restore(self.store.load(path))

    def restore_path_selection(self, path: Path, selected: set[str]) -> dict[str, int]:
        return self.adapter.restore(self.store.load(path), selected=selected)

    def named_sessions(self) -> list[Path]:
        return self.store.list_named()

    def history(self) -> list[Path]:
        return self.store.list_history()

    def save_recall(
        self,
        *,
        retention_hours: int = 24,
        excluded_apps: list[str] | tuple[str, ...] = (),
        excluded_websites: list[str] | tuple[str, ...] = (),
        include_file_paths: bool = False,
        preview: bytes | None = None,
        visual_provider: Callable[
            [SessionSnapshot], tuple
        ] | None = None,
        ocr_enabled: bool = False,
        sensitive_filter: bool = True,
        quota_mb: int = 512,
    ) -> Path:
        session = self.adapter.capture(include_files=include_file_paths)
        self.adapter.enrich_content(session)
        window_previews: dict[int, bytes] = {}
        if visual_provider is not None:
            visual_result = visual_provider(session)
            preview, window_previews = visual_result[:2]
            if len(visual_result) > 2 and isinstance(visual_result[2], dict):
                session.capture_diagnostics.update(visual_result[2])
        return self.recall_store.save(
            session,
            retention_hours=retention_hours,
            excluded_apps=excluded_apps,
            excluded_websites=excluded_websites,
            include_file_paths=include_file_paths,
            preview=preview,
            window_previews=window_previews,
            ocr_enabled=ocr_enabled,
            sensitive_filter=sensitive_filter,
            quota_mb=quota_mb,
        )

    def search_recall(
        self,
        query: str = "",
        excluded_apps: list[str] | tuple[str, ...] = (),
        *,
        app: str = "",
        semantic: bool = False,
    ) -> list[dict[str, object]]:
        return self.recall_store.search(
            query, excluded_apps=excluded_apps, app=app, semantic=semantic
        )

    def clear_recall(self) -> int:
        return self.recall_store.clear()

    def delete_recall(
        self, *, record: str = "", app: str = "", website: str = ""
    ) -> int:
        return self.recall_store.delete(record=record, app=app, website=website)

    def diagnostics(self) -> dict[str, object]:
        return {
            **self.adapter.diagnostics(),
            "storage": str(self.store.root),
            "named_sessions": len(self.named_sessions()),
            "history_snapshots": len(self.history()),
            "privacy_recall_entries": self.recall_store.entry_count(),
        }
