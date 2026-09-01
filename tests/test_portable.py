#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(ROOT / "portable"))

from sessionsifu_portable.adapters.base import (  # noqa: E402
    AdapterCapabilities, PlatformAdapter, cached_process_snapshot,
)
from sessionsifu_portable.controller import SessionController  # noqa: E402
from sessionsifu_portable.capsule import CapsuleManager, CapsuleStore  # noqa: E402
from sessionsifu_portable.model import MonitorSnapshot, SessionSnapshot, WindowSnapshot  # noqa: E402
from sessionsifu_portable.mcp import ReadOnlyMcp  # noqa: E402
from sessionsifu_portable.recall import RecallStore  # noqa: E402
from sessionsifu_portable.semantic import OfflineSemanticSearch  # noqa: E402
from sessionsifu_portable.shortcut import parse_shortcut  # noqa: E402
from sessionsifu_portable.storage import HISTORY_LIMIT, SessionStore  # noqa: E402
from sessionsifu_portable.adapters.linux import GnomeAdapter, KDEAdapter, LinuxAdapter  # noqa: E402
from sessionsifu_portable.adapters.macos import MacOSAdapter  # noqa: E402
from sessionsifu_portable.adapters.windows import WindowsAdapter  # noqa: E402
from sessionsifu_portable.api import LocalApi  # noqa: E402
from sessionsifu_portable import SCHEMA_VERSION, VERSION  # noqa: E402


class FakeAdapter(PlatformAdapter):
    key = "test"
    desktop = "Test Desktop"
    capabilities = AdapterCapabilities(geometry=True)

    def __init__(self) -> None:
        self.applied = None
        self.last_include_files = None

    def capture_windows(self, include_files: bool = True) -> list[WindowSnapshot]:
        self.last_include_files = include_files
        return [
            WindowSnapshot(
                window_id="1",
                app_id="org.example.Editor",
                app_name="Editor",
                title="Notes",
                executable="/usr/bin/editor",
                command=["/usr/bin/editor"],
                geometry=[10, 20, 900, 700],
                open_files=["/home/test/Notes.txt"] if include_files else [],
            )
        ]

    def launch_window(self, window: WindowSnapshot) -> None:
        del window

    def apply_layout(self, session: SessionSnapshot) -> None:
        self.applied = session


