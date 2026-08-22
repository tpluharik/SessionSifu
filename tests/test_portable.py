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
        self.assertEqual(VERSION, "2.3.0")
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
            payload = json.loads(path.read_text())
            self.assertEqual(payload["recall_schema"], 1)
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
            payload = json.loads(path.read_text())
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
            self.assertNotIn("open_files", json.loads(path.read_text())["windows"][0])

            controller.save_recall(include_file_paths=True)
            self.assertTrue(adapter.last_include_files)

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
            store.save(session)
            result = store.search("", excluded_apps=["Editor"])
            self.assertEqual(result[0]["apps"], ["Browser"])
            self.assertEqual(result[0]["titles"], ["Public research"])
            self.assertEqual(store.search("Notes", excluded_apps=["Editor"]), [])


if __name__ == "__main__":
    unittest.main()
