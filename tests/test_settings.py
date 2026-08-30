#!/usr/bin/python3
from __future__ import annotations

import importlib.machinery
import importlib.util
import hashlib
import io
import json
import pathlib
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from unittest import mock


target = pathlib.Path(sys.argv[1])
executable = target if target.is_file() else target / "app" / "sessionsifu"
loader = importlib.machinery.SourceFileLoader("sessionsifu_settings_test", str(executable))
spec = importlib.util.spec_from_loader(loader.name, loader)
assert spec is not None
module = importlib.util.module_from_spec(spec)
loader.exec_module(module)
assert module.missing_user_payload_modules() == ()

list_model = module.Gtk.ListStore.new([str, str])
assert module.tree_model_row_count(list_model) == 0
list_model.append(["org.example.Editor", "Editor"])
assert module.tree_model_row_count(list_model) == 1

gallery_item = {
    "image_count": 5,
    "matched_window": {"image_index": 3},
    "windows": [{"image_index": 1}, {"image_index": 3}, {"image_index": -1}],
    "displays": [{"image_index": 0}],
}
assert module.recall_window_image_indices(gallery_item) == [3, 1]
assert module.recall_image_indices(gallery_item) == [3, 1, 0, 2, 4]
assert module.recall_highlight_image_index(gallery_item) == 3
assert module.recall_highlight_image_index({"highlight_image_index": 2}) == 2
assert module.recall_capture_summary({
    "capture_diagnostics": {
        "eligible_windows": 4,
        "captured_window_images": 3,
        "excluded_windows": 1,
    }
}) == "3/4 eligible window images · 1 privacy-filtered · incomplete"
assert module.recall_window_preview_state({
    "preview_source": "workspace-cache", "preview_captured_at": "2026-08-30T12:00:00Z"
}) == "Cached workspace preview · captured 2026-08-30T12:00:00Z"
assert "2 cached workspace previews" in module.recall_capture_summary({
    "capture_diagnostics": {
        "eligible_windows": 3, "captured_window_images": 3, "cached_workspace_previews": 2,
    }
})

settings = module.settings()
assert settings.get_boolean("show-indicator") is True
assert settings.get_int("autostart-delay") >= 0
assert settings.get_boolean("continuous-save-enabled") is True
assert settings.get_int("continuous-save-interval") == 300
assert settings.get_boolean("recall-enabled") is False
assert settings.get_int("recall-interval") == 300
assert settings.get_int("recall-retention-hours") == 24
assert settings.get_boolean("recall-include-file-paths") is False
assert settings.get_boolean("recall-capture-screenshots") is False
assert settings.get_string("recall-preview-quality") == "storage"
assert settings.get_string("recall-search-view-mode") == "visual"
assert module.recall_preview_profile("storage") == (960, 68)
assert module.recall_preview_profile("readable") == (1440, 74)
assert module.recall_preview_profile("high") == (1920, 80)
assert module.recall_preview_profile("invalid") == (960, 68)
assert "SessionSifu" in settings.get_strv("recall-excluded-apps")
assert settings.get_boolean("recall-search-shortcut-enabled") is True
assert settings.get_strv("recall-search-shortcut") == ["<Control><Alt>space"]
settings.set_strv("recall-search-shortcut", ["<Control><Shift>r"])
assert settings.get_strv("recall-search-shortcut") == ["<Control><Shift>r"]
assert module.sync_gnome_recall_shortcut(settings) is True
media_keys = module.Gio.Settings.new(module.MEDIA_KEYS_SCHEMA)
assert module.RECALL_SHORTCUT_PATH in media_keys.get_strv("custom-keybindings")
native_shortcut = module.Gio.Settings.new_with_path(
    module.CUSTOM_KEYBINDING_SCHEMA, module.RECALL_SHORTCUT_PATH
)
assert native_shortcut.get_string("binding") == "<Control><Shift>r"
assert native_shortcut.get_string("command").endswith(" --recall-search")
settings.set_strv("recall-search-shortcut", ["<Control><Alt>space"])
settings.set_int("continuous-save-interval", 30)
assert settings.get_int("continuous-save-interval") == 30
settings.set_int("continuous-save-interval", 300)

now = datetime.now(timezone.utc)
manifest = module.parse_update_manifest(
    json.dumps(
        {
            "version": "3.4.1",
            "channel": "stable",
            "issued_at": (now - timedelta(minutes=1)).isoformat(),
            "expires_at": (now + timedelta(days=30)).isoformat(),
            "minimum_version": "2.5.0",
            "package_url": "https://raw.githubusercontent.com/tpluharik/SessionSifu/main/updates/sessionsifu_3.4.1_all.deb",
            "sha256": "a" * 64,
            "size": 12345,
            "notes": "Test update",
        }
    )
)
assert manifest["version"] == "3.4.1"
assert manifest["size"] == 12345

