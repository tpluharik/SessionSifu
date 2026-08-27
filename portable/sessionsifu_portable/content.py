"""Bounded application-content adapters used before screenshot OCR.

The helpers in this module never read document contents.  They prefer text
already exposed by the desktop accessibility API and derive safe re-entry
targets from observable URLs and opted-in file paths.  OCR remains the fallback
for platforms or applications that do not expose accessible text.
"""

from __future__ import annotations

import os
import re
import urllib.parse
from pathlib import Path

from .model import SessionSnapshot, WindowSnapshot

URL_RE = re.compile(r"https?://[^\s<>{}\[\]\"']+", re.IGNORECASE)
PRIVATE_CONTEXT_RE = re.compile(
    r"\b(?:private browsing|private window|incognito|inprivate|guest session)\b",
    re.IGNORECASE,
)
PROTECTED_CONTEXT_RE = re.compile(
    r"\b(?:remote desktop|screen sharing|vmconnect|digital rights management|drm protected)\b",
    re.IGNORECASE,
)
VSCODE_IDENTITY_RE = re.compile(
    r"(?:^|[.\s/_-])(?:code|codium)(?:$|[.\s/_-])|visual studio code",
    re.IGNORECASE,
)
JETBRAINS_IDENTITY_RE = re.compile(r"\b(?:idea|pycharm|clion|goland|webstorm|rider|rubymine)\b", re.IGNORECASE)
LIBREOFFICE_IDENTITY_RE = re.compile(r"\b(?:libreoffice|soffice|writer|calc|impress)\b", re.IGNORECASE)
BROWSER_IDENTITY_RE = re.compile(r"\b(?:firefox|chrome|chromium|edge|brave|vivaldi|safari)\b", re.IGNORECASE)
MAX_ACCESSIBLE_BYTES = 64 * 1024
MAX_ACCESSIBLE_NODES = 384
MAX_TARGETS = 32


def _utf8_prefix(value: str, maximum: int) -> str:
    return value.encode("utf-8", "replace")[:maximum].decode("utf-8", "ignore")


def capture_protection_reason(window: WindowSnapshot) -> str:
    """Identify contexts that should never enter visual Recall history."""
    visible = "\n".join((window.app_name, window.app_id, window.title))
    if PRIVATE_CONTEXT_RE.search(visible):
        return "private browsing"
    if PROTECTED_CONTEXT_RE.search(visible):
        return "protected or remote content"
    return ""


def deep_targets(window: WindowSnapshot) -> list[str]:
    """Return bounded, observable targets for resuming an application moment."""
    visible_url_text = "\n".join((window.title, *window.command))
    identity = "\n".join((window.app_id, window.app_name, window.executable)).casefold()
    if BROWSER_IDENTITY_RE.search(identity):
        visible_url_text += "\n" + window.accessible_text
    urls = list(dict.fromkeys(URL_RE.findall(visible_url_text)))
    files: list[Path] = []
    for raw in window.open_files:
        try:
            path = Path(raw)
            if path.is_absolute() and path.is_file() and not path.is_symlink():
                files.append(path.resolve())
        except OSError:
            continue
    targets: list[str] = []
    for path in files:
        quoted = urllib.parse.quote(str(path))
        if VSCODE_IDENTITY_RE.search(identity):
            targets.append(f"vscode://file/{quoted.lstrip('/')}")
        elif JETBRAINS_IDENTITY_RE.search(identity):
            targets.append(path.as_uri() + "#jetbrains")
        elif "obsidian" in identity:
            targets.append("obsidian://open?path=" + quoted)
        elif LIBREOFFICE_IDENTITY_RE.search(identity):
            targets.append(path.as_uri() + "#libreoffice")
        targets.append(path.as_uri())
    targets.extend(urls)
    return list(dict.fromkeys(targets))[:MAX_TARGETS]


def _accessible_application(pid: int):
    """Find one AT-SPI application without making accessibility mandatory."""
    try:
        import pyatspi  # type: ignore[import-not-found]
    except ImportError:
        return None
    try:
        desktop = pyatspi.Registry.getDesktop(0)
        for application in desktop:
            try:
                if int(application.get_process_id()) == pid:
                    return application
            except Exception:
                continue
    except Exception:
        return None
    return None


def _accessible_applications(pids: set[int]) -> dict[int, object]:
    """Build one capture-scoped PID map with a single AT-SPI desktop walk."""
    wanted = {pid for pid in pids if pid > 0}
    if not wanted:
        return {}
    try:
        import pyatspi  # type: ignore[import-not-found]
        desktop = pyatspi.Registry.getDesktop(0)
    except Exception:
        return {}
    applications: dict[int, object] = {}
    try:
        for application in desktop:
            try:
                pid = int(application.get_process_id())
            except Exception:
                continue
            if pid in wanted:
                applications[pid] = application
                if len(applications) == len(wanted):
                    break
    except Exception:
        return applications
    return applications


