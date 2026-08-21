#!/usr/bin/env python3
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(ROOT / "portable"))

from sessionsifu_portable.adapters.base import AdapterCapabilities, PlatformAdapter  # noqa: E402
from sessionsifu_portable.controller import SessionController  # noqa: E402
from sessionsifu_portable.model import SessionSnapshot, WindowSnapshot  # noqa: E402
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

    def capture_windows(self) -> list[WindowSnapshot]:
        return [
            WindowSnapshot(
                window_id="1",
                app_id="org.example.Editor",
                app_name="Editor",
                title="Notes",
                executable="/usr/bin/editor",
                command=["/usr/bin/editor"],
                geometry=[10, 20, 900, 700],
                open_files=["/home/test/Notes.txt"],
            )
        ]

    def launch_window(self, window: WindowSnapshot) -> None:
        del window

    def apply_layout(self, session: SessionSnapshot) -> None:
        self.applied = session


class PortableTests(unittest.TestCase):
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
        self.assertEqual(VERSION, "2.0.0")
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
            def capture_windows(self) -> list[WindowSnapshot]:
                return []

        with tempfile.TemporaryDirectory() as directory:
            store = SessionStore(Path(directory))
            store.save_history(FakeAdapter().capture())
            controller = SessionController(EmptyAdapter(), store)
            with self.assertRaises(RuntimeError):
                controller.save_history()
            self.assertEqual(len(store.list_history()), 1)


if __name__ == "__main__":
    unittest.main()
