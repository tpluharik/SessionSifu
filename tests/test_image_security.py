"""Synthetic image boundaries only; never touches a user's desktop or vault."""
import ast
import io
import multiprocessing
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "app"), str(ROOT / "portable")]
import recall_engine as core
from sessionsifu_portable import recall as portable
from PIL import Image


def stalled_worker(*_args):
    time.sleep(30)


class ImageSecurityTests(unittest.TestCase):
    def test_bounds_before_conversion_and_format_allowlist(self):
        for module in (core, portable):
            image = mock.MagicMock()
            image.__enter__.return_value = image
            for size in [(0, 2), (2, 20000), (8192, 8192)]:
                image.size = size
                with mock.patch.object(module.Image, "open", return_value=image) as opened:
                    with self.assertRaises(ValueError), module._open_preview(io.BytesIO(b"bounded")):
                        image.convert("L")
                    self.assertEqual(opened.call_args.kwargs["formats"], ("JPEG", "PNG"))
                image.convert.assert_not_called()

    def test_valid_jpeg_png_and_encoded_bounds(self):
        for module in (core, portable):
            for format in ("JPEG", "PNG"):
                raw = io.BytesIO()
                Image.new("RGB", (60, 40), "white").save(raw, format)
                with module._open_preview(io.BytesIO(raw.getvalue())) as image:
                    self.assertEqual(image.size, (60, 40))
            for raw in (b"", b"x" * (8 * 1024 * 1024 + 1), b"not an image"):
                with self.assertRaises((OSError, ValueError)), module._open_preview(io.BytesIO(raw)):
                    self.fail("Invalid image accepted")
            gif = io.BytesIO()
            Image.new("RGB", (4, 4)).save(gif, "GIF")
            with self.assertRaises(OSError), module._open_preview(io.BytesIO(gif.getvalue())):
                self.fail("Non-screenshot decoder accepted")

    def test_decoder_bomb_errors_do_not_escape_capture_hash(self):
        for module in (core, portable):
            visual_hash = core._visual_hash_bytes if module is core else portable.RecallStore._visual_hash
            with mock.patch.object(module.Image, "open", side_effect=Image.DecompressionBombError):
                self.assertEqual(visual_hash(b"tiny encoded header"), "")

    def test_real_spawned_preparation_and_private_cleanup(self):
        for module in (core, portable):
            with tempfile.TemporaryDirectory() as directory:
                source = Path(directory) / "legacy.jpg"
                Image.new("RGB", (60, 40), "white").save(source)
                before = source.read_bytes()
                prepared = module._prepare_untrusted_ocr_image(source)
                self.assertIsNotNone(prepared)
                try:
                    with Image.open(prepared) as result:
                        self.assertEqual(result.size, (180, 120))
                    if os.name == "posix":
                        self.assertEqual(prepared.stat().st_mode & 0o077, 0)
                    self.assertEqual(source.read_bytes(), before)
                finally:
                    prepared.unlink(missing_ok=True)
                source.write_bytes(b"old invalid preview retained for manual export")
                before = source.read_bytes()
                self.assertIsNone(module._prepare_untrusted_ocr_image(source))
                self.assertEqual(source.read_bytes(), before)

    def test_worker_timeout_reaps_only_its_own_child(self):
        for module in (core, portable):
            with tempfile.TemporaryDirectory() as directory:
                source = Path(directory) / "legacy.jpg"
                source.write_bytes(b"retained")
                with mock.patch.object(module, "_ocr_image_worker", stalled_worker), mock.patch.object(
                        module, "IMAGE_PREPARATION_TIMEOUT", 0.05):
                    started = time.monotonic()
                    self.assertIsNone(module._prepare_untrusted_ocr_image(source))
                    self.assertLess(time.monotonic() - started, 3.0)
                self.assertEqual(source.read_bytes(), b"retained")

    def test_mock_pid_is_never_coerced_or_signalled(self):
        for module in (core, portable):
            process = mock.Mock()
            process.pid = mock.MagicMock()
            process.is_alive.return_value = True
            context = mock.Mock()
            context.Process.return_value = process
            with mock.patch.object(module.multiprocessing, "get_context", return_value=context):
                self.assertIsNone(module._prepare_untrusted_ocr_image(Path("unused")))
            process.kill.assert_not_called()
            process.pid.__int__.assert_not_called()

    def test_refused_portable_reindex_preserves_old_ocr_and_image_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            store = portable.RecallStore(Path(directory))
            store._key = lambda: b"x" * 32
            original = b"legacy unsupported preview"
            metadata = {"recall_schema": 3, "windows": [], "image": "old.ssimg",
                        "ocr_text": "existing recovered text", "ocr_boxes": [{"text": "old"}]}
            path = store.import_record(metadata, {"old.ssimg": original})
            with mock.patch.object(store, "_ocr_detailed",
                                   return_value=("", [], {"state": "preview-refused"})):
                result = store.reindex(path.name)
            self.assertEqual(result["images_deferred"], 1)
            self.assertEqual(store._load(path)["ocr_text"], "existing recovered text")
            self.assertEqual(store.preview_bytes(path.name), original)

    def test_both_engines_keep_identical_image_boundaries(self):
        names = {"_open_preview", "_ocr_image_worker", "_prepare_untrusted_ocr_image"}
        functions = []
        for path in (ROOT / "app/recall_engine.py", ROOT / "portable/sessionsifu_portable/recall.py"):
            tree = ast.parse(path.read_text())
            functions.append({node.name: ast.dump(node, include_attributes=False)
                              for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names})
        self.assertEqual(functions[0], functions[1])

    def test_refused_gnome_reindex_preserves_old_window_ocr_and_images(self):
        with tempfile.TemporaryDirectory() as directory:
            vault = core.RecallVault(Path(directory))
            vault._key = lambda: b"x" * 32
            raw = b"old preview stays exportable"
            metadata = {"schema": 3, "images": ["old-window-0.ssimg"],
                        "ocr_text": "old display text", "display_ocr_boxes": {"0": []},
                        "windows": [{"image_index": 0, "ocr_text": "old OCR", "ocr_boxes": []}]}
            path = vault.import_record(metadata, [raw])
            with mock.patch.object(vault, "_ocr", side_effect=ValueError("preview refused")):
                result = vault.reindex(path.name)
            self.assertEqual(result["images_deferred"], 1)
            self.assertEqual(vault._load(path)["windows"][0]["ocr_text"], "old OCR")
            self.assertEqual(vault._load(path)["ocr_text"], "old display text")
            self.assertEqual(vault.preview_bytes(path.name, 0), raw)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    unittest.main()
