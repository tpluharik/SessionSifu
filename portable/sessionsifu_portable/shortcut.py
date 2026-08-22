"""Cross-platform validation and normalization for Recall shortcuts."""

from __future__ import annotations

from dataclasses import dataclass


DEFAULT_SHORTCUT = "Ctrl+Alt+Space"
_MODIFIER_ALIASES = {
    "ctrl": "Ctrl",
    "control": "Ctrl",
    "alt": "Alt",
    "option": "Alt",
    "shift": "Shift",
    "super": "Super",
    "meta": "Super",
    "win": "Super",
    "command": "Super",
    "cmd": "Super",
}
_MODIFIER_ORDER = ("Ctrl", "Alt", "Shift", "Super")


@dataclass(frozen=True)
class ShortcutSpec:
    label: str
    modifiers: tuple[str, ...]
    key: str

    @property
    def portal_trigger(self) -> str:
        portal_names = {
            "Ctrl": "Control",
            "Alt": "Alt",
            "Shift": "Shift",
            "Super": "Super",
        }
        prefix = "".join(f"<{portal_names[value]}>" for value in self.modifiers)
        return f"{prefix}{self.key.casefold()}"

    @property
    def windows_modifiers(self) -> int:
        flags = {"Alt": 0x0001, "Ctrl": 0x0002, "Shift": 0x0004, "Super": 0x0008}
        return 0x4000 | sum(flags[value] for value in self.modifiers)

    @property
    def windows_key(self) -> int:
        return 0x20 if self.key == "Space" else ord(self.key)

    @property
    def event_character(self) -> str:
        return " " if self.key == "Space" else self.key.casefold()


def parse_shortcut(value: str) -> ShortcutSpec:
    """Parse a portable shortcut limited to modifiers plus Space, A-Z or 0-9."""

    parts = [part.strip() for part in value.replace("-", "+").split("+") if part.strip()]
    if len(parts) < 2:
        raise ValueError("Use at least one modifier and one key")
    key_input = parts[-1]
    modifiers: set[str] = set()
    for part in parts[:-1]:
        modifier = _MODIFIER_ALIASES.get(part.casefold())
        if modifier is None:
            raise ValueError(f"Unknown modifier: {part}")
        modifiers.add(modifier)
    if not modifiers:
        raise ValueError("Use at least one modifier")
    if key_input.casefold() in {"space", "spacebar"}:
        key = "Space"
    elif len(key_input) == 1 and key_input.isascii() and key_input.isalnum():
        key = key_input.upper()
    else:
        raise ValueError("The key must be Space, A-Z or 0-9")
    ordered = tuple(value for value in _MODIFIER_ORDER if value in modifiers)
    label = "+".join((*ordered, key))
    return ShortcutSpec(label=label, modifiers=ordered, key=key)


def normalize_shortcut(value: str) -> str:
    return parse_shortcut(value).label
