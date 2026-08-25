"""Validated, platform-neutral SessionSifu session model."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from . import SCHEMA_VERSION, VERSION

MAX_WINDOWS = 512
MAX_FILES_PER_WINDOW = 32
MAX_TEXT = 4096


def _text(value: Any, maximum: int = MAX_TEXT) -> str:
    return str(value or "")[:maximum]


def _integer(value: Any, minimum: int = -100_000, maximum: int = 100_000) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = 0
    return max(minimum, min(maximum, parsed))


@dataclass(slots=True)
class WindowSnapshot:
    window_id: str = ""
    app_id: str = ""
    app_name: str = ""
    title: str = ""
    executable: str = ""
    command: list[str] = field(default_factory=list)
    pid: int = 0
    geometry: list[int] = field(default_factory=lambda: [0, 0, 800, 600])
    workspace: str = ""
    monitor: str = ""
    minimized: bool = False
    maximized: bool = False
    fullscreen: bool = False
    open_files: list[str] = field(default_factory=list)
    accessible_text: str = ""
    deep_targets: list[str] = field(default_factory=list)
    capture_protection: str = ""

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "WindowSnapshot":
        geometry = list(value.get("geometry") or [0, 0, 800, 600])[:4]
        geometry += [0] * (4 - len(geometry))
        geometry = [_integer(part) for part in geometry]
        geometry[2] = max(64, geometry[2])
        geometry[3] = max(64, geometry[3])
        return cls(
            window_id=_text(value.get("window_id"), 256),
            app_id=_text(value.get("app_id"), 512),
            app_name=_text(value.get("app_name"), 512),
            title=_text(value.get("title")),
            executable=_text(value.get("executable")),
            command=[_text(part) for part in list(value.get("command") or [])[:64]],
            pid=_integer(value.get("pid"), 0, 2**31 - 1),
            geometry=geometry,
            workspace=_text(value.get("workspace"), 256),
            monitor=_text(value.get("monitor"), 256),
            minimized=bool(value.get("minimized")),
            maximized=bool(value.get("maximized")),
            fullscreen=bool(value.get("fullscreen")),
            open_files=[_text(path) for path in list(value.get("open_files") or [])[:MAX_FILES_PER_WINDOW]],
            accessible_text=_text(value.get("accessible_text"), 64 * 1024),
            deep_targets=[_text(target) for target in list(value.get("deep_targets") or [])[:32]],
            capture_protection=_text(value.get("capture_protection"), 128),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SessionSnapshot:
    platform: str
    desktop: str
    windows: list[WindowSnapshot]
    captured_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    )
    schema: int = SCHEMA_VERSION
    sessionsifu_version: str = VERSION
    capabilities: dict[str, bool] = field(default_factory=dict)
    capture_diagnostics: dict[str, int | str | bool] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "SessionSnapshot":
        try:
            schema = int(value.get("schema", 0))
        except (TypeError, ValueError) as error:
            raise ValueError("Session schema is invalid") from error
        if schema < 1:
            raise ValueError("Session schema is invalid")
        if schema > SCHEMA_VERSION:
            raise ValueError(f"Session schema {schema} is newer than this application supports")
        raw_windows = value.get("windows")
        if not isinstance(raw_windows, list):
            raise ValueError("Session has no window list")
        return cls(
            platform=_text(value.get("platform"), 128),
            desktop=_text(value.get("desktop"), 256),
            windows=[WindowSnapshot.from_dict(item) for item in raw_windows[:MAX_WINDOWS] if isinstance(item, dict)],
            captured_at=_text(value.get("captured_at"), 128),
            schema=schema,
            sessionsifu_version=_text(value.get("sessionsifu_version"), 64),
            capabilities={str(key): bool(val) for key, val in dict(value.get("capabilities") or {}).items()},
            capture_diagnostics={
                str(key): val for key, val in dict(value.get("capture_diagnostics") or {}).items()
                if isinstance(val, (bool, int, str))
            },
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "sessionsifu_version": self.sessionsifu_version,
            "captured_at": self.captured_at,
            "platform": self.platform,
            "desktop": self.desktop,
            "capabilities": self.capabilities,
            "capture_diagnostics": self.capture_diagnostics,
            "windows": [window.to_dict() for window in self.windows],
        }
