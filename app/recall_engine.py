"""Encrypted, local-only Recall vault used by the GNOME manager.

GNOME Shell only captures bounded metadata and display images.  This module
finalizes those temporary files outside the compositor: it compresses/searches
text, applies privacy policy, encrypts persistent data and builds an in-memory
FTS index for each search process.
"""

from __future__ import annotations

import base64
import csv
import contextlib
import hashlib
import io
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
import unicodedata
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except ImportError:  # pragma: no cover - package dependency, exercised by diagnostics
    AESGCM = None

try:
    import keyring
except ImportError:  # pragma: no cover - package dependency, exercised by diagnostics
    keyring = None

try:
    from PIL import Image, ImageFilter, ImageOps
except ImportError:  # pragma: no cover - graceful fallback for source checkouts
    Image = ImageFilter = ImageOps = None

try:
    from semantic import OfflineSemanticSearch
except ImportError:  # source checkout fallback
    OfflineSemanticSearch = None


RECORD_RE = re.compile(r"^recall-\d{8}-\d{6}-\d{3}\.json$")
VAULT_RE = re.compile(r"^recall-\d{8}-\d{6}-\d{3}\.ssrec$")
IMAGE_RE = re.compile(
    r"^recall-\d{8}-\d{6}-\d{3}-(display|window)-(\d+)\.jpg$"
)
VAULT_IMAGE_RE = re.compile(
    r"^recall-\d{8}-\d{6}-\d{3}-(?:display|window)-\d+\.ssimg$"
)
PLAINTEXT_IMAGE_RE = re.compile(
    r"^recall-\d{8}-\d{6}-\d{3}-(?:display-\d+\.jpg|window-\d+\.jpg|"
    r"raw\.png|window-\d+-raw\.png)$"
)
URL_RE = re.compile(r"https?://[^\s<>{}\[\]\"']+", re.IGNORECASE)
CARD_RE = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
SENSITIVE_RE = re.compile(
    r"\b(?:password|passcode|one[- ]time code|security code|cvv|cvc|secret key|"
    r"recovery phrase|private key)\b",
    re.IGNORECASE,
)
PROTECTED_CONTEXT_RE = re.compile(
    r"\b(?:private browsing|incognito|inprivate|guest browsing|password manager|"
    r"authentication code|two-factor authentication|secret key|private key)\b",
    re.IGNORECASE,
)
VSCODE_IDENTITY_RE = re.compile(
    r"(?:^|[.\s/_-])(?:code|codium)(?:$|[.\s/_-])|visual studio code",
    re.IGNORECASE,
)
MAGIC = b"SSRF1\0"
MAX_RECORD_BYTES = 2 * 1024 * 1024
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_OCR_BYTES = 1024 * 1024
MAX_WINDOW_OCR_BYTES = 16 * 1024
MAX_TOTAL_WINDOW_OCR_BYTES = 512 * 1024
MAX_OCR_BOXES_PER_IMAGE = 512
MAX_DISPLAY_OCR_BOXES = 1024
MAX_TOTAL_WINDOW_OCR_BOXES = 4096
MIN_OCR_CONFIDENCE = 30.0
MAX_ENTRIES = 500
SERVICE = "org.gnome.SessionSifu.Recall"
ACCOUNT = "local-vault-v1"
FUZZY_OCR_SCAN_BYTES = 2 * 1024 * 1024
MAX_OCR_WORKING_EDGE = 2400
_TESSERACT_LANGUAGE_ARGS: tuple[str, ...] | None = None
TESSERACT_LANGUAGE_ALIASES = {
    "cs": "ces", "de": "deu", "es": "spa", "fr": "fra", "it": "ita",
    "nl": "nld", "pl": "pol", "pt": "por", "sk": "slk", "uk": "ukr",
}
MAX_BUNDLED_MODEL_BYTES = 16 * 1024 * 1024
MAX_ACCESSIBLE_BYTES_PER_WINDOW = 64 * 1024
MAX_TOTAL_ACCESSIBLE_BYTES = 512 * 1024
MAX_ACCESSIBLE_NODES_PER_WINDOW = 384
MAX_TOTAL_ACCESSIBLE_NODES = 3072
MAX_ACCESSIBILITY_SECONDS = 1.5


def _utf8_prefix(value: str, maximum: int) -> str:
    return value.encode("utf-8", "replace")[:maximum].decode("utf-8", "ignore")


def _private(path: Path, mode: int) -> None:
    with contextlib.suppress(OSError):
        path.chmod(mode)


def _prepare_ocr_image(image: Path) -> Path:
    """Create a private, temporary high-contrast OCR source when possible.

    Recall previews stay compact for storage and browsing. OCR instead works
    from an upscaled grayscale copy so small interface text is not permanently
    lost to the preview's JPEG size and quality limits.
    """
    if Image is None or ImageFilter is None or ImageOps is None:
        return image
    temporary: Path | None = None
    try:
        with Image.open(image) as source:
            prepared = ImageOps.autocontrast(source.convert("L"), cutoff=1)
            longest = max(prepared.size)
            if longest <= 0:
                return image
            scale = min(3.0, MAX_OCR_WORKING_EDGE / longest)
            if scale > 1.05:
                prepared = prepared.resize(
                    (max(1, round(prepared.width * scale)),
                     max(1, round(prepared.height * scale))),
                    Image.Resampling.LANCZOS,
                )
            prepared = prepared.filter(
                ImageFilter.UnsharpMask(radius=1.2, percent=160, threshold=3)
            )
            descriptor, name = tempfile.mkstemp(prefix="sessionsifu-ocr-", suffix=".png")
            os.close(descriptor)
            temporary = Path(name)
            prepared.save(temporary, "PNG", optimize=True)
            _private(temporary, 0o600)
            return temporary
    except (OSError, ValueError):
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        return image


def _tesseract_language_args() -> tuple[str, ...]:
    """Use the installed model matching the desktop locale, plus English."""
    global _TESSERACT_LANGUAGE_ARGS
    if _TESSERACT_LANGUAGE_ARGS is not None:
        return _TESSERACT_LANGUAGE_ARGS
    bundled = _bundled_tessdata_dir()
    if bundled is not None:
        _TESSERACT_LANGUAGE_ARGS = (
            "--tessdata-dir", str(bundled), "-l", "ces+eng",
        )
        return _TESSERACT_LANGUAGE_ARGS
    installed: set[str] = set()
    try:
        result = subprocess.run(
            ["tesseract", "--list-langs"], check=False, capture_output=True, timeout=5,
        )
        if result.returncode == 0:
            installed = {
                line.strip() for line in result.stdout.decode("utf-8", "replace").splitlines()
                if re.fullmatch(r"[A-Za-z_]+", line.strip())
            }
    except (OSError, subprocess.TimeoutExpired):
        pass
    locale_value = next((
        os.environ.get(name, "") for name in ("LANGUAGE", "LC_ALL", "LC_CTYPE", "LANG")
        if os.environ.get(name, "")
    ), "")
    locale_code = re.split(r"[:_.@]", locale_value.casefold())[0]
    preferred = TESSERACT_LANGUAGE_ALIASES.get(locale_code, locale_code)
    languages = [value for value in (preferred, "eng") if value and value in installed]
    languages = list(dict.fromkeys(languages))
    _TESSERACT_LANGUAGE_ARGS = ("-l", "+".join(languages)) if languages else ()
    return _TESSERACT_LANGUAGE_ARGS


