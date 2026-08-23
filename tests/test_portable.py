#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(ROOT / "portable"))

from sessionsifu_portable.adapters.base import AdapterCapabilities, PlatformAdapter  # noqa: E402
from sessionsifu_portable.controller import SessionController  # noqa: E402
from sessionsifu_portable.model import SessionSnapshot, WindowSnapshot  # noqa: E402
from sessionsifu_portable.recall import RecallStore  # noqa: E402
from sessionsifu_portable.shortcut import parse_shortcut  # noqa: E402
from sessionsifu_portable.storage import HISTORY_LIMIT, SessionStore  # noqa: E402
from sessionsifu_portable.adapters.linux import GnomeAdapter, KDEAdapter, LinuxAdapter  # noqa: E402
from sessionsifu_portable.adapters.macos import MacOSAdapter  # noqa: E402
from sessionsifu_portable.adapters.windows import WindowsAdapter  # noqa: E402
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
        self.assertEqual(VERSION, "3.1.7")
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


if __name__ == "__main__":
    unittest.main()
