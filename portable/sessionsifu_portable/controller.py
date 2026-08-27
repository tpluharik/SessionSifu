"""Application-facing orchestration for capture, history and restore."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from . import VERSION
from .adapters import PlatformAdapter, select_adapter
from .archive import ArchiveManager
from .model import SessionSnapshot
from .recall import RecallStore
from .restore_journal import RestoreJournal
from .semantic import OfflineSemanticSearch
from .storage import SessionStore


class SessionController:
    version = VERSION

    def __init__(
        self,
        adapter: PlatformAdapter | None = None,
        store: SessionStore | None = None,
    ) -> None:
        self.adapter = adapter or select_adapter()
        self.store = store or SessionStore()
        self.recall_store = RecallStore(self.store.root)
        self.restore_journal = RestoreJournal(self.store.root)
        self.archive = ArchiveManager(self.store, self.recall_store)

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

    def _restore(
        self, session: SessionSnapshot, source: str, selected: set[str] | None = None
    ) -> dict[str, object]:
        plan = self.adapter.plan_restore(session)
        journal_id = self.restore_journal.begin(source, plan)
        try:
            result = self.adapter.restore(session, selected=selected)
            actions = list(result.get("actions") or [])
            self.restore_journal.finish(journal_id, actions=actions, summary=result)
            return {
                "applications": int(result.get("applications") or 0),
                "windows": int(result.get("windows") or 0),
            }
        except Exception as error:
            self.restore_journal.finish(
                journal_id, actions=[], summary={}, error=str(error)
            )
            raise

    def restore_named(self, name: str) -> dict[str, object]:
        return self._restore(self.store.load_named(name), f"named:{name}")

    def plan_named(self, name: str) -> list[dict[str, object]]:
        return self.adapter.plan_restore(self.store.load_named(name))

    def restore_named_selection(self, name: str, selected: set[str]) -> dict[str, object]:
        return self._restore(self.store.load_named(name), f"named:{name}", selected)

    def restore_path(self, path: Path) -> dict[str, object]:
        return self._restore(self.store.load(path), f"path:{path.name}")

    def plan_path(self, path: Path) -> list[dict[str, object]]:
        return self.adapter.plan_restore(self.store.load(path))

    def restore_path_selection(self, path: Path, selected: set[str]) -> dict[str, object]:
        return self._restore(self.store.load(path), f"path:{path.name}", selected)

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
        session = self.prepare_recall(include_file_paths=include_file_paths)
        window_previews: dict[int, bytes] = {}
        if visual_provider is not None:
            visual_result = visual_provider(session)
            preview, window_previews = visual_result[:2]
            if len(visual_result) > 2 and isinstance(visual_result[2], dict):
                session.capture_diagnostics.update(visual_result[2])
        return self.save_prepared_recall(
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

    def prepare_recall(self, *, include_file_paths: bool = False) -> SessionSnapshot:
        """Capture and enrich plain snapshot data before GUI-owned image grabs."""
        session = self.adapter.capture(include_files=include_file_paths)
        self.adapter.enrich_content(session)
        return session

    def save_prepared_recall(
        self,
        session: SessionSnapshot,
        *,
        retention_hours: int = 24,
        excluded_apps: list[str] | tuple[str, ...] = (),
        excluded_websites: list[str] | tuple[str, ...] = (),
        include_file_paths: bool = False,
        preview: bytes | None = None,
        window_previews: dict[int, bytes] | None = None,
        ocr_enabled: bool = False,
        sensitive_filter: bool = True,
        quota_mb: int = 512,
    ) -> Path:
        """Finalize an already captured snapshot without touching GUI objects."""
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

    def grouped_recall(self, *args, **kwargs) -> list[dict[str, object]]:
        return self.recall_store.group_scenes(self.search_recall(*args, **kwargs))

    def configure_semantic_model(self, path: str) -> dict[str, object]:
        self.recall_store.semantic = OfflineSemanticSearch(path)
        return self.recall_store.semantic.diagnostics()

    def annotate_recall(self, record: str, **changes) -> dict[str, object]:
        return self.recall_store.annotate(record, **changes)

    def reindex_recall(self, record: str) -> dict[str, object]:
        return self.recall_store.reindex(record)

    def recall_ocr_diagnostics(self, record: str) -> dict[str, object]:
        return self.recall_store.ocr_diagnostics(record)

    def ask_recall(self, question: str) -> dict[str, object]:
        return self.recall_store.ask(question)

    def export_archive(self, destination: Path, passphrase: str) -> dict[str, int]:
        return self.archive.export(destination, passphrase)

    def import_archive(self, source: Path, passphrase: str) -> dict[str, int]:
        return self.archive.import_archive(source, passphrase)

    def restore_journals(self) -> list[dict[str, object]]:
        return self.restore_journal.list()

    def retry_restore(self, journal_id: str) -> dict[str, object]:
        entry = self.restore_journal.get(journal_id)
        if not entry:
            raise ValueError("Restore journal entry is unavailable")
        source = str(entry.get("source") or "")
        if source.startswith("named:"):
            return self.restore_named(source.removeprefix("named:"))
        if source.startswith("path:"):
            filename = source.removeprefix("path:")
            candidates = [*self.store.list_history(), *self.store.list_named()]
            path = next((candidate for candidate in candidates if candidate.name == filename), None)
            if path:
                return self.restore_path(path)
        raise ValueError("The source session for this restore is no longer available")

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
            "privacy_recall": self.recall_store.diagnostics(),
            "restore_journals": len(self.restore_journal.list()),
        }