older_manifest = module.parse_update_manifest(
    json.dumps(
        {
            "version": "3.1.1",
            "channel": "stable",
            "issued_at": (now - timedelta(minutes=1)).isoformat(),
            "expires_at": (now + timedelta(days=30)).isoformat(),
            "minimum_version": "2.5.0",
            "package_url": "https://raw.githubusercontent.com/tpluharik/SessionSifu/main/updates/sessionsifu_3.1.1_all.deb",
            "sha256": "a" * 64,
            "size": 12345,
        }
    )
)
assert older_manifest["version"] == "3.1.1"

if target.is_dir():
    signed_manifest = (target / "updates/latest.json").read_bytes()
    signed_signature = (target / "updates/latest.json.sig").read_bytes()
    module.verify_update_manifest(signed_manifest, signed_signature)

class FakeResponse:
    def __init__(self, contents: bytes, url: str):
        self._stream = io.BytesIO(contents)
        self._url = url

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)

    def geturl(self) -> str:
        return self._url


payload = b"a test Debian package payload"
download_manifest = {
    **manifest,
    "sha256": hashlib.sha256(payload).hexdigest(),
    "size": len(payload),
}
with tempfile.TemporaryDirectory() as cache_dir:
    response = FakeResponse(payload, download_manifest["package_url"])
    with mock.patch.object(module.urllib.request, "urlopen", return_value=response):
        with mock.patch.object(module.GLib, "get_user_cache_dir", return_value=cache_dir):
            downloaded = module.download_update(download_manifest)
    assert downloaded.read_bytes() == payload