def _bundled_tessdata_dir() -> Path | None:
    """Find the signed Czech/English models in every supported install layout."""
    module = Path(__file__).resolve()
    candidates = [
        Path(os.environ["SESSIONSIFU_TESSDATA_DIR"])
        if os.environ.get("SESSIONSIFU_TESSDATA_DIR") else None,
        Path(getattr(sys, "_MEIPASS", "")) / "tessdata"
        if getattr(sys, "_MEIPASS", "") else None,
        Path("/usr/share/sessionsifu/tessdata"),
        module.parent.parent / "tessdata",
        module.parents[1] / "ocr/tessdata",
    ]
    for directory in candidates:
        if directory is None or directory.is_symlink() or not directory.is_dir():
            continue
        required = (
            directory / "ces.traineddata",
            directory / "eng.traineddata",
            directory / "configs/tsv",
        )
        try:
            if all(
                path.is_file() and not path.is_symlink()
                and 0 < path.stat().st_size <= MAX_BUNDLED_MODEL_BYTES
                for path in required
            ):
                return directory
        except OSError:
            continue
    return None


def _luhn(value: str) -> bool:
    digits = [int(char) for char in value if char.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False
    parity = len(digits) % 2
    total = 0
    for index, digit in enumerate(digits):
        if index % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def contains_sensitive_text(text: str) -> bool:
    if SENSITIVE_RE.search(text):
        return True
    return any(_luhn(match.group(0)) for match in CARD_RE.finditer(text))


def _domain(value: str) -> str:
    with contextlib.suppress(ValueError):
        return (urllib.parse.urlparse(value).hostname or "").casefold()
    return ""


def _capture_protection(window: dict) -> str:
    """Return a reason when an app window must not enter the visual timeline."""
    identity = "\n".join((
        str(window.get("app_name") or window.get("app_id") or ""),
        str(window.get("title") or window.get("window_title") or ""),
        str(window.get("capture_protection") or ""),
    ))
    if str(window.get("capture_protection") or "").strip():
        return str(window["capture_protection"])[:128]
    return "protected application context" if PROTECTED_CONTEXT_RE.search(identity) else ""


def _atspi_window_root(application, title: str, sibling_windows: int):
    """Match an AT-SPI top-level window without merging sibling window text."""
    try:
        children = [
            application.getChildAtIndex(index)
            for index in range(min(int(application.childCount), 64))
        ]
        children = [child for child in children if child is not None]
    except Exception:
        children = []
    normalized_title = title.strip().casefold()
    if normalized_title:
        exact = next((
            child for child in children
            if str(getattr(child, "name", "") or "").strip().casefold() == normalized_title
        ), None)
        if exact is not None:
            return exact
        title_terms = set(re.findall(r"[\w]+", normalized_title))
        ranked = []
        for child in children:
            child_terms = set(re.findall(
                r"[\w]+", str(getattr(child, "name", "") or "").casefold()
            ))
            ranked.append((
                len(title_terms & child_terms) / max(1, len(title_terms | child_terms)),
                child,
            ))
        if ranked:
            score, candidate = max(ranked, key=lambda item: item[0])
            if score >= 0.25:
                return candidate
    if sibling_windows == 1:
        return children[0] if len(children) == 1 else application
    return None


def _atspi_visible_text(root, pyatspi, node_budget: int, byte_budget: int, deadline: float):
    """Return bounded visible text plus consumed nodes from one AT-SPI subtree."""
    pending = [root]
    values: list[str] = []
    value_set: set[str] = set()
    consumed = 0
    size = 0
    while (
        pending and consumed < node_budget and size < byte_budget
        and time.monotonic() < deadline
    ):
        node = pending.pop()
        consumed += 1
        collect = True
        protected_node = False
        try:
            state = node.getState()
            protected = getattr(pyatspi, "STATE_PROTECTED", None)
            if protected is not None and state.contains(protected):
                protected_node = True
            visible = getattr(pyatspi, "STATE_VISIBLE", None)
            showing = getattr(pyatspi, "STATE_SHOWING", None)
            if (
                visible is not None and showing is not None
                and not state.contains(visible) and not state.contains(showing)
            ):
                collect = False
        except Exception:
            pass
        try:
            role = str(node.getRoleName() or "").casefold()
            if "password" in role:
                protected_node = True
        except Exception:
            pass
        if protected_node:
            continue
        if collect:
            candidates = []
            try:
                candidates.append(str(getattr(node, "name", "") or "").strip()[:1024])
            except Exception:
                pass
            try:
                text = node.queryText()
                candidates.append(str(
                    text.getText(0, min(int(text.characterCount), 4096))
                ).strip())
            except Exception:
                pass
            for candidate in candidates:
                if candidate and candidate not in value_set:
                    candidate = _utf8_prefix(candidate, max(0, byte_budget - size))
                    values.append(candidate)
                    value_set.add(candidate)
                    size += len(candidate.encode("utf-8", "replace"))
        try:
            for index in range(min(int(node.childCount), 64)):
                child = node.getChildAtIndex(index)
                if child is not None:
                    pending.append(child)
        except Exception:
            pass
    return _utf8_prefix("\n".join(values), MAX_ACCESSIBLE_BYTES_PER_WINDOW), consumed


def _accessible_text_for_windows(windows: list[dict]) -> dict[int, str]:
    """Read bounded per-window AT-SPI text; fail closed when unavailable."""
    try:
        import pyatspi  # type: ignore[import-not-found]
        desktop = pyatspi.Registry.getDesktop(0)
    except Exception:
        return {}
    applications = {}
    try:
        for application in desktop:
            with contextlib.suppress(Exception):
                applications[int(application.get_process_id())] = application
    except Exception:
        return {}
    candidates = [
        (index, window, int(window.get("recall_pid") or 0))
        for index, window in enumerate(windows[:64])
        if isinstance(window, dict) and not _capture_protection(window)
    ]
    sibling_count = {
        pid: sum(1 for _index, _window, candidate_pid in candidates if candidate_pid == pid)
        for pid in {pid for _index, _window, pid in candidates if pid > 0}
    }
    deadline = time.monotonic() + MAX_ACCESSIBILITY_SECONDS
    remaining_nodes = MAX_TOTAL_ACCESSIBLE_NODES
    remaining_bytes = MAX_TOTAL_ACCESSIBLE_BYTES
    output: dict[int, str] = {}
    for index, window, pid in candidates:
        if pid <= 0 or pid not in applications or remaining_nodes <= 0 or remaining_bytes <= 0:
            continue
        title = str(window.get("title") or window.get("window_title") or "")[:4096]
        root = _atspi_window_root(applications[pid], title, sibling_count.get(pid, 1))
        if root is None:
            continue
        text, consumed = _atspi_visible_text(
            root,
            pyatspi,
            min(MAX_ACCESSIBLE_NODES_PER_WINDOW, remaining_nodes),
            min(MAX_ACCESSIBLE_BYTES_PER_WINDOW, remaining_bytes),
            deadline,
        )
        remaining_nodes -= consumed
        remaining_bytes -= len(text.encode("utf-8", "replace"))
        if text:
            output[index] = text
        if time.monotonic() >= deadline:
            break
    return output


def _deep_targets(window: dict, files: list[str], title: str) -> list[str]:
    targets = [
        str(value)[:4096]
        for value in list(window.get("deep_targets") or [])[:32]
        if str(value).startswith(("file://", "http://", "https://", "vscode://", "obsidian://"))
    ]
    identity = "\n".join((
        str(window.get("app_name") or ""),
        str(window.get("app_id") or window.get("desktop_file_id") or ""),
    )).casefold()
    for value in files:
        path = Path(value)
        if not path.is_absolute() or not path.is_file() or path.is_symlink():
            continue
        quoted = urllib.parse.quote(str(path))
        if VSCODE_IDENTITY_RE.search(identity):
            targets.append(f"vscode://file/{quoted.lstrip('/')}")
        elif any(token in identity for token in ("idea", "pycharm", "clion", "goland", "webstorm", "rider")):
            targets.append(path.as_uri() + "#jetbrains")
        elif "obsidian" in identity:
            targets.append("obsidian://open?path=" + quoted)
        elif any(token in identity for token in ("libreoffice", "soffice", "writer", "calc", "impress")):
            targets.append(path.as_uri() + "#libreoffice")
        targets.append(path.as_uri())
    targets.extend(URL_RE.findall(title))
    if any(token in identity for token in ("firefox", "chrome", "chromium", "edge", "brave", "vivaldi")):
        targets.extend(URL_RE.findall(str(window.get("accessible_text") or "")))
    return list(dict.fromkeys(targets))[:32]


def _visual_hash_bytes(value: bytes) -> str:
    if not value or Image is None:
        return ""
    try:
        with Image.open(io.BytesIO(value)) as source:
            pixels = list(source.convert("L").resize((8, 8), Image.Resampling.LANCZOS).getdata())
        average = sum(pixels) / len(pixels)
        return f"{int(''.join('1' if pixel >= average else '0' for pixel in pixels), 2):016x}"
    except (OSError, ValueError):
        return ""


def _search_tokens(value: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return re.findall(r"[\w]+", normalized)


def _edit_distance_within(left: str, right: str, limit: int) -> bool:
    """Return early once a bounded Levenshtein distance cannot match."""
    if abs(len(left) - len(right)) > limit:
        return False
    previous = list(range(len(right) + 1))
    for row, left_character in enumerate(left, 1):
        current = [row]
        row_minimum = row
        for column, right_character in enumerate(right, 1):
            current.append(min(
                current[-1] + 1,
                previous[column] + 1,
                previous[column - 1] + (left_character != right_character),
            ))
            row_minimum = min(row_minimum, current[-1])
        if row_minimum > limit:
            return False
        previous = current
    return previous[-1] <= limit


def _fuzzy_ocr_score(query: str, text: str) -> float:
    """Match OCR prefixes and a small number of common recognition errors."""
    queries = _search_tokens(query)[:16]
    targets = _search_tokens(text)
    best = 0.0
    for needle in queries:
        if len(needle) < 4:
            continue
        for candidate in targets:
            if needle == candidate:
                return 1.0
            shorter = min(len(needle), len(candidate))
            longer = max(len(needle), len(candidate))
            if (
                shorter >= 4
                and shorter / max(1, longer) >= 0.5
                and (candidate.startswith(needle) or needle.startswith(candidate))
            ):
                best = max(best, 0.86)
                continue
            if shorter < 4:
                continue
            distance_limit = 2 if longer >= 8 else 1
            if _edit_distance_within(needle, candidate, distance_limit):
                best = max(best, 0.82 if distance_limit == 1 else 0.78)
    return best


def _safe_json(path: Path, maximum: int) -> dict:
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= maximum:
        raise ValueError("Recall capture is not a bounded regular file")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Recall capture root must be an object")
    return value


@dataclass(frozen=True)
class RecallPolicy:
    ocr: bool = False
    semantic: bool = False
    sensitive_filter: bool = True
    excluded_websites: tuple[str, ...] = ()
    quota_mb: int = 512
    retention_hours: int = 24


class RecallVault:
    """AES-GCM record/image store with an ephemeral in-memory FTS5 index."""

    def __init__(self, root: Path, *, test_key: bytes | None = None, semantic_model_path: str = "") -> None:
        self.root = root.resolve()
        self.vault = self.root / "vault"
        self.status_path = self.root / "capture-status.json"
        self._test_key = test_key
        self._key_source = "test" if test_key else "unavailable"
        self.semantic = OfflineSemanticSearch(semantic_model_path or None) if OfflineSemanticSearch else None

    def _ensure(self) -> None:
        if self.root.is_symlink() or self.vault.is_symlink():
            raise ValueError("Refusing symbolic-link Recall storage")
        self.vault.mkdir(parents=True, exist_ok=True, mode=0o700)
        _private(self.root, 0o700)
        _private(self.vault, 0o700)

    def _key(self) -> bytes:
        if AESGCM is None:
            raise RuntimeError("python3-cryptography is required for Privacy Recall")
        if self._test_key:
            return self._test_key
        fallback = self.root / ".vault-key"
        if fallback.is_symlink():
            raise ValueError("Refusing symbolic-link Recall key")
        # A fallback key may have been created while the desktop credential
        # service was locked. Keep using it so that service availability cannot
        # silently make an existing vault undecryptable.
        if fallback.exists():
            encoded = fallback.read_text(encoding="ascii").strip()
            _private(fallback, 0o600)
            self._key_source = "private fallback key file"
            key = base64.urlsafe_b64decode(encoded.encode("ascii"))
            if len(key) != 32:
                raise ValueError("Recall vault key has an invalid length")
            return key
        encoded = None
        if keyring is not None:
            with contextlib.suppress(Exception):
                encoded = keyring.get_password(SERVICE, ACCOUNT)
            if not encoded:
                candidate = base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")
                with contextlib.suppress(Exception):
                    keyring.set_password(SERVICE, ACCOUNT, candidate)
                    encoded = keyring.get_password(SERVICE, ACCOUNT)
            if encoded:
                self._key_source = "operating-system credential store"
        if not encoded:
            # A locked-down fallback keeps the application usable on minimal
            # desktops without Secret Service.  The UI exposes this degraded
            # state so users can keep visual/OCR capture disabled.
            encoded = base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")
            descriptor = os.open(fallback, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="ascii") as output:
                output.write(encoded)
            _private(fallback, 0o600)
            self._key_source = "private fallback key file"
        key = base64.urlsafe_b64decode(encoded.encode("ascii"))
        if len(key) != 32:
            raise ValueError("Recall vault key has an invalid length")
        return key

    def _encrypt(self, data: bytes, aad: bytes) -> bytes:
        nonce = os.urandom(12)
        return MAGIC + nonce + AESGCM(self._key()).encrypt(nonce, data, aad)

    def _decrypt(self, data: bytes, aad: bytes) -> bytes:
        if not data.startswith(MAGIC) or len(data) < len(MAGIC) + 28:
            raise ValueError("Recall vault item has an invalid envelope")
        nonce = data[len(MAGIC):len(MAGIC) + 12]
        return AESGCM(self._key()).decrypt(nonce, data[len(MAGIC) + 12:], aad)

    def _atomic_encrypted(self, target: Path, data: bytes) -> None:
        encrypted = self._encrypt(data, target.name.encode("utf-8"))
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=self.vault)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(encrypted)
                output.flush()
                os.fsync(output.fileno())
            _private(temporary, 0o600)
            os.replace(temporary, target)
            _private(target, 0o600)
        finally:
            temporary.unlink(missing_ok=True)

    def _read_encrypted(self, path: Path, maximum: int) -> bytes:
        if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= maximum:
            raise ValueError("Recall vault item is not a bounded regular file")
        return self._decrypt(path.read_bytes(), path.name.encode("utf-8"))

    def _ocr(self, image: Path) -> tuple[str, list[dict[str, object]]]:
        """Return useful OCR words and normalized positions from Tesseract TSV."""
        working_image = _prepare_ocr_image(image)
        language_args = _tesseract_language_args()
        try:
            result = subprocess.run(
                # Application windows contain scattered controls, labels and
                # document fragments rather than one uniform paragraph. TSV
                # lets us discard low-confidence noise and retain word boxes.
                [
                    "tesseract", str(working_image), "stdout", *language_args, "--oem", "1",
                    "--psm", "11", "--dpi", "180", "-c",
                    "preserve_interword_spaces=1", "tsv",
                ],
                check=False,
                capture_output=True,
                timeout=20,
            )
        except (OSError, subprocess.TimeoutExpired):
            return "", []
        finally:
            if working_image != image:
                working_image.unlink(missing_ok=True)
        if result.returncode != 0:
            return "", []
        decoded = result.stdout[:MAX_OCR_BYTES].decode("utf-8", "replace")
        reader = csv.DictReader(io.StringIO(decoded), delimiter="\t")
        words: list[tuple[tuple[int, int, int], str]] = []
        boxes: list[dict[str, object]] = []
        page_width = page_height = 0
        for row in reader:
            try:
                level = int(row.get("level") or 0)
                if level == 1:
                    page_width = max(page_width, int(row.get("width") or 0))
                    page_height = max(page_height, int(row.get("height") or 0))
                    continue
                if level != 5 or not page_width or not page_height:
                    continue
                text = str(row.get("text") or "").strip()[:128]
                confidence = float(row.get("conf") or -1)
                if (
                    not text or confidence < MIN_OCR_CONFIDENCE
                    or not any(character.isalnum() for character in text)
                    or len(boxes) >= MAX_OCR_BOXES_PER_IMAGE
                ):
                    continue
                left = max(0, int(row.get("left") or 0))
                top = max(0, int(row.get("top") or 0))
                width = max(1, int(row.get("width") or 0))
                height = max(1, int(row.get("height") or 0))
                if left >= page_width or top >= page_height:
                    continue
                width = min(width, page_width - left)
                height = min(height, page_height - top)
                line = (
                    int(row.get("block_num") or 0),
                    int(row.get("par_num") or 0),
                    int(row.get("line_num") or 0),
                )
            except (TypeError, ValueError):
                continue
            words.append((line, text))
            boxes.append({
                "t": text,
                "x": round(left * 10000 / page_width),
                "y": round(top * 10000 / page_height),
                "w": max(1, round(width * 10000 / page_width)),
                "h": max(1, round(height * 10000 / page_height)),
                "c": round(confidence),
            })
        lines: list[str] = []
        current_line = None
        current_words: list[str] = []
        for line, word in words:
            if current_line is not None and line != current_line:
                lines.append(" ".join(current_words))
                current_words = []
            current_line = line
            current_words.append(word)
        if current_words:
            lines.append(" ".join(current_words))
        return "\n".join(lines)[:MAX_OCR_BYTES], boxes

    def _write_status(self, **values: object) -> None:
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        payload = {"updated_at": datetime.now(timezone.utc).isoformat(), **values}
        descriptor, name = tempfile.mkstemp(prefix=".capture-status.", dir=self.root)
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                json.dump(payload, output, ensure_ascii=False)
            _private(temporary, 0o600)
            os.replace(temporary, self.status_path)
        finally:
            temporary.unlink(missing_ok=True)

    def status(self) -> dict[str, object]:
        try:
            value = _safe_json(self.status_path, 64 * 1024)
        except (OSError, ValueError, json.JSONDecodeError):
            value = {"state": "No finalized Recall capture yet"}
        value["encryption"] = self._key_source
        with contextlib.suppress(Exception):
            self._key()
            value["encryption"] = self._key_source
        value["vault_entries"] = len(self._record_paths())
        value["vault_bytes"] = self.storage_bytes()
        return value

    def finalize(self, capture: Path, policy: RecallPolicy) -> dict[str, object]:
        started = time.monotonic()
        self._ensure()
        capture = capture.resolve(strict=True)
        if capture.parent != self.root or not RECORD_RE.fullmatch(capture.name):
            raise ValueError("Recall capture path is outside owned storage")
        payload = _safe_json(capture, MAX_RECORD_BYTES)
        stem = capture.stem
        image_paths = [
            *sorted(self.root.glob(f"{stem}-display-*.jpg"))[:8],
            *sorted(self.root.glob(f"{stem}-window-*.jpg"))[:64],
        ]
        windows = payload.get("windows")
        if not isinstance(windows, list):
            windows = payload.get("x_session_config_objects")
        if not isinstance(windows, list):
            windows = []
        accessible_by_window = _accessible_text_for_windows(windows)
        protected_indexes = {
            index for index, window in enumerate(windows[:512])
            if isinstance(window, dict) and _capture_protection(window)
        }
        valid_images = []
        display_ocr_parts = []
        display_ocr_boxes: dict[int, list[dict[str, object]]] = {}
        window_ocr: dict[int, str] = {}
        window_ocr_boxes: dict[int, list[dict[str, object]]] = {}
        for image in image_paths:
            if image.is_symlink() or not IMAGE_RE.fullmatch(image.name):
                continue
            if not 0 < image.stat().st_size <= MAX_IMAGE_BYTES:
                continue
            image_match = IMAGE_RE.fullmatch(image.name)
            if image_match and (
                (image_match.group(1) == "window" and int(image_match.group(2)) in protected_indexes)
                or (image_match.group(1) == "display" and protected_indexes)
            ):
                continue
            valid_images.append(image)
            if policy.ocr:
                ocr_result = self._ocr(image)
                # Preserve compatibility with third-party test/finalizer
                # integrations that supplied a text-only OCR callback.
                if isinstance(ocr_result, tuple):
                    text, boxes = ocr_result
                else:
                    text, boxes = str(ocr_result), []
                if text:
                    match = IMAGE_RE.fullmatch(image.name)
                    if match and match.group(1) == "window":
                        index = int(match.group(2))
                        window_ocr[index] = text[:MAX_WINDOW_OCR_BYTES]
                        window_ocr_boxes[index] = boxes
                    else:
                        display_ocr_parts.append(text)
                        if match:
                            display_ocr_boxes[int(match.group(2))] = boxes

        apps, titles, files, targets, urls = [], [], [], [], []
        accessible_parts = []
        for window_index, window in enumerate(windows[:512]):
            if not isinstance(window, dict):
                continue
            if window_index in protected_indexes:
                continue
            app = str(
                window.get("app_name") or window.get("app_id") or
                window.get("desktop_file_id") or ""
            )[:512]
            title = str(window.get("title") or window.get("window_title") or "")[:4096]
            if app and app not in apps:
                apps.append(app)
            if title and title not in titles:
                titles.append(title)
            for value in list(window.get("open_files") or [])[:32]:
                value = str(value)[:4096]
                if value and value not in files:
                    files.append(value)
            for value in URL_RE.findall(title):
                if value not in urls:
                    urls.append(value)
            accessible = _utf8_prefix(str(
                window.get("accessible_text") or accessible_by_window.get(window_index, "")
            ), MAX_ACCESSIBLE_BYTES_PER_WINDOW)
            if accessible:
                accessible_parts.append(accessible)
        targets.extend(
            Path(value).as_uri()
            for value in files
            if Path(value).is_absolute() and Path(value).is_file()
        )
        targets.extend(urls)
        searchable = "\n".join([
            *apps, *titles, *files, *accessible_parts, *display_ocr_parts,
            *(text for index, text in window_ocr.items() if index not in protected_indexes)
        ])
        excluded_domains = tuple(value.strip().casefold().lstrip(".") for value in policy.excluded_websites if value.strip())
        if any(any(domain == excluded or domain.endswith(f".{excluded}") for excluded in excluded_domains) for domain in map(_domain, urls) if domain):
            self._discard_legacy(capture, image_paths)
            self._write_status(state="skipped", reason="excluded website", duration_ms=round((time.monotonic() - started) * 1000))
            return {"saved": False, "reason": "excluded website"}
        if policy.sensitive_filter and contains_sensitive_text(searchable):
            self._discard_legacy(capture, image_paths)
            self._write_status(state="skipped", reason="sensitive information detected", duration_ms=round((time.monotonic() - started) * 1000))
            return {"saved": False, "reason": "sensitive information detected"}

        raw_displays = payload.get("recall_displays")
        normalized_displays = []
        if isinstance(raw_displays, list):
            for fallback_index, display in enumerate(raw_displays[:8]):
                if not isinstance(display, dict):
                    continue
                try:
                    normalized = {
                        "index": int(display.get("index", fallback_index)),
                        "x": int(display.get("x", 0)),
                        "y": int(display.get("y", 0)),
                        "width": int(display.get("width", 0)),
                        "height": int(display.get("height", 0)),
                    }
                except (TypeError, ValueError):
                    continue
                if (
                    0 <= normalized["index"] < 8
                    and normalized["width"] > 0
                    and normalized["height"] > 0
                ):
                    normalized_displays.append(normalized)

        image_names = []
        image_hashes = []
        for image in valid_images:
            image_hashes.append(hashlib.sha256(image.read_bytes()).hexdigest())
        previous_path = next(iter(self._record_paths()), None)
        previous = self._load(previous_path) if previous_path else None
        if (
            image_hashes and previous and previous.get("image_hashes") == image_hashes and
            previous.get("apps") == apps and previous.get("titles") == titles
        ):
            self._discard_legacy(capture, image_paths)
            self._write_status(
                state="skipped", reason="screen unchanged", screenshots=len(image_hashes),
                duration_ms=round((time.monotonic() - started) * 1000),
            )
            return {"saved": False, "reason": "screen unchanged"}
        image_hashes = []
        image_index_by_display = {}
        image_index_by_window = {}
        try:
            for image in valid_images:
                raw = image.read_bytes()
                target = self.vault / f"{image.stem}.ssimg"
                self._atomic_encrypted(target, raw)
                match = IMAGE_RE.fullmatch(image.name)
                if match:
                    index = int(match.group(2))
                    if match.group(1) == "display":
                        image_index_by_display[index] = len(image_names)
                    else:
                        image_index_by_window[index] = len(image_names)
                image_names.append(target.name)
                image_hashes.append(hashlib.sha256(raw).hexdigest())
        except Exception:
            for name in image_names:
                (self.vault / name).unlink(missing_ok=True)
            raise
        for display in normalized_displays:
            display["image_index"] = image_index_by_display.get(display["index"], -1)
        normalized_windows = []
        remaining_window_ocr = MAX_TOTAL_WINDOW_OCR_BYTES
        remaining_window_boxes = MAX_TOTAL_WINDOW_OCR_BOXES
        for window_index, window in enumerate(windows[:512]):
            if not isinstance(window, dict):
                continue
            if window_index in protected_indexes:
                continue
            position = window.get("window_position") or {}
            ocr_text = window_ocr.get(window_index, "")[:remaining_window_ocr]
            remaining_window_ocr -= len(ocr_text)
            ocr_boxes = window_ocr_boxes.get(window_index, [])[:remaining_window_boxes]
            remaining_window_boxes -= len(ocr_boxes)
            window_files = [str(value)[:4096] for value in list(window.get("open_files") or [])[:32]]
            window_title = str(window.get("title") or window.get("window_title") or "")[:4096]
            normalized_windows.append({
                "app": str(window.get("app_name") or window.get("app_id") or window.get("desktop_file_id") or "")[:512],
                "app_id": str(window.get("app_id") or window.get("desktop_file_id") or "")[:512],
                "title": window_title,
                "files": window_files,
                "accessible_text": _utf8_prefix(str(
                    window.get("accessible_text") or accessible_by_window.get(window_index, "")
                ), MAX_ACCESSIBLE_BYTES_PER_WINDOW),
                "targets": _deep_targets(window, window_files, window_title),
                "monitor": int(window.get("monitor_number", window.get("monitor", 0)) or 0),
                "workspace": int(window.get("desktop_number", window.get("workspace", 0)) or 0),
                "focused": bool(window.get("recall_focused", False)),
                "x": int(position.get("x_offset", (window.get("geometry") or [0, 0, 0, 0])[0]) or 0),
                "y": int(position.get("y_offset", (window.get("geometry") or [0, 0, 0, 0])[1]) or 0),
                "width": int(position.get("width", (window.get("geometry") or [0, 0, 0, 0])[2]) or 0),
                "height": int(position.get("height", (window.get("geometry") or [0, 0, 0, 0])[3]) or 0),
                "image_index": image_index_by_window.get(window_index, -1),
                "ocr_text": ocr_text,
                "ocr_boxes": ocr_boxes,
            })
        source_diagnostics = payload.get("recall_capture_diagnostics")
        if not isinstance(source_diagnostics, dict):
            source_diagnostics = {}
        try:
            expected_windows = max(
                min(len(windows), 64),
                min(max(0, int(source_diagnostics.get("expected_windows") or 0)), 64),
            )
            excluded_windows = min(
                max(0, int(source_diagnostics.get("excluded_windows") or 0)), 64
            )
        except (TypeError, ValueError):
            expected_windows = min(len(windows), 64)
            excluded_windows = 0
        eligible_windows = min(len(normalized_windows), 64)
        captured_window_images = sum(
            1 for window in normalized_windows if int(window.get("image_index", -1)) >= 0
        )
        record = {
            "schema": 3,
            "captured_at": payload.get("captured_at") or payload.get("session_create_time"),
            "modified": capture.stat().st_mtime,
            "platform": payload.get("platform", "linux"),
            "desktop": payload.get("desktop", "GNOME"),
            "apps": apps,
            "titles": titles,
            "files": files,
            "urls": urls,
            "targets": targets[:128],
            "ocr_text": "\n".join(display_ocr_parts)[:MAX_OCR_BYTES],
            "display_ocr_boxes": {
                str(index): boxes[:MAX_DISPLAY_OCR_BOXES]
                for index, boxes in display_ocr_boxes.items()
            },
            "windows": normalized_windows,
            "displays": normalized_displays,
            "images": image_names,
            "image_hashes": image_hashes,
            "scene_id": _visual_hash_bytes(valid_images[0].read_bytes()) if valid_images else "",
            "annotations": {"bookmarked": False, "collection": "", "note": ""},
            "ocr_diagnostics": {
                "state": "completed" if policy.ocr else "disabled",
                "engine": "tesseract",
                "images_indexed": len(valid_images) if policy.ocr else 0,
                "recognized_characters": len("\n".join(display_ocr_parts)) + sum(len(value) for value in window_ocr.values()),
            },
            "capture_diagnostics": {
                "expected_windows": expected_windows,
                "eligible_windows": eligible_windows,
                "captured_window_images": captured_window_images,
                "missing_window_images": max(0, eligible_windows - captured_window_images),
                "excluded_windows": excluded_windows,
                "protected_windows": len(protected_indexes),
                "accessibility_indexed_windows": sum(
                    1 for window in normalized_windows if window.get("accessible_text")
                ),
                "display_overview_captured": any(
                    int(display.get("image_index", -1)) >= 0 for display in normalized_displays
                ),
            },
            "privacy": {
                "sensitive_filter": policy.sensitive_filter,
                "protected_context_visible": bool(protected_indexes),
                "shared_display_withheld": bool(protected_indexes),
            },
        }
        record_target = self.vault / f"{stem}.ssrec"
        record_bytes = json.dumps(
            record, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        if len(record_bytes) > MAX_RECORD_BYTES:
            for name in image_names:
                (self.vault / name).unlink(missing_ok=True)
            raise ValueError("Privacy Recall entry exceeds the metadata safety limit")
        try:
            self._atomic_encrypted(record_target, record_bytes)
        except Exception:
            for name in image_names:
                (self.vault / name).unlink(missing_ok=True)
            raise
        self._discard_legacy(capture, image_paths)
        self.prune(policy.quota_mb, policy.retention_hours)
        duration = round((time.monotonic() - started) * 1000)
        ocr_characters = len(record["ocr_text"]) + sum(
            len(str(window.get("ocr_text", ""))) for window in normalized_windows
        )
        self._write_status(
            state="saved", duration_ms=duration, screenshots=len(image_names),
            ocr_characters=ocr_characters, record=record_target.name,
        )
        return {"saved": True, "record": record_target.name, "duration_ms": duration, "screenshots": len(image_names)}

    @staticmethod
    def _discard_legacy(capture: Path, images: list[Path]) -> None:
        capture.unlink(missing_ok=True)
        for image in images:
            image.unlink(missing_ok=True)

    def migrate_legacy(self, policy: RecallPolicy) -> int:
        if not self.root.is_dir() or self.root.is_symlink():
            return 0
        migrated = 0
        for path in sorted(self.root.glob("recall-*.json")):
            if RECORD_RE.fullmatch(path.name):
                # Metadata appears before the asynchronous preview. Leave new
                # captures to the Shell-launched finalizer so search cannot
                # migrate a record before its screenshot arrives.
                if time.time() - path.stat().st_mtime < 120:
                    continue
                with contextlib.suppress(Exception):
                    self.finalize(path, policy)
                    migrated += 1
        return migrated

    def _record_paths(self) -> list[Path]:
        if not self.vault.is_dir() or self.vault.is_symlink():
            return []
        return sorted(
            (path for path in self.vault.glob("*.ssrec") if VAULT_RE.fullmatch(path.name) and path.is_file() and not path.is_symlink()),
            key=lambda path: path.stat().st_mtime_ns,
            reverse=True,
        )

    def _load(self, path: Path) -> dict[str, object] | None:
        try:
            value = json.loads(self._read_encrypted(path, MAX_RECORD_BYTES + MAX_OCR_BYTES).decode("utf-8"))
            return value if value.get("schema") == 3 else None
        except (OSError, ValueError, json.JSONDecodeError):
            return None

    def search(self, query: str = "", *, app: str = "", day: str = "", semantic: bool = False, excluded_apps: tuple[str, ...] = (), limit: int = 100) -> list[dict[str, object]]:
        records = [(path, self._load(path)) for path in self._record_paths()]
        records = [(path, value) for path, value in records if value]
        exclusion_tokens = tuple(
            token.strip().casefold() for token in excluded_apps if token.strip()
        )
        connection = sqlite3.connect(":memory:")
        try:
            connection.execute(
                "CREATE VIRTUAL TABLE recall_windows USING fts5("
                "key UNINDEXED, app, title, files, accessible, ocr)"
            )
            connection.execute(
                "CREATE VIRTUAL TABLE recall_visual USING fts5(name UNINDEXED, ocr)"
            )
            loaded = []
            for path, value in records:
                captured = str(value.get("captured_at") or "")
                if day and not captured.startswith(day):
                    continue
                visible_windows = []
                excluded_visible = False
                for index, window in enumerate(value.get("windows", [])[:512]):
                    if not isinstance(window, dict):
                        continue
                    identity = "\n".join(
                        (str(window.get("app", "")), str(window.get("app_id", "")))
                    ).casefold()
                    if any(token in identity for token in exclusion_tokens):
                        excluded_visible = True
                        continue
                    visible_windows.append((index, window))
                    connection.execute(
                        "INSERT INTO recall_windows VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            f"{path.name}#{index}",
                            str(window.get("app", "")),
                            str(window.get("title", "")),
                            "\n".join(str(item) for item in window.get("files", [])),
                            str(window.get("accessible_text", "")),
                            str(window.get("ocr_text", "")),
                        ),
                    )
                if not visible_windows:
                    continue
                preview_allowed = not excluded_visible
                if preview_allowed:
                    connection.execute(
                        "INSERT INTO recall_visual VALUES (?, ?)",
                        (path.name, str(value.get("ocr_text", ""))),
                    )
                loaded.append((path, value, visible_windows, preview_allowed))

            window_candidates: dict[str, float] = {}
            visual_candidates: dict[str, float] = {}
            fuzzy_ocr_candidates: set[str] = set()
            needle = query.strip()[:256]
            if needle:
                tokens = re.findall(r"[\w.-]+", needle.casefold())[:16]
                expression = " OR ".join(f'"{token.replace(chr(34), "")}"' for token in tokens if token)
                if expression:
                    with contextlib.suppress(sqlite3.OperationalError):
                        for key, rank in connection.execute(
                            "SELECT key, bm25(recall_windows, 0, 6, 5, 3, 4, 2) "
                            "FROM recall_windows WHERE recall_windows MATCH ? "
                            "ORDER BY 2 LIMIT 500",
                            (expression,),
                        ):
                            window_candidates[key] = -float(rank)
                    with contextlib.suppress(sqlite3.OperationalError):
                        for name, rank in connection.execute(
                            "SELECT name, bm25(recall_visual, 0, 2) "
                            "FROM recall_visual WHERE recall_visual MATCH ? "
                            "ORDER BY 2 LIMIT 100",
                            (expression,),
                        ):
                            visual_candidates[name] = -float(rank)
                # OCR commonly substitutes one glyph (for example O/0) or
                # splits a long word. Apply a bounded, recent-first fallback
                # without creating a persistent plaintext index.
                remaining_fuzzy_bytes = FUZZY_OCR_SCAN_BYTES
                for path, _value, windows, _preview_allowed in loaded:
                    for index, window in windows:
                        key = f"{path.name}#{index}"
                        if key in window_candidates:
                            continue
                        ocr_text = str(window.get("ocr_text", ""))
                        remaining_fuzzy_bytes -= len(ocr_text.encode("utf-8"))
                        score = _fuzzy_ocr_score(needle, ocr_text)
                        if score:
                            window_candidates[key] = score * 0.35
                            fuzzy_ocr_candidates.add(key)
                        if remaining_fuzzy_bytes <= 0:
                            break
                    if remaining_fuzzy_bytes <= 0:
                        break
            if needle and semantic:
                documents: dict[str, str] = {}
                for path, _value, windows, _preview_allowed in loaded:
                    for index, window in windows:
                        documents[f"{path.name}#{index}"] = " ".join([
                            str(window.get("app", "")), str(window.get("title", "")),
                            *(str(item) for item in window.get("files", [])),
                            str(window.get("accessible_text", "")),
                            str(window.get("ocr_text", "")),
                        ])
                if self.semantic is not None:
                    for key, score in self.semantic.rank(needle, documents).items():
                        window_candidates[key] = max(window_candidates.get(key, 0.0), score * 4.0)
            output = []
            for path, value, windows, preview_allowed in loaded:
                common = {
                    "name": path.name,
                    "captured_at": value.get("captured_at"),
                    "modified": float(value.get("modified") or path.stat().st_mtime),
                    "image_count": len(value.get("images", [])) if preview_allowed else 0,
                    "displays": value.get("displays", []) if preview_allowed else [],
                    "capture_diagnostics": value.get("capture_diagnostics", {}),
                    "privacy": value.get("privacy", {}),
                    "annotations": value.get("annotations", {}),
                    "scene_id": value.get("scene_id", ""),
                    "ocr_diagnostics": value.get("ocr_diagnostics", {}),
                }
                if not needle and not app:
                    apps = list(dict.fromkeys(
                        str(window.get("app", ""))
                        for _index, window in windows if window.get("app")
                    ))
                    titles = list(dict.fromkeys(
                        str(window.get("title", ""))
                        for _index, window in windows if window.get("title")
                    ))
                    files = list(dict.fromkeys(
                        str(item) for _index, window in windows
                        for item in window.get("files", [])
                    ))
                    urls = list(dict.fromkeys(URL_RE.findall("\n".join(titles))))
                    output.append({
                        **common,
                        "apps": apps,
                        "titles": titles,
                        "files": files,
                        "urls": urls,
                        "targets": list(dict.fromkeys([
                            *(str(target) for _index, window in windows for target in window.get("targets", [])),
                            *self._targets(files, urls),
                        ]))[:32],
                        "windows": [window for _index, window in windows],
                        "rank": 0.0,
                        "match_type": "Timeline",
                        "result_kind": "timeline",
                        "ocr_excerpt": self._excerpt(
                            str(value.get("ocr_text", "")), needle
                        ),
                    })
                    continue

                for index, window in windows:
                    app_token = app.casefold()
                    identities = {
                        str(window.get("app", "")).casefold(),
                        str(window.get("app_id", "")).casefold(),
                    }
                    if app and app_token not in identities:
                        continue
                    key = f"{path.name}#{index}"
                    if needle and key not in window_candidates:
                        continue
                    files = [str(item) for item in window.get("files", [])]
                    urls = list(dict.fromkeys(
                        URL_RE.findall(str(window.get("title", "")))
                    ))
                    rank = window_candidates.get(key, 0.0)
                    if window.get("focused"):
                        rank += 0.15
                    output.append({
                        **common,
                        "apps": [str(window.get("app", ""))] if window.get("app") else [],
                        "titles": [str(window.get("title", ""))] if window.get("title") else [],
                        "files": files,
                        "urls": urls,
                        "targets": list(dict.fromkeys([
                            *(str(target) for target in window.get("targets", [])),
                            *self._targets(files, urls),
                        ]))[:32],
                        # Keep the matched window explicit for ranking and
                        # highlighting, but let the gallery browse the whole
                        # captured desktop moment from this search result.
                        "windows": [visible for _visible_index, visible in windows],
                        "matched_window": window,
                        "window_index": index,
                        "rank": round(rank, 4),
                        "match_type": (
                            "Window image text"
                            if key in fuzzy_ocr_candidates
                            else self._window_match_type(window, needle)
                        ),
                        "result_kind": "window",
                        "highlight_boxes": self._matching_ocr_boxes(window, needle),
                        "highlight_image_index": int(window.get("image_index", -1)),
                        "ocr_excerpt": self._excerpt(
                            str(window.get("ocr_text", "")), needle
                        ),
                    })

                if needle and not app and path.name in visual_candidates:
                    apps = list(dict.fromkeys(
                        str(window.get("app", ""))
                        for _index, window in windows if window.get("app")
                    ))
                    titles = list(dict.fromkeys(
                        str(window.get("title", ""))
                        for _index, window in windows if window.get("title")
                    ))
                    output.append({
                        **common,
                        "apps": apps,
                        "titles": titles,
                        "files": [],
                        "urls": [],
                        "targets": [],
                        "windows": [window for _index, window in windows],
                        "rank": round(visual_candidates[path.name], 4),
                        "match_type": "Visual text",
                        "result_kind": "visual",
                        **self._display_highlights(value, needle),
                        "ocr_excerpt": self._excerpt(
                            str(value.get("ocr_text", "")), needle
                        ),
                    })
            output.sort(key=lambda item: (-float(item["rank"]), -float(item.get("modified") or 0)))
            return output[:max(1, min(250, int(limit)))]
        finally:
            connection.close()

    @staticmethod
    def _targets(files: list[str], urls: list[str]) -> list[str]:
        targets = [
            Path(value).as_uri()
            for value in files
            if Path(value).is_absolute() and Path(value).is_file()
        ]
        targets.extend(urls)
        return list(dict.fromkeys(targets))[:32]

    @staticmethod
    def _window_match_type(window: dict, query: str) -> str:
        needle = query.casefold()
        if not needle:
            return "Window"
        if needle in str(window.get("title", "")).casefold():
            return "Window text"
        if any(needle in str(value).casefold() for value in window.get("files", [])):
            return "Window file"
        if needle in str(window.get("ocr_text", "")).casefold():
            return "Window image text"
        if needle in str(window.get("accessible_text", "")).casefold():
            return "Application content"
        if needle in "\n".join(
            (str(window.get("app", "")), str(window.get("app_id", "")))
        ).casefold():
            return "Application"
        return "Related window"

    @staticmethod
    def _matching_ocr_boxes(window: dict, query: str) -> list[dict[str, object]]:
        """Return only encrypted OCR boxes that plausibly match this query."""
        query_tokens = _search_tokens(query)[:16]
        if not query_tokens:
            return []
        matches = []
        for box in window.get("ocr_boxes", [])[:MAX_OCR_BOXES_PER_IMAGE]:
            if not isinstance(box, dict):
                continue
            word = str(box.get("t") or "")
            word_tokens = _search_tokens(word)
            if not word_tokens:
                continue
            matched = any(
                needle == candidate
                or (len(needle) >= 3 and needle in candidate)
                or _fuzzy_ocr_score(needle, candidate) >= 0.78
                for needle in query_tokens
                for candidate in word_tokens
            )
            if matched:
                matches.append({
                    key: box[key] for key in ("t", "x", "y", "w", "h", "c")
                    if key in box
                })
            if len(matches) >= 64:
                break
        return matches

    @classmethod
    def _display_highlights(cls, value: dict, query: str) -> dict[str, object]:
        boxes_by_display = value.get("display_ocr_boxes", {})
        if not isinstance(boxes_by_display, dict):
            return {"highlight_boxes": []}
        displays = {
            str(display.get("index")): display
            for display in value.get("displays", [])
            if isinstance(display, dict)
        }
        for display_index, boxes in boxes_by_display.items():
            matches = cls._matching_ocr_boxes({"ocr_boxes": boxes}, query)
            display = displays.get(str(display_index))
            if matches and display:
                return {
                    "highlight_boxes": matches,
                    "highlight_image_index": int(display.get("image_index", -1)),
                }
        return {"highlight_boxes": []}

    @staticmethod
    def _match_type(value: dict, query: str) -> str:
        needle = query.casefold()
        if not needle:
            return "Timeline"
        if needle in "\n".join(value.get("titles", [])).casefold():
            return "Text"
        if needle in str(value.get("ocr_text", "")).casefold():
            return "OCR"
        if needle in "\n".join(value.get("files", [])).casefold():
            return "File"
        if needle in "\n".join(value.get("apps", [])).casefold():
            return "Application"
        return "Related"

    @staticmethod
    def _excerpt(text: str, query: str) -> str:
        compact = " ".join(text.split())
        if not compact:
            return ""
        index = compact.casefold().find(query.casefold()) if query else 0
        index = max(0, index)
        return compact[max(0, index - 80):index + 240]

    def preview_bytes(self, record_name: str, index: int = 0) -> bytes | None:
        if not VAULT_RE.fullmatch(record_name):
            return None
        value = self._load(self.vault / record_name)
        images = value.get("images", []) if value else []
        if not 0 <= index < len(images):
            return None
        image_name = str(images[index])
        if not VAULT_IMAGE_RE.fullmatch(image_name):
            return None
        with contextlib.suppress(OSError, ValueError):
            return self._read_encrypted(self.vault / image_name, MAX_IMAGE_BYTES + 128)
        return None

    def annotate(self, record_name: str, *, bookmarked=None, collection=None, note=None) -> dict[str, object]:
        if not VAULT_RE.fullmatch(record_name):
            raise ValueError("Invalid Recall record")
        path = self.vault / record_name
        value = self._load(path)
        if not value:
            raise ValueError("Recall record is unavailable")
        annotations = dict(value.get("annotations") or {})
        if bookmarked is not None:
            annotations["bookmarked"] = bool(bookmarked)
        if collection is not None:
            annotations["collection"] = str(collection).strip()[:128]
        if note is not None:
            annotations["note"] = str(note).strip()[:4096]
        value["annotations"] = annotations
        value["modified"] = time.time()
        self._atomic_encrypted(path, json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode())
        return annotations

    @staticmethod
    def group_scenes(results: list[dict[str, object]]) -> list[dict[str, object]]:
        grouped = []
        for result in results:
            visual = str(result.get("scene_id") or "")
            previous = grouped[-1] if grouped else None
            distance = 65
            if previous and visual and previous.get("scene_id"):
                with contextlib.suppress(ValueError):
                    distance = (int(visual, 16) ^ int(str(previous["scene_id"]), 16)).bit_count()
            if previous and visual and distance <= 5:
                previous["scene_count"] = int(previous.get("scene_count") or 1) + 1
                previous["scene_started_at"] = result.get("captured_at")
            else:
                item = dict(result)
                item.update({"scene_count": 1, "scene_started_at": result.get("captured_at"), "scene_finished_at": result.get("captured_at")})
                grouped.append(item)
        return grouped

    def reindex(self, record_name: str) -> dict[str, object]:
        if not VAULT_RE.fullmatch(record_name):
            raise ValueError("Invalid Recall record")
        path = self.vault / record_name
        value = self._load(path)
        if not value:
            raise ValueError("Recall record is unavailable")
        indexed = 0
        display_boxes: dict[str, list] = {}
        display_text: list[str] = []
        windows_by_image = {
            int(window.get("image_index", -1)): window
            for window in value.get("windows", []) if isinstance(window, dict)
        }
        displays_by_image = {
            int(display.get("image_index", -1)): display
            for display in value.get("displays", []) if isinstance(display, dict)
        }
        for index, image_name in enumerate(value.get("images", [])[:72]):
            raw = self.preview_bytes(record_name, index)
            if raw is None:
                continue
            descriptor, temporary_name = tempfile.mkstemp(prefix="sessionsifu-reindex-", suffix=".jpg")
            temporary = Path(temporary_name)
            try:
                with os.fdopen(descriptor, "wb") as output:
                    output.write(raw)
                text, boxes = self._ocr(temporary)
            finally:
                temporary.unlink(missing_ok=True)
            if index in windows_by_image:
                windows_by_image[index]["ocr_text"] = text[:MAX_WINDOW_OCR_BYTES]
                windows_by_image[index]["ocr_boxes"] = boxes[:MAX_OCR_BOXES_PER_IMAGE]
            elif index in displays_by_image:
                display_index = str(displays_by_image[index].get("index", index))
                display_boxes[display_index] = boxes[:MAX_DISPLAY_OCR_BOXES]
                display_text.append(text)
            indexed += 1
        value["ocr_text"] = "\n".join(display_text)[:MAX_OCR_BYTES]
        value["display_ocr_boxes"] = display_boxes
        value["ocr_diagnostics"] = {
            "state": "completed", "engine": "tesseract", "images_indexed": indexed,
            "recognized_characters": len(str(value.get("ocr_text") or "")) + sum(
                len(str(window.get("ocr_text") or "")) for window in value.get("windows", []) if isinstance(window, dict)
            ),
        }
        value["modified"] = time.time()
        payload = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
        if len(payload) > MAX_RECORD_BYTES:
            raise ValueError("Reindexed Recall record exceeds the safety limit")
        self._atomic_encrypted(path, payload)
        return {"record": record_name, **dict(value["ocr_diagnostics"])}

    def ask(self, question: str, limit: int = 8) -> dict[str, object]:
        question = question.strip()[:256]
        if not question:
            raise ValueError("A question is required")
        matches = self.search(question, semantic=True, limit=limit)
        citations = []
        excerpts = []
        for item in matches[:limit]:
            excerpt = str(item.get("ocr_excerpt") or "") or " — ".join(str(value) for value in item.get("titles", [])[:2])
            citations.append({
                "record": item.get("name"), "captured_at": item.get("captured_at"),
                "application": next(iter(item.get("apps", [])), ""),
                "title": next(iter(item.get("titles", [])), ""), "excerpt": excerpt[:320],
            })
            if excerpt:
                excerpts.append(excerpt[:240])
        return {
            "question": question,
            "answer": "No matching local history was found." if not citations else "The closest local evidence is: " + " ".join(excerpts[:3]),
            "citations": citations,
        }

    def diagnostics(self) -> dict[str, object]:
        return {
            "entries": len(self._record_paths()), "storage_bytes": self.storage_bytes(),
            "semantic": self.semantic.diagnostics() if self.semantic is not None else {"available": False, "error": "semantic component unavailable"},
        }

    def export_records(self):
        for path in self._record_paths():
            value = self._load(path)
            if not value:
                continue
            images = []
            for index, _name in enumerate(value.get("images", [])):
                data = self.preview_bytes(path.name, index)
                if data is not None:
                    images.append(data)
            yield path.stem, value, images

    def import_record(self, value: dict[str, object], images: list[bytes]) -> Path:
        self._ensure()
        if value.get("schema") != 3 or not isinstance(value.get("windows"), list):
            raise ValueError("Recall archive record is incompatible")
        payload = json.loads(json.dumps(value))
        if len(images) != len(payload.get("images", [])) or any(
            not isinstance(image, bytes) or not 0 < len(image) <= MAX_IMAGE_BYTES
            for image in images
        ):
            raise ValueError("Recall archive has missing or oversized images")
        stamp = datetime.now(timezone.utc).strftime("recall-%Y%m%d-%H%M%S-%f")[:26]
        while (self.vault / f"{stamp}.ssrec").exists():
            time.sleep(0.002)
            stamp = datetime.now(timezone.utc).strftime("recall-%Y%m%d-%H%M%S-%f")[:26]
        names = []
        written = []
        try:
            for index, (old_name, raw) in enumerate(zip(payload.get("images", []), images)):
                match = re.search(r"-(display|window)-(\d+)\.ssimg$", str(old_name))
                suffix = f"-{match.group(1)}-{match.group(2)}" if match else f"-window-{index}"
                name = f"{stamp}{suffix}.ssimg"
                target = self.vault / name
                self._atomic_encrypted(target, raw)
                names.append(name)
                written.append(target)
            payload["images"] = names
            payload["modified"] = time.time()
            target = self.vault / f"{stamp}.ssrec"
            encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
            if len(encoded) > MAX_RECORD_BYTES:
                raise ValueError("Imported Recall record exceeds the metadata limit")
            self._atomic_encrypted(target, encoded)
            return target
        except Exception:
            for path in written:
                path.unlink(missing_ok=True)
            raise

    def delete(self, *, record: str = "", app: str = "", website: str = "", before: float | None = None, after: float | None = None) -> int:
        removed = 0
        for path in self._record_paths():
            value = self._load(path)
            if not value:
                continue
            modified = float(value.get("modified") or 0)
            matches = bool(record and path.name == record)
            matches = matches or bool(app and app.casefold() in "\n".join(value.get("apps", [])).casefold())
            matches = matches or bool(website and website.casefold() in "\n".join(value.get("urls", [])).casefold())
            matches = matches or bool(before is not None and modified < before)
            matches = matches or bool(after is not None and modified > after)
            if not any((record, app, website, before is not None, after is not None)):
                matches = True
            if not matches:
                continue
            for image_name in value.get("images", []):
                with contextlib.suppress(OSError):
                    (self.vault / str(image_name)).unlink(missing_ok=True)
            path.unlink(missing_ok=True)
            removed += 1
        return removed

    def storage_bytes(self) -> int:
        if not self.vault.is_dir():
            return 0
        return sum(path.stat().st_size for path in self.vault.iterdir() if path.is_file() and not path.is_symlink())

    def prune(self, quota_mb: int, retention_hours: int = 24 * 30) -> None:
        quota = max(64, min(16_384, int(quota_mb))) * 1024 * 1024
        cutoff = time.time() - max(1, min(24 * 365, int(retention_hours))) * 3600
        paths = self._record_paths()
        for index, path in enumerate(paths):
            value = self._load(path)
            if index >= MAX_ENTRIES or path.stat().st_mtime < cutoff or self.storage_bytes() > quota:
                if value:
                    for image in value.get("images", []):
                        with contextlib.suppress(OSError):
                            (self.vault / str(image)).unlink(missing_ok=True)
                path.unlink(missing_ok=True)
        referenced = {
            str(image)
            for path in self._record_paths()
            for value in [self._load(path)]
            if value
            for image in value.get("images", [])
        }
        for image in self.vault.glob("*.ssimg"):
            if (
                VAULT_IMAGE_RE.fullmatch(image.name)
                and image.name not in referenced
                and image.is_file()
                and not image.is_symlink()
            ):
                image.unlink(missing_ok=True)
        # Interrupted or legacy finalizers may leave compressed screenshots in
        # the plaintext staging directory. Keep a short grace period for an
        # overlapping capture, then remove files that can no longer belong to
        # a live finalization job.
        plaintext_cutoff = time.time() - 120
        for image in self.root.glob("recall-*"):
            if (
                PLAINTEXT_IMAGE_RE.fullmatch(image.name)
                and image.is_file()
                and not image.is_symlink()
                and image.stat().st_mtime < plaintext_cutoff
            ):
                image.unlink(missing_ok=True)
