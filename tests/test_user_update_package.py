#!/usr/bin/python3
"""Exercise the user-local updater against the real Debian artifact."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import os
import pathlib
import subprocess
import sys
import tempfile


root = pathlib.Path(sys.argv[1]).resolve()
package = pathlib.Path(sys.argv[2]).resolve()
executable = root / "app" / "sessionsifu"
loader = importlib.machinery.SourceFileLoader(
    "sessionsifu_package_install_test", str(executable)
)
spec = importlib.util.spec_from_loader(loader.name, loader)
assert spec is not None
module = importlib.util.module_from_spec(spec)
loader.exec_module(module)

with tempfile.TemporaryDirectory(prefix="sessionsifu-package-test-") as directory:
    test_root = pathlib.Path(directory)
    payload_root = test_root / "payload"
    extracted = subprocess.run(
        ["dpkg-deb", "--extract", str(package), str(payload_root)],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert extracted.returncode == 0, extracted.stderr

    local_app = module.install_user_payload(
        payload_root,
        user_data_dir=test_root / "data",
        user_config_dir=test_root / "config",
        user_bin_dir=test_root / "bin",
    )
    installed_app = test_root / "data/sessionsifu/app/sessionsifu"
    installed_module = test_root / "data/sessionsifu/app/recall_engine.py"
    assert installed_app.is_file()
    assert installed_module.is_file()

    # Directly launched Python scripts already contain their own directory in
    # sys.path. Ensure SessionSifu still moves that directory ahead of the
    # distro module path, otherwise a user-local update can run an older
    # /usr/lib/sessionsifu/recall_engine.py against newer extension output.
    original_module = installed_module.read_text(encoding="utf-8")
    installed_module.write_text(
        'raise SystemExit("user-local Recall engine selected")\n',
        encoding="utf-8",
    )
    precedence = subprocess.run(
        [str(local_app), "--help"],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert precedence.returncode != 0
    assert "user-local Recall engine selected" in precedence.stderr
    installed_module.write_text(original_module, encoding="utf-8")

    launched = subprocess.run(
        [str(local_app), "--help"],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert launched.returncode == 0, launched.stderr
    assert "Save and restore GNOME desktop sessions" in launched.stdout

print("user-local package launch test passed")
