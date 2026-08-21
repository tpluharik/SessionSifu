#!/usr/bin/python3
from __future__ import annotations

import importlib.machinery
import importlib.util
import pathlib
import sys


root = pathlib.Path(sys.argv[1])
executable = root / "app" / "sessionsifu"
loader = importlib.machinery.SourceFileLoader("sessionsifu_settings_test", str(executable))
spec = importlib.util.spec_from_loader(loader.name, loader)
assert spec is not None
module = importlib.util.module_from_spec(spec)
loader.exec_module(module)

settings = module.settings()
assert settings.get_boolean("show-indicator") is True
assert settings.get_int("autostart-delay") >= 0

print("settings schema lookup test passed")