def _matching_accessible_root(application, window_title: str, sibling_windows: int):
    """Select a top-level AT-SPI window without mixing sibling window content."""
    try:
        children = [
            application.getChildAtIndex(index)
            for index in range(min(int(application.childCount), 64))
        ]
        children = [child for child in children if child is not None]
    except Exception:
        children = []
    title = window_title.strip().casefold()
    if title:
        exact = next(
            (child for child in children if str(getattr(child, "name", "") or "").strip().casefold() == title),
            None,
        )
        if exact is not None:
            return exact
        terms = set(re.findall(r"[\w]+", title))
        ranked = []
        for child in children:
            candidate = set(re.findall(
                r"[\w]+", str(getattr(child, "name", "") or "").casefold()
            ))
            score = len(terms & candidate) / max(1, len(terms | candidate))
            ranked.append((score, child))
        if ranked:
            score, candidate = max(ranked, key=lambda item: item[0])
            if score >= 0.25:
                return candidate
    if sibling_windows == 1:
        return children[0] if len(children) == 1 else application
    return None


def linux_accessible_text(
    pid: int, window_title: str = "", sibling_windows: int = 1,
    *, application=None,
) -> str:
    """Collect visible AT-SPI names/text with strict node and byte limits."""
    if pid <= 0 or os.environ.get("XDG_SESSION_TYPE", "").casefold() not in {"", "x11", "wayland"}:
        return ""
    try:
        import pyatspi  # type: ignore[import-not-found]
    except ImportError:
        return ""
    application = application if application is not None else _accessible_application(pid)
    if application is None:
        return ""
    root = _matching_accessible_root(application, window_title, sibling_windows)
    if root is None:
        return ""
    pending = [root]
    seen = 0
    values: list[str] = []
    size = 0
    while pending and seen < MAX_ACCESSIBLE_NODES and size < MAX_ACCESSIBLE_BYTES:
        node = pending.pop()
        seen += 1
        collect = True
        protected = False
        try:
            role = str(getattr(node, "getRoleName", lambda: "")() or "").casefold()
            if "password" in role:
                protected = True
            state = node.getState()
            protected_state = getattr(pyatspi, "STATE_PROTECTED", None)
            if protected_state is not None and state.contains(protected_state):
                protected = True
            visible = getattr(pyatspi, "STATE_VISIBLE", None)
            showing = getattr(pyatspi, "STATE_SHOWING", None)
            if (
                visible is not None and showing is not None
                and not state.contains(visible) and not state.contains(showing)
            ):
                collect = False
        except Exception:
            pass
        if protected:
            continue
        try:
            if not collect:
                raise ValueError("hidden accessibility node")
            name = str(getattr(node, "name", "") or "").strip()
            if name and name not in values:
                value = _utf8_prefix(name, min(1024, MAX_ACCESSIBLE_BYTES - size))
                values.append(value)
                size += len(value.encode("utf-8"))
            text = node.queryText()
            content = str(text.getText(0, min(int(text.characterCount), 4096))).strip()
            if content and content not in values:
                value = _utf8_prefix(content, MAX_ACCESSIBLE_BYTES - size)
                values.append(value)
                size += len(value.encode("utf-8"))
        except Exception:
            pass
        try:
            for index in range(min(int(node.childCount), 64)):
                child = node.getChildAtIndex(index)
                if child is not None:
                    pending.append(child)
        except Exception:
            continue
    return _utf8_prefix("\n".join(values), MAX_ACCESSIBLE_BYTES)


def enrich_linux_session(session: SessionSnapshot) -> None:
    """Attach accessibility-first content and resumable targets in place."""
    window_count_by_pid = {
        pid: sum(1 for candidate in session.windows if candidate.pid == pid)
        for pid in {window.pid for window in session.windows}
    }
    applications = _accessible_applications(set(window_count_by_pid))
    accessible_by_window: dict[tuple[int, str], str] = {}
    for window in session.windows:
        key = (window.pid, window.title)
        if key not in accessible_by_window:
            application = applications.get(window.pid)
            accessible_by_window[key] = (
                linux_accessible_text(
                    window.pid, window.title, window_count_by_pid.get(window.pid, 1),
                    application=application,
                )
                if application is not None else ""
            )
        window.accessible_text = accessible_by_window[key]
        window.deep_targets = deep_targets(window)
        window.capture_protection = capture_protection_reason(window)


def enrich_generic_session(session: SessionSnapshot) -> None:
    for window in session.windows:
        window.deep_targets = deep_targets(window)
        window.capture_protection = capture_protection_reason(window)
