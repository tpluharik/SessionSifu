#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import recall_engine  # noqa: E402
from recall_engine import MAGIC, RecallPolicy, RecallVault, _prepare_ocr_image  # noqa: E402


class RecallEngineTests(unittest.TestCase):
    def test_accessibility_roots_do_not_merge_sibling_windows(self) -> None:
        class FakeText:
            def __init__(self, value: str) -> None:
                self.value = value
                self.characterCount = len(value)

            def getText(self, start: int, end: int) -> str:
                return self.value[start:end]

        class FakeNode:
            def __init__(self, name: str, text: str = "", children=()) -> None:
                self.name = name
                self.text = text
                self.children = list(children)
                self.childCount = len(self.children)

            def getChildAtIndex(self, index: int):
                return self.children[index]

            def getRoleName(self) -> str:
                return "text"

            def getState(self):
                raise RuntimeError("state unavailable")

            def queryText(self):
                if not self.text:
                    raise RuntimeError("no text")
                return FakeText(self.text)

        alpha = FakeNode("Alpha — Editor", children=[FakeNode("body", "secret alpha")])
        beta = FakeNode("Beta — Editor", children=[FakeNode("body", "visible beta")])
        application = FakeNode("Editor", children=[alpha, beta])
        root = recall_engine._atspi_window_root(application, "Beta — Editor", 2)
        self.assertIs(root, beta)
        text, consumed = recall_engine._atspi_visible_text(
            root, object(), 32, 4096, time.monotonic() + 1
        )
        self.assertIn("visible beta", text)
        self.assertNotIn("secret alpha", text)
        self.assertGreaterEqual(consumed, 2)

    def test_deep_targets_use_validated_files_and_supported_editor_uri(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            document = Path(directory) / "release notes.txt"
            document.write_text("content is never read by the target adapter")
            targets = recall_engine._deep_targets(
                {"app_name": "Visual Studio Code", "app_id": "code.desktop"},
                [str(document)],
                "Issue https://example.test/42",
            )
            self.assertIn(document.as_uri(), targets)
            self.assertIn(
                f"vscode://file/{str(document).lstrip('/').replace(' ', '%20')}",
                targets,
            )
            self.assertIn("https://example.test/42", targets)

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

    def test_window_preview_is_encrypted_linked_and_searchable_by_ocr(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            display = root / "recall-20260822-120000-123-display-0.jpg"
            window = root / "recall-20260822-120000-123-window-0.jpg"
            display.write_bytes(b"display-preview")
            window.write_bytes(b"exact-window-preview")
            vault = RecallVault(root, test_key=b"v" * 32)
            vault._ocr = lambda path: (
                (
                    "quarterly falcon figures",
                    [
                        {"t": "falcon", "x": 2500, "y": 3000,
                         "w": 1800, "h": 900, "c": 91}
                    ],
                )
                if "window-0" in path.name else ("", [])
            )
            result = vault.finalize(self.capture(root), RecallPolicy(ocr=True))
            record = vault.vault / result["record"]
            payload = vault._load(record)
            image_index = payload["windows"][0]["image_index"]
            self.assertGreaterEqual(image_index, 0)
            self.assertEqual(
                vault.preview_bytes(record.name, image_index),
                b"exact-window-preview",
            )
            match = vault.search("falcon")[0]
            self.assertEqual(match["match_type"], "Window image text")
            self.assertEqual(match["matched_window"]["image_index"], image_index)
            self.assertEqual(match["highlight_image_index"], image_index)
            self.assertIn("falcon", match["ocr_excerpt"])
            self.assertEqual(match["highlight_boxes"][0]["t"], "falcon")
            self.assertEqual(match["highlight_boxes"][0]["x"], 2500)
            self.assertEqual(
                vault.search("quart")[0]["match_type"], "Window image text"
            )
            self.assertEqual(
                vault.search("quartrly")[0]["match_type"], "Window image text"
            )
            self.assertEqual(vault.delete(record=record.name), 1)
            self.assertEqual(list(vault.vault.iterdir()), [])

    def test_structured_ocr_filters_noise_and_normalizes_word_boxes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / "sample.jpg"
            image.write_bytes(b"image")
            tsv = "\n".join((
                "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext",
                "1\t1\t0\t0\t0\t0\t0\t0\t1000\t500\t-1\t",
                "5\t1\t1\t1\t1\t1\t100\t50\t200\t50\t93.4\tFalcon",
                "5\t1\t1\t1\t1\t2\t320\t50\t100\t50\t12.0\tgarbage",
            )).encode()
            completed = mock.Mock(returncode=0, stdout=tsv)
            vault = RecallVault(root, test_key=b"o" * 32)
            with mock.patch("recall_engine._tesseract_language_args", return_value=()), \
                    mock.patch("recall_engine.subprocess.run", return_value=completed) as run:
                text, boxes = vault._ocr(image)
            self.assertEqual(text, "Falcon")
            self.assertEqual(boxes, [{
                "t": "Falcon", "x": 1000, "y": 1000,
                "w": 2000, "h": 1000, "c": 93,
            }])
            command = run.call_args.args[0]
            self.assertIn("tsv", command)
            self.assertIn("11", command)

    def test_ocr_uses_private_upscaled_working_image_and_removes_it(self) -> None:
        from PIL import Image

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / "small.jpg"
            Image.new("RGB", (320, 180), "white").save(image, "JPEG", quality=60)
            prepared = _prepare_ocr_image(image)
            self.assertNotEqual(prepared, image)
            self.assertEqual(prepared.stat().st_mode & 0o777, 0o600)
            with Image.open(prepared) as working:
                self.assertEqual(working.mode, "L")
                self.assertEqual(working.size, (960, 540))
            prepared.unlink()

            tsv = ("level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\t"
                   "left\ttop\twidth\theight\tconf\ttext\n").encode()
            completed = mock.Mock(returncode=0, stdout=tsv)
            seen: list[Path] = []

            def recognize(command, **_kwargs):
                seen.append(Path(command[1]))
                self.assertTrue(seen[-1].is_file())
                self.assertNotEqual(seen[-1], image)
                return completed

            vault = RecallVault(root, test_key=b"p" * 32)
            with mock.patch("recall_engine._tesseract_language_args", return_value=()), \
                    mock.patch("recall_engine.subprocess.run", side_effect=recognize):
                vault._ocr(image)
            self.assertEqual(len(seen), 1)
            self.assertFalse(seen[0].exists())
            self.assertTrue(image.exists())

    def test_ocr_selects_installed_desktop_language_with_english(self) -> None:
        completed = mock.Mock(
            returncode=0,
            stdout=b"List of available languages in /tmp (2):\neng\nces\n",
        )
        with mock.patch.object(recall_engine, "_TESSERACT_LANGUAGE_ARGS", None), \
                mock.patch.object(recall_engine, "_bundled_tessdata_dir", return_value=None), \
                mock.patch.dict(os.environ, {"LANG": "cs_CZ.UTF-8"}, clear=True), \
                mock.patch("recall_engine.subprocess.run", return_value=completed):
            self.assertEqual(
                recall_engine._tesseract_language_args(), ("-l", "ces+eng")
            )

    def test_ocr_prefers_bundled_czech_and_english_models(self) -> None:
        bundled = ROOT / "ocr" / "tessdata"
        with mock.patch.object(recall_engine, "_TESSERACT_LANGUAGE_ARGS", None):
            self.assertEqual(
                recall_engine._tesseract_language_args(),
                ("--tessdata-dir", str(bundled), "-l", "ces+eng"),
            )
        result = subprocess.run(
            ["tesseract", "--tessdata-dir", str(bundled), "--list-langs"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue({"ces", "eng"} <= set(result.stdout.splitlines()))

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

    def test_prune_removes_stale_plaintext_window_images(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stale = root / "recall-20260822-120000-123-window-7.jpg"
            fresh = root / "recall-20260822-120001-123-window-8.jpg"
            unrelated = root / "personal-photo.jpg"
            for path in (stale, fresh, unrelated):
                path.write_bytes(b"preview")
            old = time.time() - 300
            stale.touch()
            os.utime(stale, (old, old))
            vault = RecallVault(root, test_key=b"q" * 32)
            vault._ensure()
            vault.prune(64)
            self.assertFalse(stale.exists())
            self.assertTrue(fresh.exists())
            self.assertTrue(unrelated.exists())

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
                {
                    "app_name": "Visual Studio Browser",
                    "app_id": "org.example.VisualStudioBrowser.desktop",
                    "window_title": "Project Gamma code",
                    "monitor_number": 0,
                    "window_position": {
                        "x_offset": 100, "y_offset": 100,
                        "width": 700, "height": 500,
                    },
                },
            ]
            capture.write_text(json.dumps(payload))
            image = root / "recall-20260822-120000-123-display-0.jpg"
            image.write_bytes(b"jpeg-preview")
            vault = RecallVault(root, test_key=b"w" * 32)
            vault.finalize(capture, RecallPolicy())
            results = vault.search("Project")
            self.assertEqual(len(results), 3)
            self.assertEqual(results[0]["apps"], ["Browser"])
            self.assertEqual(
                {result["matched_window"]["title"] for result in results},
                {"Project Alpha notes", "Project Beta research", "Project Gamma code"},
            )
            browser = vault.search("Project", app="Browser")
            self.assertEqual(len(browser), 1)
            self.assertEqual(browser[0]["apps"], ["Browser"])
            redacted = vault.search("Project", excluded_apps=("Editor",))
            self.assertEqual(len(redacted), 2)
            self.assertNotIn("Editor", {result["apps"][0] for result in redacted})
            self.assertTrue(all(result["image_count"] == 0 for result in redacted))

    def test_accessible_text_is_indexed_and_private_windows_are_redacted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            capture = self.capture(root)
            payload = json.loads(capture.read_text())
            payload["x_session_config_objects"][0]["accessible_text"] = (
                "Quarterly narwhal forecast"
            )
            payload["x_session_config_objects"][0]["deep_targets"] = [
                "vscode://file/home/example/notes.txt"
            ]
            payload["x_session_config_objects"].append({
                "app_name": "Browser",
                "window_title": "Private Browsing",
                "capture_protection": "private browsing",
            })
            capture.write_text(json.dumps(payload))
            display = root / "recall-20260822-120000-123-display-0.jpg"
            editor = root / "recall-20260822-120000-123-window-0.jpg"
            private = root / "recall-20260822-120000-123-window-1.jpg"
            display.write_bytes(b"shared")
            editor.write_bytes(b"editor")
            private.write_bytes(b"private")
            vault = RecallVault(root, test_key=b"a" * 32)
            result = vault.finalize(capture, RecallPolicy())
            record = vault._load(vault.vault / result["record"])
            self.assertEqual(len(record["windows"]), 1)
            self.assertEqual(record["images"], [
                "recall-20260822-120000-123-window-0.ssimg"
            ])
            self.assertTrue(record["privacy"]["shared_display_withheld"])
            self.assertEqual(record["capture_diagnostics"]["protected_windows"], 1)
            match = vault.search("narwhal")[0]
            self.assertEqual(match["match_type"], "Application content")
            self.assertIn("vscode://file/home/example/notes.txt", match["targets"])


if __name__ == "__main__":
    unittest.main()
