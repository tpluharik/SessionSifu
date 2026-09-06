"""Fault-injection regressions. Only synthetic temporary vaults and mock desktops."""
import base64
import json
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "app"), str(ROOT / "portable")]
import recall_engine as core
from sessionsifu_portable import recall as portable
from sessionsifu_portable.vault_key import vault_key
from sessionsifu_portable.adapters.base import PlatformAdapter
from sessionsifu_portable.adapters.linux import KDEAdapter
from sessionsifu_portable.model import SessionSnapshot, WindowSnapshot

KEY = b"x" * 32


class Keyring:
    def __init__(self):
        self.keys = {}
        self.locked = False
        self.writes = 0

    def get_password(self, service, account):
        if self.locked:
            raise RuntimeError("locked")
        return self.keys.get((service, account))

    def set_password(self, service, account, value):
        if self.locked:
            raise RuntimeError("locked")
        self.keys[(service, account)] = value
        self.writes += 1


class AuditTests(unittest.TestCase):
    def test_key_outage_recovery_and_missing_key(self):
        for module, constructor in ((core, core.RecallVault), (portable, portable.RecallStore)):
            with self.subTest(engine=module.__name__), tempfile.TemporaryDirectory() as directory:
                ring = Keyring()
                with patch.object(module, "keyring", ring):
                    vault = constructor(Path(directory))
                    vault._ensure() if module is core else vault._ensure_directory()
                    key = vault._key()
                    ring.locked = True
                    with self.assertRaisesRegex(RuntimeError, "locked"):
                        vault._key()
                    self.assertFalse(list(Path(directory).rglob(".vault-key")))
                    ring.locked = False
                    self.assertEqual(vault._key(), key)
                    ring.keys.clear()
                    with self.assertRaisesRegex(RuntimeError, "unavailable"):
                        vault._key()
                    self.assertEqual(ring.writes, 1)

    def test_legacy_vault_never_creates_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vault = root / "vault"
            vault.mkdir()
            (vault / "existing.ssrec").write_bytes(b"unreadable synthetic record")
            with self.assertRaisesRegex(RuntimeError, "unavailable"):
                vault_key(root, vault, None, "test", "default", encoded_file=False)
            self.assertFalse((root / ".vault-key").exists())

    def test_concurrent_initialization_and_legacy_formats(self):
        for encoded in (True, False):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                ring = Keyring()
                def load(_):
                    return vault_key(root, root / "vault", ring, "test", "default", encoded_file=encoded)[0]
                with ThreadPoolExecutor(max_workers=8) as pool:
                    keys = list(pool.map(load, range(32)))
                self.assertEqual(len(set(keys)), 1)
                self.assertEqual(ring.writes, 1)
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / ".vault-key").write_bytes(base64.urlsafe_b64encode(KEY) if encoded else KEY)
                result, _ = vault_key(root, root / "vault", None, "test", "default", encoded_file=encoded)
                self.assertEqual(result, KEY)

    def test_wrong_key_identity_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ring = Keyring()
            vault_key(root, root / "vault", ring, "test", "default", encoded_file=False)
            ring.keys = {key: base64.urlsafe_b64encode(KEY).decode() for key in ring.keys}
            with self.assertRaisesRegex(RuntimeError, "does not match"):
                vault_key(root, root / "vault", ring, "test", "default", encoded_file=False)

    def test_corruption_and_incremental_search(self):
        for module, constructor in ((core, core.RecallVault), (portable, portable.RecallStore)):
            with self.subTest(engine=module.__name__), tempfile.TemporaryDirectory() as directory:
                vault = constructor(Path(directory))
                vault._ensure() if module is core else vault._ensure_directory()
                vault._key = lambda: KEY
                folder = vault.vault if module is core else vault.vault_dir
                write = vault._atomic_encrypted if module is core else vault._write_encrypted
                def record(i):
                    name = f"recall-20260906-120000-{i:03d}.ssrec" if module is core else f"recall-20260906-120000-{i:06d}.ssrec"
                    path = folder / name
                    payload = {"schema": 3, "recall_schema": 3, "captured_at": "2026-09-06",
                               "windows": [{"app": "Editor", "app_name": "Editor", "app_id": "editor",
                                            "title": f"uniqueterm{i}", "ocr_text": "example text",
                                            "ocr_boxes": [{"text": "example", "x": .1, "y": .1}]*100}]}
                    write(path, json.dumps(payload).encode())
                    return path
                paths = [record(i) for i in range(12)]
                with patch.object(module, "MAX_RECORD_CACHE_BYTES", 1000):
                    self.assertTrue(vault.search("uniqueterm3", limit=1))
                    connection = vault._index_connection
                    with patch.object(vault, "_decrypt", wraps=vault._decrypt) as decrypt:
                        self.assertTrue(vault.search("uniqueterm3", limit=1))
                        self.assertLessEqual(decrypt.call_count, 1)
                    record(12)
                    with patch.object(vault, "_decrypt", wraps=vault._decrypt) as decrypt:
                        self.assertTrue(vault.search("uniqueterm12", limit=1))
                        self.assertEqual(decrypt.call_count, 1)
                    self.assertIs(connection, vault._index_connection)
                data = bytearray(paths[0].read_bytes())
                data[-1] ^= 1
                paths[0].write_bytes(data)
                self.assertIsNone(vault._load(paths[0]))
                self.assertTrue(vault.search("uniqueterm3"))
                paths[3].unlink()
                self.assertFalse(vault.search("uniqueterm3"))
                vault.clear_search_cache()
                self.assertEqual(vault._manifest_bytes, 0)

    def test_kde_partial_batch_falls_back_only_for_unmatched(self):
        adapter = object.__new__(KDEAdapter)
        adapter.kdotool = "mock-kdotool"
        adapter.reconciled_session = lambda session: session
        adapter._kwin_json = lambda script: {"updated": 1, "ids": ["survivor"]}
        adapter.capture_windows = Mock(return_value=[
            WindowSnapshot(window_id="survivor", app_id="editor"),
            WindowSnapshot(window_id="new-id", app_id="browser")])
        session = SessionSnapshot(platform="test", desktop="KDE", windows=[
            WindowSnapshot(window_id="survivor", app_id="editor"),
            WindowSnapshot(window_id="old-id", app_id="browser")])
        with patch("sessionsifu_portable.adapters.linux.subprocess.run") as run:
            result = adapter.apply_layout(session)
        self.assertEqual({item["window_id"] for item in result}, {"survivor", "old-id"})
        self.assertTrue(all("new-id" in call.args[0] for call in run.call_args_list))

    def test_restore_missing_windows_never_reports_success(self):
        class Missing(PlatformAdapter):
            def capture_windows(self, include_files=True): return []
            def launch_window(self, window): return True
            def apply_layout(self, session): return []
        session = SessionSnapshot(platform="test", desktop="test", windows=[
            WindowSnapshot(window_id="1", app_id="slow")])
        result = Missing().restore(session, settle_seconds=0)
        self.assertEqual(result["windows"], 0)
        self.assertTrue(result["partial"])
        result = Missing().restore(session, cancelled=lambda: True)
        self.assertEqual(result["applications"], 0)
        self.assertEqual(result["actions"][0]["state"], "cancelled")

    def test_restore_waits_and_aggregates_documents(self):
        class Delayed(PlatformAdapter):
            def __init__(self): self.calls = 0; self.launched = []
            def capture_windows(self, include_files=True):
                self.calls += 1
                return session.windows if self.calls >= 3 else []
            def launch_window(self, window): self.launched.append(window); return True
            def apply_layout(self, restored):
                return [{"window_id": w.window_id, "state": "completed"} for w in restored.windows]
        session = SessionSnapshot(platform="test", desktop="test", windows=[
            WindowSnapshot(window_id="1", app_id="editor", open_files=["/tmp/a"]),
            WindowSnapshot(window_id="2", app_id="editor", open_files=["/tmp/b"])])
        adapter = Delayed()
        with patch("sessionsifu_portable.adapters.base.time.sleep"):
            result = adapter.restore(session, settle_seconds=1)
        self.assertEqual(result["windows"], 2)
        self.assertEqual(len(adapter.launched), 1)
        self.assertEqual(adapter.launched[0].open_files, ["/tmp/a", "/tmp/b"])


if __name__ == "__main__":
    unittest.main()
