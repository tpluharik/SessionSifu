"""Owner-private, declarative placement rules for portable restores."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import hashlib
import json
import os
import tempfile
from pathlib import Path

from .model import SessionSnapshot, WindowSnapshot

MAX_RULES = 256
MAX_RULE_BYTES = 512 * 1024


def _bounded(value: object, limit: int = 512) -> str:
    return str(value or "").strip()[:limit]


@dataclass(frozen=True, slots=True)
class WindowRule:
    app_id: str
    title_contains: str = ""
    monitor: str = ""
    workspace: str = ""
    geometry: tuple[int, int, int, int] | None = None
    enabled: bool = True

    @classmethod
    def from_dict(cls, value: dict) -> "WindowRule":
        app_id = _bounded(value.get("app_id"))
        if not app_id or any(ord(character) < 32 for character in app_id):
            raise ValueError("Window rule requires a valid application identity")
        raw_geometry = value.get("geometry")
        geometry = None
        if raw_geometry is not None:
            if not isinstance(raw_geometry, list) or len(raw_geometry) != 4:
                raise ValueError("Window rule geometry must contain x, y, width and height")
            geometry = tuple(max(-100_000, min(100_000, int(part))) for part in raw_geometry)
            if geometry[2] < 64 or geometry[3] < 64:
                raise ValueError("Window rule geometry is too small")
        return cls(
            app_id=app_id,
            title_contains=_bounded(value.get("title_contains"), 256),
            monitor=_bounded(value.get("monitor"), 256),
            workspace=_bounded(value.get("workspace"), 64),
            geometry=geometry,
            enabled=bool(value.get("enabled", True)),
        )

    def to_dict(self) -> dict:
        value = asdict(self)
        value["geometry"] = list(self.geometry) if self.geometry is not None else None
        return value

    @property
    def key(self) -> str:
        identity = f"{self.app_id.casefold()}\0{self.title_contains.casefold()}"
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]

    def matches(self, window: WindowSnapshot) -> bool:
        identity = window.app_id or window.executable or window.app_name
        return (
            self.enabled
            and identity.casefold() == self.app_id.casefold()
            and (
                not self.title_contains
                or self.title_contains.casefold() in window.title.casefold()
            )
        )


class WindowRuleStore:
    def __init__(self, root: Path) -> None:
        self.path = root / "window-rules.json"

    def list(self) -> list[WindowRule]:
        if not self.path.exists():
            return []
        if self.path.is_symlink() or self.path.stat().st_size > MAX_RULE_BYTES:
            raise ValueError("Window rules file is unsafe or too large")
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or raw.get("schema") != 1 or not isinstance(raw.get("rules"), list):
            raise ValueError("Window rules file has an unsupported format")
        rules: list[WindowRule] = []
        for value in raw["rules"][:MAX_RULES]:
            if isinstance(value, dict):
                rules.append(WindowRule.from_dict(value))
        return rules

    def _write(self, rules: list[WindowRule]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {"schema": 1, "rules": [rule.to_dict() for rule in rules[:MAX_RULES]]},
            ensure_ascii=False,
            indent=2,
        ) + "\n"
        if len(payload.encode("utf-8")) > MAX_RULE_BYTES:
            raise ValueError("Window rules exceed the storage limit")
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.path.parent, delete=False) as output:
            output.write(payload)
            temporary = Path(output.name)
        try:
            if os.name != "nt":
                temporary.chmod(0o600)
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def save(self, rule: WindowRule) -> None:
        rules = [candidate for candidate in self.list() if candidate.key != rule.key]
        self._write([rule, *rules])

    def delete(self, key: str) -> bool:
        rules = self.list()
        kept = [rule for rule in rules if rule.key != key]
        if len(kept) == len(rules):
            return False
        self._write(kept)
        return True

    def apply(self, session: SessionSnapshot) -> SessionSnapshot:
        rules = self.list()
        windows: list[WindowSnapshot] = []
        for window in session.windows:
            matching = [candidate for candidate in rules if candidate.matches(window)]
            rule = next((candidate for candidate in matching if candidate.title_contains), None)
            if rule is None:
                rule = next(iter(matching), None)
            if rule is None:
                windows.append(window)
                continue
            windows.append(replace(
                window,
                geometry=list(rule.geometry) if rule.geometry is not None else window.geometry,
                monitor=rule.monitor or window.monitor,
                workspace=rule.workspace or window.workspace,
            ))
        return replace(session, windows=windows)


def rule_from_window(window: WindowSnapshot, *, title_specific: bool = False) -> WindowRule:
    identity = window.app_id or window.executable or window.app_name
    if not identity:
        raise ValueError("The selected window has no stable application identity")
    return WindowRule(
        app_id=identity,
        title_contains=window.title if title_specific else "",
        monitor=window.monitor,
        workspace=window.workspace,
        geometry=tuple(window.geometry),
    )
