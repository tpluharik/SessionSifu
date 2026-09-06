"""Offscreen Qt heartbeat, worker failure, stale preview and capture backpressure."""
import base64
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock

_temporary = tempfile.TemporaryDirectory()
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["XDG_CONFIG_HOME"] = _temporary.name
os.environ["SESSIONSIFU_RECALL_TEST_KEY"] = base64.urlsafe_b64encode(b"x"*32).decode()
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "portable"))
try:
    from PySide6.QtCore import QObject, QTimer, QSettings
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QApplication
except ImportError:
    print("Qt background tests skipped: install portable[gui] to run")
    sys.exit(0)
from sessionsifu_portable.ui import BackgroundWork, RecallSearchDialog, MainWindow, RecallCaptureBridge
from sessionsifu_portable.model import SessionSnapshot, WindowSnapshot

QSettings.setDefaultFormat(QSettings.IniFormat)
QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, _temporary.name)
app = QApplication.instance() or QApplication([])


def until(predicate, seconds=5):
    deadline = time.monotonic() + seconds
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.005)
    assert predicate(), "Timed out waiting for an asynchronous completion"


class QtTests(unittest.TestCase):
    def test_main_window_refresh_and_result_icons_are_async(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from test_portable import FakeAdapter
        from sessionsifu_portable.controller import SessionController
        from sessionsifu_portable.storage import SessionStore
        with tempfile.TemporaryDirectory() as directory:
            controller = SessionController(FakeAdapter(), SessionStore(Path(directory)))
            controller.capsules.available_applications = lambda: []
            controller.search_recall = lambda *args, **kwargs: []
            window = MainWindow(controller)
            window._perform(lambda: (time.sleep(.05) or {"partial": True}), "Done", silent=True)
            until(lambda: not window._operation_busy)
            self.assertIn("partially", window.status.text())
            window._background.pool.shutdown()
            window.timer.stop()
            window.recall_timer.stop()
            window.capsule_running_timer.stop()
            window.close()

    def test_slow_io_and_exception_do_not_block_gui(self):
        parent = QObject()
        worker = BackgroundWork(parent)
        completions = []
        ticks = []
        timer = QTimer()
        timer.setInterval(5)
        timer.timeout.connect(lambda: ticks.append(1))
        timer.start()
        main_thread = threading.get_ident()
        def slow():
            time.sleep(.15)
            raise RuntimeError("injected worker failure")
        worker.submit(slow, lambda result, error: completions.append((error, threading.get_ident())))
        until(lambda: bool(completions))
        self.assertGreater(len(ticks), 5)
        self.assertIn("injected", completions[0][0])
        self.assertEqual(completions[0][1], main_thread)
        timer.stop()
        worker.pool.shutdown()

    def test_search_failure_releases_busy_and_next_search_runs(self):
        controller = Mock()
        controller.search_recall.side_effect = [KeyError("unexpected"), []]
        dialog = RecallSearchDialog(controller, lambda: [])
        dialog.refresh()
        until(lambda: not dialog._search_inflight)
        self.assertIn("unavailable", dialog.notice.text())
        dialog.refresh()
        until(lambda: not dialog._search_inflight)
        self.assertEqual(controller.search_recall.call_count, 2)
        dialog._background.pool.shutdown()
        dialog._thumbnail_executor.shutdown()
        dialog.close()

    def test_old_full_image_cannot_replace_new_selection(self):
        controller = Mock()
        controller.recall_store.preview_bytes.side_effect = lambda *a, **k: (time.sleep(.05) or None)
        dialog = RecallSearchDialog(controller, lambda: [])
        dialog._detail_entry = {"name": "synthetic"}
        dialog._detail_images = [("a.ssimg", "Old"), ("b.ssimg", "New")]
        shown = []
        dialog._display_image = lambda position, pixmap: shown.append(position)
        dialog.set_image(0)
        dialog.set_image(1)
        until(lambda: bool(shown))
        self.assertEqual(shown, [1])
        dialog._background.pool.shutdown()
        dialog._thumbnail_executor.shutdown()
        dialog.close()

    def test_capture_compresses_before_next_grab_and_preserves_all_windows(self):
        class Toggle:
            def isChecked(self): return True
        class Harness(QObject):
            _prepare_recall_visuals = MainWindow._prepare_recall_visuals
            def __init__(self):
                super().__init__()
                self._background = BackgroundWork(self)
                self.recall_screenshots = Toggle()
                self.recall_enabled = Toggle()
                self._recall_capture_bridge = RecallCaptureBridge(self)
                self.controller = Mock()
                self.encoding = False
                self.grabs = 0
            def _capture_recall_images(self, session, *, indices, with_display, allow_fallback=True):
                assert not self.encoding, "Raw frames must not queue behind compression"
                self.grabs += 1
                image = QImage(1920, 1080, QImage.Format_RGB32)
                image.fill(0)
                return (image if with_display else None, {i: image for i in indices}, {}, 1920, 80)
            def _jpeg_bytes(self, image, edge, quality):
                self.encoding = True
                time.sleep(.01)
                self.encoding = False
                return b"synthetic encoded image"
        harness = Harness()
        completed = []
        harness._recall_capture_bridge.completed.connect(lambda *args: completed.append(args))
        session = SessionSnapshot(platform="test", desktop="test", windows=[
            WindowSnapshot(window_id=str(i), app_id="editor") for i in range(16)])
        request = dict(retention_hours=24, excluded_apps=(), excluded_websites=(),
                       include_file_paths=False, ocr_enabled=False, sensitive_filter=True,
                       quota_mb=512, silent=True)
        harness._prepare_recall_visuals(request, session, "")
        until(lambda: bool(completed))
        self.assertTrue(completed[0][0])
        self.assertEqual(harness.grabs, 17)
        saved = harness.controller.save_prepared_recall.call_args.kwargs
        self.assertEqual(len(saved["window_previews"]), 16)
        harness._background.pool.shutdown()


if __name__ == "__main__":
    unittest.main()