with tempfile.TemporaryDirectory() as install_root:
    install_root = pathlib.Path(install_root)
    payload_root = install_root / "payload"
    source_app = payload_root / "usr/bin/sessionsifu"
    source_recall_module = payload_root / "usr/lib/sessionsifu/recall_engine.py"
    source_support_modules = [
        payload_root / f"usr/lib/sessionsifu/{name}"
        for name in ("semantic.py", "restore_journal.py", "mcp.py", "capsule.py")
    ]
    source_desktop = payload_root / "usr/share/applications/org.gnome.SessionSifu.desktop"
    source_autostart = payload_root / "etc/xdg/autostart/org.gnome.SessionSifu.desktop"
    source_icon = payload_root / "usr/share/icons/hicolor/scalable/apps/org.gnome.SessionSifu.svg"
    source_extension = payload_root / "usr/share/gnome-shell/extensions/sessionsifu@local"
    source_bundle = payload_root / "usr/share/sessionsifu/sessionsifu@local.shell-extension.zip"
    source_tessdata = payload_root / "usr/share/sessionsifu/tessdata"
    source_ocr_files = [
        source_tessdata / "ces.traineddata",
        source_tessdata / "eng.traineddata",
        source_tessdata / "configs/tsv",
        source_tessdata / "LICENSE",
    ]
    for path in [
        source_app,
        source_recall_module,
        *source_support_modules,
        source_desktop,
        source_autostart,
        source_icon,
        source_bundle,
        *source_ocr_files,
    ]:
        path.parent.mkdir(parents=True, exist_ok=True)
    source_extension.mkdir(parents=True)
    source_app.write_text(
        "#!/usr/bin/python3\n"
        "from recall_engine import TEST_VALUE\n"
        "print(TEST_VALUE)\n"
    )
    source_recall_module.write_text("TEST_VALUE = 'updated with module'\n")
    for source_support_module in source_support_modules:
        source_support_module.write_text("# SessionSifu support module\n")
    source_desktop.write_text("[Desktop Entry]\nType=Application\nExec=sessionsifu\n")
    source_autostart.write_text("[Desktop Entry]\nType=Application\nExec=sessionsifu --autostart\n")
    source_icon.write_text("<svg/>\n")
    source_bundle.write_bytes(b"extension bundle")
    (source_tessdata / "ces.traineddata").write_bytes(b"czech model")
    (source_tessdata / "eng.traineddata").write_bytes(b"english model")
    (source_tessdata / "configs/tsv").write_text("tessedit_create_tsv 1\n")
    (source_tessdata / "LICENSE").write_text("Apache-2.0\n")
    (source_extension / "metadata.json").write_text('{"version-name":"1.2.2"}\n')

    data_dir = install_root / "data"
    config_dir = install_root / "config"
    bin_dir = install_root / "bin"
    local_app = module.install_user_payload(
        payload_root,
        user_data_dir=data_dir,
        user_config_dir=config_dir,
        user_bin_dir=bin_dir,
    )
    assert local_app == bin_dir / "sessionsifu"
    installed_app = data_dir / "sessionsifu/app/sessionsifu"
    assert installed_app.read_text() == source_app.read_text()
    assert str(installed_app) in local_app.read_text()
    assert local_app.stat().st_mode & 0o111
    assert installed_app.stat().st_mode & 0o111
    installed_module = data_dir / "sessionsifu/app/recall_engine.py"
    assert installed_module.read_text() == source_recall_module.read_text()
    for source_support_module in source_support_modules:
        installed = data_dir / "sessionsifu/app" / source_support_module.name
        assert installed.read_text() == source_support_module.read_text()
    installed_tessdata = data_dir / "sessionsifu/tessdata"
    for source in source_ocr_files:
        installed = installed_tessdata / source.relative_to(source_tessdata)
        assert installed.read_bytes() == source.read_bytes()
    launched = subprocess.run(
        [str(local_app)],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert launched.returncode == 0, launched.stderr
    assert launched.stdout.strip() == "updated with module"
    assert f'Exec="{local_app}"' in (
        data_dir / "applications/org.gnome.SessionSifu.desktop"
    ).read_text()
    assert f'Exec="{local_app}" --autostart' in (
        config_dir / "autostart/org.gnome.SessionSifu.desktop"
    ).read_text()
    assert (
        data_dir / "gnome-shell/extensions/sessionsifu@local/metadata.json"
    ).is_file()
    assert (
        data_dir / "sessionsifu/sessionsifu@local.shell-extension.zip"
    ).read_bytes() == b"extension bundle"

try:
    module.parse_update_manifest(
        json.dumps(
            {
                "version": "3.4.1",
                "channel": "stable",
                "issued_at": (now - timedelta(minutes=1)).isoformat(),
                "expires_at": (now + timedelta(days=30)).isoformat(),
                "minimum_version": "2.5.0",
                "package_url": "https://example.com/sessionsifu.deb",
                "sha256": "a" * 64,
                "size": 12345,
            }
        )
    )
except ValueError:
    pass
else:
    raise AssertionError("untrusted update host was accepted")

try:
    module.verify_update_manifest(b"{}", b"not-a-signature")
except ValueError:
    pass
else:
    raise AssertionError("invalid update signature was accepted")

with tempfile.TemporaryDirectory() as config_root:
    storage = pathlib.Path(config_root) / "sessionsifu"
    nested = storage / "sessions"
    nested.mkdir(parents=True, mode=0o755)
    private_file = nested / "Work"
    private_file.write_text("{}")
    private_file.chmod(0o644)
    with mock.patch.object(module.GLib, "get_user_config_dir", return_value=config_root):
        module.harden_local_storage()
    assert storage.stat().st_mode & 0o777 == 0o700
    assert nested.stat().st_mode & 0o777 == 0o700
    assert private_file.stat().st_mode & 0o777 == 0o600

with tempfile.NamedTemporaryFile(suffix=".shell-extension.zip") as bundle:
    module.os.environ["SESSIONSIFU_EXTENSION_BUNDLE"] = bundle.name
    installed = subprocess.CompletedProcess([], 0, "", "")
    not_discovered = subprocess.CompletedProcess([], 2, "", "does not exist")
    with mock.patch.object(module, "extension_state", return_value=("missing", "")):
        with mock.patch.object(module, "extension_needs_update", return_value=False):
            with mock.patch.object(module.subprocess, "run", side_effect=[installed, not_discovered]) as run:
                ok, message = module.enable_extension()
    assert ok is True
    assert message == "Extension installed. Log out and back in once to start it."
    assert module.extension_scheduled() is True
    assert run.call_args_list[0].args[0][0:3] == [
        "gnome-extensions", "install", "--force"
    ]
    assert run.call_args_list[1].args[0] == [
        "gnome-extensions", "enable", "sessionsifu@local"
    ]

stopped = subprocess.CompletedProcess([], 0, "", "")
started = subprocess.CompletedProcess([], 0, "", "")
with mock.patch.object(module, "extension_state", return_value=("enabled", "")):
    with mock.patch.object(module, "extension_needs_update", return_value=False):
        with mock.patch.object(
            module, "live_extension_current", side_effect=[False, True]
        ):
            with mock.patch.object(
                module.subprocess, "run", side_effect=[stopped, started]
            ) as run:
                ok, message = module.enable_extension()
assert ok is True
assert message == "GNOME integration reloaded and connected."
assert [item.args[0] for item in run.call_args_list] == [
    ["gnome-extensions", "disable", "sessionsifu@local"],
    ["gnome-extensions", "enable", "sessionsifu@local"],
]

print("settings schema lookup test passed")
