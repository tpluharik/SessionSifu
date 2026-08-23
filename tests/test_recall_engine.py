#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from recall_engine import MAGIC, RecallPolicy, RecallVault  # noqa: E402


class RecallEngineTests(unittest.TestCase):
    def capture(self, root: Path, title: str = "Project notes") -> Path:
        path = root / "recall-20260822-120000-123.json"
        path.write_text(json.dumps({
            "recall_schema": 2,
            "session_create_time": "2026-08-22T12:00:00+00:00",
            "recall_displays": [
                {"index": 0, "x": 0, "y": 0, "width": 1920, "height": 1080}
            ],
            "x_session_config_objects": [{
                "app_name": "Editor",
                "window_title": title,
                "open_files": ["/home/example/notes.txt"],
                "monitor_number": 0,
                "window_position": {"x_offset": 10, "y_offset": 20, "width": 800, "height": 600},
            }],
        }))
        return path

    def test_finalize_encrypt_search_preview_and_delete(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / "recall-20260822-120000-123-display-0.jpg"
            image.write_bytes(b"jpeg-preview")
            vault = RecallVault(root, test_key=b"x" * 32)
            result = vault.finalize(self.capture(root), RecallPolicy())
            self.assertTrue(result["saved"])
            record = vault.vault / result["record"]
            self.assertTrue(record.read_bytes().startswith(MAGIC))
            self.assertNotIn(b"Project notes", record.read_bytes())
            self.assertEqual(vault.search("Project notes")[0]["apps"], ["Editor"])
            self.assertEqual(vault.search("Project notes")[0]["result_kind"], "window")
            self.assertEqual(vault.search("Project notes")[0]["matched_window"]["title"], "Project notes")
            self.assertEqual(vault.search()[0]["displays"][0]["image_index"], 0)
            self.assertEqual(vault.preview_bytes(record.name), b"jpeg-preview")
            self.assertEqual(vault.delete(record=record.name), 1)
            self.assertEqual(vault.search(), [])

    def test_sensitive_and_website_filters_discard_capture(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vault = RecallVault(root, test_key=b"y" * 32)
            result = vault.finalize(
                self.capture(root, "Password recovery phrase"), RecallPolicy()
            )
            self.assertFalse(result["saved"])
            self.assertEqual(vault.search(), [])
            result = vault.finalize(
                self.capture(root, "https://bank.example/account"),
                RecallPolicy(excluded_websites=("bank.example",)),
            )
            self.assertFalse(result["saved"])

    def test_quota_and_status_are_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vault = RecallVault(root, test_key=b"z" * 32)
            vault.finalize(self.capture(root), RecallPolicy(quota_mb=64))
            status = vault.status()
            self.assertEqual(status["state"], "saved")
            self.assertEqual(status["vault_entries"], 1)
            self.assertLess(status["vault_bytes"], 10 * 1024 * 1024)

    def test_search_returns_separate_window_moments_and_honors_app_filter(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            capture = self.capture(root)
            payload = json.loads(capture.read_text())
            payload["x_session_config_objects"] = [
                {
                    "app_name": "Editor",
                    "app_id": "org.example.Editor.desktop",
                    "window_title": "Project Alpha notes",
                    "recall_focused": False,
                    "monitor_number": 0,
                    "window_position": {
                        "x_offset": 10, "y_offset": 20,
                        "width": 800, "height": 600,
                    },
                },
                {
                    "app_name": "Browser",
                    "app_id": "org.example.Browser.desktop",
                    "window_title": "Project Beta research",
                    "recall_focused": True,
                    "monitor_number": 0,
                    "window_position": {
                        "x_offset": 900, "y_offset": 20,
                        "width": 900, "height": 700,
                    },
                },
            ]
            capture.write_text(json.dumps(payload))
            image = root / "recall-20260822-120000-123-display-0.jpg"
            image.write_bytes(b"jpeg-preview")
            vault = RecallVault(root, test_key=b"w" * 32)
            vault.finalize(capture, RecallPolicy())
            results = vault.search("Project")
            self.assertEqual(len(results), 2)
            self.assertEqual(results[0]["apps"], ["Browser"])
            self.assertEqual(
                {result["matched_window"]["title"] for result in results},
                {"Project Alpha notes", "Project Beta research"},
            )
            browser = vault.search("Project", app="Browser")
            self.assertEqual(len(browser), 1)
            self.assertEqual(browser[0]["apps"], ["Browser"])
            redacted = vault.search("Project", excluded_apps=("Editor",))
            self.assertEqual(len(redacted), 1)
            self.assertEqual(redacted[0]["apps"], ["Browser"])
            self.assertEqual(redacted[0]["image_count"], 0)


if __name__ == "__main__":
    unittest.main()
