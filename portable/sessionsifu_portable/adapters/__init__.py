"""Platform adapter selection."""

from __future__ import annotations

import os
import platform

from .base import PlatformAdapter


def select_adapter() -> PlatformAdapter:
    system = platform.system()
    if system == "Windows":
        from .windows import WindowsAdapter

        return WindowsAdapter()
    if system == "Darwin":
        from .macos import MacOSAdapter

        return MacOSAdapter()
    from .linux import GnomeAdapter, KDEAdapter, LinuxAdapter

    desktop = ":".join(
        filter(None, [os.environ.get("XDG_CURRENT_DESKTOP", ""), os.environ.get("DESKTOP_SESSION", "")])
    ).lower()
    if "kde" in desktop or "plasma" in desktop:
        return KDEAdapter()
    if "gnome" in desktop or "ubuntu" in desktop:
        return GnomeAdapter()
    return LinuxAdapter()


__all__ = ["PlatformAdapter", "select_adapter"]
