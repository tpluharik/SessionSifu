"""Fail-closed discovery for experimental Wayland session management.

The protocol is intentionally not treated as a general desktop capability.  It
must be advertised by the running compositor and explicitly enabled by the
user.  SessionSifu can only defer layout for windows that a cooperating client
has claimed; it cannot attach a protocol object to an arbitrary existing
third-party surface.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from typing import Callable, Mapping


PROTOCOL_NAME = "xx_session_manager_v1"
PROTOCOL_VERSION = 1
FEATURE_ENV = "SESSIONSIFU_EXPERIMENTAL_WAYLAND_SESSION_MANAGEMENT"
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


@dataclass(frozen=True, slots=True)
class WaylandSessionStatus:
    feature_enabled: bool = False
    wayland_session: bool = False
    probe_available: bool = False
    compositor_advertises: bool = False
    compositor_version: int = 0
    usable: bool = False
    protocol: str = PROTOCOL_NAME
    version: int = PROTOCOL_VERSION
    scope: str = "cooperative-applications-only"
    reason: str = "Experimental Wayland session management is disabled"

    def to_dict(self) -> dict[str, bool | int | str]:
        return asdict(self)


def feature_enabled(environment: Mapping[str, str] | None = None) -> bool:
    environment = os.environ if environment is None else environment
    return str(environment.get(FEATURE_ENV, "")).strip().casefold() in _TRUE_VALUES


def _system_probe(executable: str) -> str:
    completed = subprocess.run(
        [executable],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
        timeout=3,
    )
    # Registry output is normally small, but diagnostics must remain bounded.
    return completed.stdout[:2 * 1024 * 1024]


def detect_wayland_session_management(
    *,
    environment: Mapping[str, str] | None = None,
    executable: str | None = None,
    probe: Callable[[str], str] | None = None,
) -> WaylandSessionStatus:
    environment = os.environ if environment is None else environment
    enabled = feature_enabled(environment)
    is_wayland = str(environment.get("XDG_SESSION_TYPE", "")).casefold() == "wayland"
    if not enabled:
        return WaylandSessionStatus(wayland_session=is_wayland)
    if not is_wayland:
        return WaylandSessionStatus(
            feature_enabled=True,
            reason="The experimental feature is enabled, but this is not a Wayland session",
        )
    tool = executable if executable is not None else shutil.which("wayland-info")
    if not tool:
        return WaylandSessionStatus(
            feature_enabled=True,
            wayland_session=True,
            reason="The compositor registry cannot be inspected because wayland-info is unavailable",
        )
    try:
        output = (probe or _system_probe)(tool)
    except (OSError, subprocess.SubprocessError, UnicodeError) as error:
        return WaylandSessionStatus(
            feature_enabled=True,
            wayland_session=True,
            probe_available=True,
            reason=f"The compositor registry probe failed: {type(error).__name__}",
        )
    match = re.search(
        rf"interface:\s*['\"]{re.escape(PROTOCOL_NAME)}['\"][^\n]*"
        r"version:\s*(\d+)",
        output,
    )
    advertised_version = min(65_535, int(match.group(1))) if match else 0
    advertised = advertised_version >= PROTOCOL_VERSION
    return WaylandSessionStatus(
        feature_enabled=True,
        wayland_session=True,
        probe_available=True,
        compositor_advertises=advertised,
        compositor_version=advertised_version,
        usable=advertised,
        reason=(
            "Available only to applications that opt in before mapping their windows"
            if advertised
            else "The running compositor does not advertise the experimental protocol"
        ),
    )


def managed_window_ids(
    metadata: Mapping[str, object] | None,
    status: WaylandSessionStatus,
) -> set[str]:
    """Return only window IDs explicitly delegated to a compatible client."""
    if not status.usable or not isinstance(metadata, Mapping):
        return set()
    if metadata.get("protocol") != PROTOCOL_NAME:
        return set()
    try:
        version = int(metadata.get("version") or 0)
    except (TypeError, ValueError):
        return set()
    if version != PROTOCOL_VERSION or metadata.get("client_claimed") is not True:
        return set()
    raw = metadata.get("managed_window_ids")
    if not isinstance(raw, list):
        return set()
    return {str(value)[:256] for value in raw[:512] if str(value)[:256]}