class PortableTests(unittest.TestCase):
    def test_workspace_capsules_are_encrypted_bounded_and_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / "firefox"
            executable.write_text("test executable", encoding="utf-8")
            executable.chmod(0o700)
            store = CapsuleStore(root / "data", test_key=b"c" * 32)
            manager = CapsuleManager(store)
            path = manager.create("Research", "profile", [str(executable)])
            raw = path.read_bytes()
            self.assertNotIn(b"Research", raw)
            self.assertNotIn(str(executable).encode(), raw)
            self.assertEqual(store.load("Research").applications[0].identity, str(executable))
            plan = manager.preflight("Research")
            self.assertTrue(plan["supported"])
            self.assertFalse(plan["security_boundary"])
            self.assertIn("not a security sandbox", plan["warnings"][0])
            with mock.patch("sessionsifu_portable.capsule.subprocess.Popen") as launch:
                launch.return_value.pid = 4242
                launch.return_value.poll.return_value = None
                result = manager.launch("Research")
                running = manager.list_running()
            self.assertEqual(result["launched"], 1)
            self.assertEqual(result["launched_applications"][0]["pid"], 4242)
            self.assertEqual(running[0]["capsule"], "Research")
            self.assertEqual(running[0]["application"], str(executable))
            launch.return_value.poll.return_value = 0
            self.assertEqual(manager.list_running(), [])
            launch.assert_called_once()
            with self.assertRaises(ValueError):
                manager.create("../escape", "profile", [str(executable)])
            manager.create("Offline profile", "profile", [str(executable)], offline=True)
            self.assertFalse(manager.preflight("Offline profile")["supported"])

    def test_flatpak_capsule_preflight_uses_structured_offline_launch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = CapsuleManager(CapsuleStore(Path(directory), test_key=b"f" * 32))
            manager.create("Web", "flatpak", ["org.mozilla.firefox"], offline=True)
            completed = mock.Mock(returncode=0)
            with (
                mock.patch("sessionsifu_portable.capsule.platform.system", return_value="Linux"),
                mock.patch("sessionsifu_portable.capsule.shutil.which", return_value="/usr/bin/flatpak"),
                mock.patch("sessionsifu_portable.capsule.subprocess.run", return_value=completed) as probe,
            ):
                plan = manager.preflight("Web")
            self.assertTrue(plan["supported"])
            self.assertTrue(plan["security_boundary"])
            self.assertEqual(
                plan["commands"],
                [["/usr/bin/flatpak", "run", "--unshare=network", "org.mozilla.firefox"]],
            )
            probe.assert_called_once()

    def test_windows_sandbox_export_has_safe_defaults_and_read_only_folders(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manager = CapsuleManager(CapsuleStore(root / "data", test_key=b"w" * 32))
            manager.create(
                "Disposable",
                "windows-sandbox",
                [],
                offline=True,
                mapped_folders=[r"C:\Users\Example\Workspace"],
            )
            target = manager.export_windows_sandbox("Disposable", root / "Disposable.wsb")
            contents = target.read_text(encoding="utf-8")
            self.assertIn("<Networking>Disable</Networking>", contents)
            self.assertIn("<ClipboardRedirection>Disable</ClipboardRedirection>", contents)
            self.assertIn("<ProtectedClient>Enable</ProtectedClient>", contents)
            self.assertIn("<ReadOnly>true</ReadOnly>", contents)
            self.assertNotIn("LogonCommand", contents)

    def test_recall_shortcuts_are_normalized_for_all_platform_backends(self) -> None:
        shortcut = parse_shortcut("alt+control+r")
        self.assertEqual(shortcut.label, "Ctrl+Alt+R")
        self.assertEqual(shortcut.portal_trigger, "<Control><Alt>r")
        self.assertEqual(shortcut.windows_modifiers, 0x4003)
        self.assertEqual(shortcut.windows_key, ord("R"))
        self.assertEqual(shortcut.event_character, "r")
        self.assertEqual(parse_shortcut("super+shift+space").label, "Shift+Super+Space")
        with self.assertRaises(ValueError):
            parse_shortcut("Space")
        with self.assertRaises(ValueError):
            parse_shortcut("Ctrl+Escape")

    def test_all_platform_modules_import_without_side_effects(self) -> None:
        self.assertEqual(WindowsAdapter.key, "windows")
        self.assertEqual(MacOSAdapter.key, "macos")
        self.assertEqual(KDEAdapter.key, "kde-plasma")
        self.assertEqual(GnomeAdapter.key, "gnome-portable")
        self.assertEqual(LinuxAdapter.key, "linux")

    def test_model_round_trip_and_bounds(self) -> None:
        session = FakeAdapter().capture()
        restored = SessionSnapshot.from_dict(json.loads(json.dumps(session.to_dict())))
        self.assertEqual(restored.platform, "test")
        self.assertEqual(restored.windows[0].geometry, [10, 20, 900, 700])
        self.assertEqual(restored.windows[0].open_files, ["/home/test/Notes.txt"])
        self.assertEqual(VERSION, "3.5.11")
        self.assertEqual(restored.schema, SCHEMA_VERSION)

    def test_future_and_invalid_schemas_are_rejected(self) -> None:
        session = FakeAdapter().capture().to_dict()
        session["schema"] = SCHEMA_VERSION + 1
        with self.assertRaises(ValueError):
            SessionSnapshot.from_dict(session)
        session["schema"] = "not-a-version"
        with self.assertRaises(ValueError):
            SessionSnapshot.from_dict(session)

    def test_named_session_and_restore(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            adapter = FakeAdapter()
            controller = SessionController(adapter, SessionStore(Path(directory)))
            path = controller.save_named("Work")
            self.assertTrue(path.is_file())
            result = controller.restore_named("Work")
            self.assertEqual(result, {"applications": 1, "windows": 1})
            self.assertEqual(adapter.applied.windows[0].title, "Notes")

    def test_restore_preview_and_selection_are_application_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            adapter = FakeAdapter()
            controller = SessionController(adapter, SessionStore(Path(directory)))
            controller.save_named("Work")
            plan = controller.plan_named("Work")
            self.assertEqual(plan[0]["application"], "Editor")
            self.assertEqual(plan[0]["windows"], 1)
            result = controller.restore_named_selection(
                "Work", {str(plan[0]["identity"])}
            )
            self.assertEqual(result, {"applications": 1, "windows": 1})
            self.assertEqual(
                controller.restore_named_selection("Work", {"not-selected"}),
                {"applications": 0, "windows": 0},
            )
            self.assertEqual(adapter.applied.windows, [])

    def test_history_retains_five(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SessionStore(Path(directory))
            session = FakeAdapter().capture()
            for index in range(HISTORY_LIMIT + 3):
                session.captured_at = str(index)
                store.save_history(session)
            self.assertEqual(len(store.list_history()), HISTORY_LIMIT)

    def test_invalid_name_and_external_path_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SessionStore(Path(directory) / "data")
            with self.assertRaises(ValueError):
                store.save_named("../escape", FakeAdapter().capture())
            external = Path(directory) / "external.json"
            external.write_text("{}")
            with self.assertRaises(ValueError):
                store.load(external)

    def test_empty_capture_does_not_replace_history(self) -> None:
        class EmptyAdapter(FakeAdapter):
            def capture_windows(self, include_files: bool = True) -> list[WindowSnapshot]:
                del include_files
                return []

        with tempfile.TemporaryDirectory() as directory:
            store = SessionStore(Path(directory))
            store.save_history(FakeAdapter().capture())
            controller = SessionController(EmptyAdapter(), store)
            with self.assertRaises(RuntimeError):
                controller.save_history()
            self.assertEqual(len(store.list_history()), 1)

    def test_privacy_recall_is_sanitized_searchable_and_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = RecallStore(root)
            self.assertFalse(store.recall_dir.exists())
            session = FakeAdapter().capture()
            session.windows.append(
                WindowSnapshot(
                    app_id="org.example.SessionSifu.Helper",
                    app_name="SessionSifu Helper",
                    title="Must not be captured",
                    executable="/usr/bin/sessionsifu-helper",
                )
            )
            path = store.save(
                session,
                retention_hours=24,
                excluded_apps=["private-browser"],
                include_file_paths=False,
            )
            with self.assertRaises(UnicodeDecodeError):
                path.read_text()
            payload = store._load(path)
            self.assertEqual(payload["recall_schema"], 3)
            self.assertEqual(len(payload["windows"]), 1)
            self.assertNotIn("executable", payload["windows"][0])
            self.assertNotIn("command", payload["windows"][0])
            self.assertNotIn("open_files", payload["windows"][0])
            self.assertEqual(len(store.search("Notes")), 1)
            self.assertEqual(store.search("Must not be captured"), [])
            self.assertEqual(store.search("Notes", excluded_apps=["Editor"]), [])
            if os.name != "nt":
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)

            old = time.time() - (48 * 60 * 60)
            os.utime(path, (old, old))
            store.prune(24)
            self.assertFalse(path.exists())

    def test_privacy_recall_file_paths_require_separate_opt_in(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = RecallStore(Path(directory))
            path = store.save(FakeAdapter().capture(), include_file_paths=True)
            payload = store._load(path)
            self.assertEqual(payload["windows"][0]["open_files"], ["/home/test/Notes.txt"])
            self.assertEqual(store.search("Notes.txt")[0]["files"], ["/home/test/Notes.txt"])
            self.assertEqual(store.clear(), 1)
            self.assertEqual(store.search(), [])

    def test_privacy_recall_capture_does_not_inspect_files_without_opt_in(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            adapter = FakeAdapter()
            controller = SessionController(adapter, SessionStore(Path(directory)))
            path = controller.save_recall(include_file_paths=False)
            self.assertFalse(adapter.last_include_files)
            self.assertNotIn("open_files", controller.recall_store._load(path)["windows"][0])

            controller.save_recall(include_file_paths=True)
            self.assertTrue(adapter.last_include_files)

    def test_privacy_recall_encrypts_preview_and_supports_granular_delete(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = RecallStore(Path(directory))
            preview = b"not-a-real-jpeg-but-encrypted-preview-data"
            path = store.save(FakeAdapter().capture(), preview=preview)
            self.assertNotIn(b"Notes", path.read_bytes())
            self.assertEqual(store.preview_bytes(path.name), preview)
            self.assertEqual(store.delete(record=path.name), 1)
            self.assertEqual(store.search(), [])

    def test_privacy_recall_stores_exact_window_previews(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = RecallStore(Path(directory))
            session = FakeAdapter().capture()
            path = store.save(
                session,
                preview=b"desktop-preview",
                window_previews={0: b"exact-window-preview"},
            )
            payload = store._load(path)
            image_name = payload["windows"][0]["image"]
            self.assertEqual(
                store.preview_bytes(path.name, image_name=image_name),
                b"exact-window-preview",
            )
            result = store.search("Notes")[0]
            self.assertTrue(result["has_preview"])
            self.assertEqual(result["matched_window"]["image"], image_name)
            self.assertEqual(store.delete(record=path.name), 1)
            self.assertEqual(list(store.vault_dir.iterdir()), [])

    def test_privacy_recall_searches_each_window_image_ocr(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = RecallStore(Path(directory))
            store._ocr = lambda preview: (
                (
                    "quarterly falcon figures",
                    [{"t": "falcon", "x": 1000, "y": 2000,
                      "w": 2000, "h": 1000, "c": 92}],
                )
                if preview == b"exact-window-preview" else ("", [])
            )
            store.save(
                FakeAdapter().capture(),
                window_previews={0: b"exact-window-preview"},
                ocr_enabled=True,
            )
            result = store.search("falcon")[0]
            self.assertEqual(result["match_type"], "Window image text")
            self.assertIn("falcon", result["ocr_excerpt"])
            self.assertEqual(result["highlight_boxes"][0]["t"], "falcon")
            self.assertEqual(
                result["highlight_image"], result["matched_window"]["image"]
            )

    def test_identical_portable_images_reuse_encrypted_ocr_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = RecallStore(Path(directory))
            calls: list[bytes] = []

            def recognize(preview: bytes):
                calls.append(preview)
                return "reusable falcon text", [{
                    "t": "falcon", "x": 1, "y": 2, "w": 3, "h": 4, "c": 95,
                }]

            store._ocr = recognize
            for _index in range(2):
                store.save(
                    FakeAdapter().capture(),
                    preview=b"same-display",
                    window_previews={0: b"same-window"},
                    ocr_enabled=True,
                )
            self.assertEqual(calls, [b"same-window", b"same-display"])
            newest = store._load(store._paths()[0])
            self.assertTrue(newest["windows"][0]["ocr_diagnostics"]["reused"])
            self.assertTrue(newest["ocr_diagnostics"]["reused"])
            self.assertTrue(store.search("falcon"))

    def test_process_snapshot_cache_resolves_each_pid_once(self) -> None:
        cache = {}
        with mock.patch(
            "sessionsifu_portable.adapters.base.process_details",
            return_value=("/usr/bin/editor", ["editor"]),
        ) as details, mock.patch(
            "sessionsifu_portable.adapters.base.process_files",
            return_value=["/home/test/Notes.txt"],
        ) as files:
            first = cached_process_snapshot(cache, 42)
            second = cached_process_snapshot(cache, 42)
        self.assertEqual(first, second)
        details.assert_called_once_with(42, include_command=True)
        files.assert_called_once_with(42)

    def test_display_ocr_highlight_targets_display_overview(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = RecallStore(Path(directory))
            store._ocr = lambda preview: (
                (
                    "visible albatross status",
                    [{"t": "albatross", "x": 1800, "y": 2200,
                      "w": 2400, "h": 900, "c": 94}],
                )
                if preview == b"display-preview" else ("", [])
            )
            store.save(
                FakeAdapter().capture(),
                preview=b"display-preview",
                ocr_enabled=True,
            )
            result = next(
                item for item in store.search("albatross")
                if item["result_kind"] == "visual"
            )
            self.assertEqual(result["highlight_image"], "")
            self.assertEqual(result["highlight_boxes"][0]["t"], "albatross")

    def test_excluded_app_pixels_are_not_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = RecallStore(Path(directory))
            session = FakeAdapter().capture()
            session.windows.append(
                WindowSnapshot(
                    app_id="org.example.Browser",
                    app_name="Browser",
                    title="Public research",
                )
            )
            path = store.save(
                session,
                excluded_apps=["Editor"],
                preview=b"desktop-with-private-window",
                window_previews={
                    0: b"private-window-preview",
                    1: b"public-window-preview",
                },
            )
            payload = store._load(path)
            self.assertEqual(payload["image"], "")
            self.assertEqual(len(payload["windows"]), 1)
            image_name = payload["windows"][0]["image"]
            self.assertEqual(
                store.preview_bytes(path.name, image_name=image_name),
                b"public-window-preview",
            )
            self.assertEqual(len(list(store.vault_dir.iterdir())), 2)
            self.assertNotIn(
                b"private-window-preview",
                b"".join(item.read_bytes() for item in store.vault_dir.iterdir()),
            )

    def test_privacy_recall_filters_sensitive_text_and_excluded_websites(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = RecallStore(Path(directory))
            session = FakeAdapter().capture()
            session.windows[0].title = "Account 4111 1111 1111 1111"
            with self.assertRaises(RuntimeError):
                store.save(session)
            session.windows[0].title = "https://secure.bank.example/account"
            with self.assertRaises(RuntimeError):
                store.save(session, excluded_websites=["bank.example"])
            self.assertEqual(store.search(), [])

    def test_privacy_recall_related_search_and_website_delete(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = RecallStore(Path(directory))
            session = FakeAdapter().capture()
            session.windows[0].title = "Project planning https://docs.example/roadmap"
            store.save(session)
            self.assertEqual(len(store.search("project planning", semantic=True)), 1)
            self.assertEqual(store.delete(website="docs.example"), 1)
            self.assertEqual(store.search(), [])

    def test_privacy_recall_search_redacts_apps_from_existing_entries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = RecallStore(Path(directory))
            session = FakeAdapter().capture()
            session.windows.append(
                WindowSnapshot(
                    app_id="org.example.Browser",
                    app_name="Browser",
                    title="Public research",
                )
            )
            store.save(session, preview=b"encrypted-shared-display")
            result = store.search("", excluded_apps=["Editor"])
            self.assertEqual(result[0]["apps"], ["Browser"])
            self.assertEqual(result[0]["titles"], ["Public research"])
            self.assertEqual(store.search("Notes", excluded_apps=["Editor"]), [])
            self.assertFalse(result[0]["has_preview"])

    def test_privacy_recall_search_returns_individual_window_moments(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = RecallStore(Path(directory))
            session = FakeAdapter().capture()
            session.windows[0].title = "Project notes"
            session.windows.append(
                WindowSnapshot(
                    app_id="org.example.Browser",
                    app_name="Browser",
                    title="Project research",
                    geometry=[920, 20, 900, 700],
                )
            )
            session.windows.append(
                WindowSnapshot(
                    app_id="org.example.VisualStudioBrowser",
                    app_name="Visual Studio Browser",
                    title="Project code",
                )
            )
            store.save(session)
            results = store.search("Project", semantic=True)
            self.assertEqual(len(results), 3)
            self.assertTrue(all(item["result_kind"] == "window" for item in results))
            self.assertEqual(
                {item["matched_window"]["app_name"] for item in results},
                {"Editor", "Browser", "Visual Studio Browser"},
            )
            browser = store.search("Project", app="Browser", semantic=True)
            self.assertEqual(len(browser), 1)
            self.assertEqual(browser[0]["apps"], ["Browser"])

    def test_recall_search_reuses_memory_only_index_across_worker_threads(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = RecallStore(Path(directory))
            store.save(FakeAdapter().capture())
            results: list[list[dict]] = []
            first = threading.Thread(
                target=lambda: results.append(store.search("Notes"))
            )
            first.start()
            first.join(timeout=5)
            connection = store._index_connection
            second = threading.Thread(
                target=lambda: results.append(store.search("Editor"))
            )
            second.start()
            second.join(timeout=5)
            self.assertFalse(first.is_alive())
            self.assertFalse(second.is_alive())
            self.assertTrue(all(results))
            self.assertIs(store._index_connection, connection)

    def test_semantic_search_caches_document_vectors(self) -> None:
        class FakeModel:
            def __init__(self) -> None:
                self.batches: list[list[str]] = []

            def encode(self, values, **_kwargs):
                batch = list(values)
                self.batches.append(batch)
                return [[1.0, 0.0] if "alpha" in value else [0.0, 1.0] for value in batch]

        search = OfflineSemanticSearch()
        model = FakeModel()
        search._model = model
        documents = {"one": "alpha project", "two": "beta research"}
        self.assertIn("one", search.rank("alpha", documents))
        self.assertIn("one", search.rank("alpha update", documents))
        self.assertEqual([len(batch) for batch in model.batches], [2, 1, 1])
        self.assertEqual(search.diagnostics()["cached_documents"], 2)

    def test_accessible_text_deep_targets_and_capture_completeness(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = RecallStore(Path(directory))
            session = FakeAdapter().capture()
            session.windows[0].accessible_text = "Quarterly narwhal forecast"
            session.windows[0].deep_targets = ["vscode://file/home/test/Notes.txt"]
            session.windows.append(WindowSnapshot(
                app_id="org.example.Browser",
                app_name="Browser",
                title="Private Browsing",
                capture_protection="private browsing",
            ))
            session.capture_diagnostics = {"screenshots_enabled": True}
            path = store.save(
                session,
                preview=b"shared-display",
                window_previews={0: b"editor", 1: b"private"},
            )
            payload = store._load(path)
            self.assertEqual(len(payload["windows"]), 1)
            self.assertEqual(payload["image"], "")
            self.assertEqual(payload["capture_diagnostics"]["captured_window_images"], 1)
            self.assertEqual(payload["capture_diagnostics"]["protected_windows"], 1)
            result = store.search("narwhal")[0]
            self.assertEqual(result["match_type"], "Application content")
            self.assertEqual(result["targets"], ["vscode://file/home/test/Notes.txt"])
            self.assertTrue(result["privacy"]["protected_context_visible"])

    def test_local_api_is_read_only_and_returns_bounded_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            controller = SessionController(FakeAdapter(), SessionStore(Path(directory)))
            controller.save_named("Work")
            api = LocalApi(controller)
            status = api.dispatch({"method": "status"})
            self.assertEqual(status["version"], "3.5.11")
            preview = api.dispatch({"method": "restore.preview", "params": {"name": "Work"}})
            self.assertEqual(preview["applications"][0]["application"], "Editor")
            with self.assertRaises(ValueError):
                api.dispatch({"method": "restore.execute", "params": {"name": "Work"}})

    def test_restore_journal_records_actions_and_can_be_retried(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            controller = SessionController(FakeAdapter(), SessionStore(Path(directory)))
            controller.save_named("Work")
            controller.restore_named("Work")
            entry = controller.restore_journals()[0]
            self.assertEqual(entry["state"], "completed")
            self.assertEqual(entry["source"], "named:Work")
            self.assertTrue(entry["actions"])
            self.assertEqual(controller.retry_restore(str(entry["id"])), {"applications": 1, "windows": 1})

    def test_semantic_search_annotations_scenes_and_ask_are_local(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = RecallStore(Path(directory))
            session = FakeAdapter().capture()
            path = store.save(session, window_previews={0: b"window"})
            store.annotate(path.name, bookmarked=True, collection="Research", note="Quarterly plan")
            store.semantic.rank = lambda query, documents: {next(iter(documents)): 0.9}
            result = store.search("conceptual query", semantic=True)[0]
            self.assertEqual(result["match_type"], "Semantic match")
            self.assertTrue(result["annotations"]["bookmarked"])
            result["scene_id"] = "0123456789abcdef"
            self.assertEqual(store.group_scenes([result, result])[0]["scene_count"], 2)
            answer = store.ask("conceptual query")
            self.assertTrue(answer["citations"])

    def test_encrypted_archive_round_trip_and_wrong_password(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = SessionController(FakeAdapter(), SessionStore(root / "source"))
            source.save_named("Work")
            source.recall_store.save(FakeAdapter().capture(), window_previews={0: b"preview"})
            archive = root / "transfer.ssxa"
            source.export_archive(archive, "correct horse battery staple")
            destination = SessionController(FakeAdapter(), SessionStore(root / "destination"))
            with self.assertRaises(ValueError):
                destination.import_archive(archive, "incorrect passphrase")
            counts = destination.import_archive(archive, "correct horse battery staple")
            self.assertEqual(counts["sessions"], 1)
            self.assertEqual(counts["recall"], 1)

    def test_monitor_topology_mapping_clamps_windows_to_available_display(self) -> None:
        saved = [MonitorSnapshot("external", "External", [1920, 0, 2560, 1440])]
        current = [MonitorSnapshot("laptop", "Laptop", [0, 0, 1920, 1080], primary=True)]
        geometry = PlatformAdapter.reconcile_geometry([2200, 100, 1200, 900], "external", saved, current)
        self.assertGreaterEqual(geometry[0], 0)
        self.assertGreaterEqual(geometry[1], 0)
        self.assertLessEqual(geometry[0] + geometry[2], 1920)
        self.assertLessEqual(geometry[1] + geometry[3], 1080)

    def test_mcp_surface_is_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            controller = SessionController(FakeAdapter(), SessionStore(Path(directory)))
            controller.save_named("Work")
            mcp = ReadOnlyMcp(controller)
            self.assertEqual(mcp.dispatch({"jsonrpc": "2.0", "id": 1, "method": "initialize"})["result"]["serverInfo"]["version"], "3.5.11")
            self.assertTrue(mcp.call("restore_preview", {"name": "Work"}))
            with self.assertRaises(ValueError):
                mcp.call("restore_execute", {"name": "Work"})


if __name__ == "__main__":
    unittest.main()
