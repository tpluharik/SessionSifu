#!/usr/bin/python3
from __future__ import annotations

import importlib.machinery
import importlib.util
import pathlib
import subprocess
import sys
import tempfile
from unittest import mock


target = pathlib.Path(sys.argv[1])
executable = target if target.is_file() else target / "app" / "sessionsifu"
loader = importlib.machinery.SourceFileLoader("sessionsifu_settings_test", str(executable))
spec = importlib.util.spec_from_loader(loader.name, loader)
assert spec is not None
module = importlib.util.module_from_spec(spec)
loader.exec_module(module)

settings = module.settings()
assert settings.get_boolean("show-indicator") is True
assert settings.get_int("autostart-delay") >= 0

with tempfile.NamedTemporaryFile(suffix=".shell-extension.zip") as bundle:
    module.os.environ["SESSIONSIFU_EXTENSION_BUNDLE"] = bundle.name
    installed = subprocess.CompletedProcess([], 0, "", "")
    not_discovered = subprocess.CompletedProcess([], 2, "", "does not exist")
    with mock.patch.object(module, "extension_state", return_value=("missing", "")):
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

print("settings schema lookup test passed")
