"""Encrypted, bounded and searchable cross-platform Privacy Recall vault."""

from __future__ import annotations

import base64
import csv
import contextlib
import io
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.parse
import threading
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

try:
    import keyring
except ImportError:  # Linux system packages may intentionally omit it.
    keyring = None

try:
    from PIL import Image, ImageFilter, ImageOps
except ImportError:  # pragma: no cover - source checkout fallback
    Image = ImageFilter = ImageOps = None

from .model import SessionSnapshot, WindowSnapshot
from .semantic import OfflineSemanticSearch

RECALL_SCHEMA = 3
RECALL_MAX_ENTRIES = 500
MAX_RECALL_BYTES = 3 * 1024 * 1024
MAX_PREVIEW_BYTES = 8 * 1024 * 1024
MAX_RECORD_CACHE_BYTES = 128 * 1024 * 1024
MAX_WINDOW_PREVIEWS = 64
MAX_WINDOW_OCR_BYTES = 16 * 1024
MAX_TOTAL_WINDOW_OCR_BYTES = 512 * 1024
MAX_OCR_BOXES_PER_IMAGE = 512
MAX_TOTAL_WINDOW_OCR_BOXES = 4096
MIN_OCR_CONFIDENCE = 30.0
MAX_OCR_WORKING_EDGE = 2400
_TESSERACT_LANGUAGE_ARGS: tuple[str, ...] | None = None
TESSERACT_LANGUAGE_ALIASES = {
    "cs": "ces", "de": "deu", "es": "spa", "fr": "fra", "it": "ita",
    "nl": "nld", "pl": "pol", "pt": "por", "sk": "slk", "uk": "ukr",
}
MAX_BUNDLED_MODEL_BYTES = 16 * 1024 * 1024
DEFAULT_RETENTION_HOURS = 24
DEFAULT_EXCLUSIONS = ("sessionsifu",)
MAGIC = b"SSRF1\0"
KEYRING_SERVICE = "org.sessionsifu.RecallVault"
KEYRING_ACCOUNT = "default"
RECORD_RE = re.compile(r"^recall-\d{8}-\d{6}-\d{6}\.ssrec$")
IMAGE_RE = re.compile(
    r"^recall-\d{8}-\d{6}-\d{6}(?:-window-\d{1,3})?\.ssimg$"
)
SENSITIVE_RE = re.compile(
    r"\b(?:password|passcode|security code|cvv|cvc|secret key|private key)\b",
    re.IGNORECASE,
)
URL_RE = re.compile(r"https?://[^\s<>{}\[\]\"']+", re.IGNORECASE)


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


def _contains_sensitive(text: str) -> bool:
    if SENSITIVE_RE.search(text):
        return True
    card_pattern = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
    return any(_luhn(match.group(0)) for match in card_pattern.finditer(text))


def _domain(value: str) -> str:
    try:
        return (urllib.parse.urlparse(value).hostname or "").casefold()
    except ValueError:
        return ""


def _private_mode(path: Path, mode: int) -> None:
    with contextlib.suppress(OSError):
        path.chmod(mode)


def _prepare_ocr_image(image: Path) -> Path:
    """Return a private, sharpened OCR copy without enlarging stored previews."""
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
            _private_mode(temporary, 0o600)
            return temporary
    except (OSError, ValueError):
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        return image


def _tesseract_language_args() -> tuple[str, ...]:
    """Select an installed locale model and retain English UI recognition."""
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
    """Locate signed OCR resources in source, installed and frozen layouts."""
    module = Path(__file__).resolve()
    candidates = [
        Path(os.environ["SESSIONSIFU_TESSDATA_DIR"])
        if os.environ.get("SESSIONSIFU_TESSDATA_DIR") else None,
        Path(getattr(sys, "_MEIPASS", "")) / "tessdata"
        if getattr(sys, "_MEIPASS", "") else None,
        Path("/usr/share/sessionsifu/tessdata"),
        module.parent.parent / "tessdata",
        module.parents[2] / "ocr/tessdata",
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


def _matching_ocr_boxes(boxes: object, query: str) -> list[dict]:
    tokens = re.findall(r"[\w]+", query.casefold())[:16]
    if not tokens or not isinstance(boxes, list):
        return []
    matches = []
    for box in boxes[:MAX_OCR_BOXES_PER_IMAGE]:
        if not isinstance(box, dict):
            continue
        word = str(box.get("t") or "").casefold()
        if any(token == word or (len(token) >= 3 and token in word) for token in tokens):
            matches.append({
                key: box[key] for key in ("t", "x", "y", "w", "h", "c")
                if key in box
            })
        if len(matches) >= 64:
            break
    return matches


def _matches_exclusion(window: WindowSnapshot, exclusions: tuple[str, ...]) -> bool:
    identity = "\n".join((window.app_id, window.app_name, Path(window.executable).name)).casefold()
    return any(token and token in identity for token in exclusions)


class RecallStore:
    """AES-GCM activity records with ephemeral FTS5 indexing."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.recall_dir = root / "recall"
        self.vault_dir = self.recall_dir / "vault"
        self.semantic = OfflineSemanticSearch()
        self._search_lock = threading.RLock()
        self._record_cache: OrderedDict[str, tuple[tuple[int, int], dict, int]] = OrderedDict()
        self._record_cache_bytes = 0
        self._index_signature: tuple[tuple[str, int, int], ...] = ()
        self._index_connection: sqlite3.Connection | None = None
        self._storage_cache: tuple[int, int] | None = None

    def _ensure_directory(self) -> None:
        if self.recall_dir.is_symlink() or self.vault_dir.is_symlink():
            raise ValueError("Refusing to use a symbolic link for Privacy Recall storage")
        self.vault_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        _private_mode(self.recall_dir, 0o700)
        _private_mode(self.vault_dir, 0o700)

    def _key(self) -> bytes:
        override = os.environ.get("SESSIONSIFU_RECALL_TEST_KEY", "")
        if override:
            key = base64.urlsafe_b64decode(override.encode("ascii"))
            if len(key) != 32:
                raise ValueError("Invalid test Recall key")
            return key
        key_path = self.recall_dir / ".vault-key"
        if key_path.is_symlink():
            raise ValueError("Refusing a symbolic-link Recall key")
        # Keep existing file-backed vaults decryptable after this upgrade.
        if key_path.exists():
            _private_mode(key_path, 0o600)
            key = key_path.read_bytes()
            if len(key) != 32:
                raise ValueError("Invalid Recall vault key")
            return key
        if keyring is not None:
            try:
                encoded = keyring.get_password(KEYRING_SERVICE, KEYRING_ACCOUNT)
                if encoded:
                    key = base64.urlsafe_b64decode(encoded.encode("ascii"))
                    if len(key) == 32:
                        return key
                candidate = os.urandom(32)
                encoded = base64.urlsafe_b64encode(candidate).decode("ascii")
                keyring.set_password(KEYRING_SERVICE, KEYRING_ACCOUNT, encoded)
                if keyring.get_password(KEYRING_SERVICE, KEYRING_ACCOUNT) == encoded:
                    return candidate
            except (ValueError, RuntimeError, keyring.errors.KeyringError):
                pass
        key = os.urandom(32)
        descriptor = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as output:
            output.write(key)
        _private_mode(key_path, 0o600)
        return key

    def _encrypt(self, data: bytes, name: str) -> bytes:
        nonce = os.urandom(12)
        return MAGIC + nonce + AESGCM(self._key()).encrypt(nonce, data, name.encode())

    def _decrypt(self, data: bytes, name: str) -> bytes:
        if not data.startswith(MAGIC):
            raise ValueError("Invalid encrypted Recall envelope")
        nonce = data[len(MAGIC):len(MAGIC) + 12]
        return AESGCM(self._key()).decrypt(nonce, data[len(MAGIC) + 12:], name.encode())

    def _write_encrypted(self, target: Path, data: bytes) -> None:
        encrypted = self._encrypt(data, target.name)
        descriptor, temporary_name = tempfile.mkstemp(dir=self.vault_dir, prefix=f".{target.name}.")
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(encrypted)
                output.flush()
                os.fsync(output.fileno())
            _private_mode(temporary, 0o600)
            os.replace(temporary, target)
            _private_mode(target, 0o600)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _exclusions(values: list[str] | tuple[str, ...]) -> tuple[str, ...]:
        normalized = {token.strip().casefold()[:256] for token in (*DEFAULT_EXCLUSIONS, *values)}
        return tuple(sorted(token for token in normalized if token))

    def save(
        self,
        session: SessionSnapshot,
        *,
        retention_hours: int = DEFAULT_RETENTION_HOURS,
        excluded_apps: list[str] | tuple[str, ...] = (),
        excluded_websites: list[str] | tuple[str, ...] = (),
        include_file_paths: bool = False,
        preview: bytes | None = None,
        window_previews: dict[int, bytes] | None = None,
        ocr_enabled: bool = False,
        sensitive_filter: bool = True,
        quota_mb: int = 512,
    ) -> Path:
        self._ensure_directory()
        exclusions = self._exclusions(excluded_apps)
        window_previews = window_previews or {}
        has_excluded_window = any(
            _matches_exclusion(window, exclusions) for window in session.windows
        )
        has_protected_window = any(window.capture_protection for window in session.windows)
        # A desktop image may contain pixels from an excluded window. Individual
        # window images can be retained safely because they are mapped before save.
        if has_excluded_window or has_protected_window:
            preview = None
        windows = []
        remaining_window_ocr = MAX_TOTAL_WINDOW_OCR_BYTES
        remaining_window_boxes = MAX_TOTAL_WINDOW_OCR_BOXES
        for source_index, window in enumerate(session.windows):
            if _matches_exclusion(window, exclusions):
                continue
            if window.capture_protection:
                continue
            item = {
                "app_id": window.app_id,
                "app_name": window.app_name,
                "title": window.title,
                "geometry": list(window.geometry),
                "workspace": window.workspace,
                "monitor": window.monitor,
                "accessible_text": window.accessible_text,
                "targets": list(window.deep_targets),
            }
            if include_file_paths:
                item["open_files"] = list(window.open_files)
            image = window_previews.get(source_index)
            if image is not None:
                if not isinstance(image, bytes) or len(image) > MAX_PREVIEW_BYTES:
                    raise ValueError("Recall window preview exceeds the safety limit")
                item["_preview"] = image
                if ocr_enabled and remaining_window_ocr:
                    text, boxes = self._ocr(image)
                    ocr_diagnostics = {
                        "state": "completed", "engine": "tesseract",
                        "word_count": len(text.split()), "recognized_characters": len(text),
                    }
                    text = text.encode("utf-8")[
                        :min(MAX_WINDOW_OCR_BYTES, remaining_window_ocr)
                    ].decode("utf-8", "ignore")
                    if text:
                        item["ocr_text"] = text
                        item["ocr_boxes"] = boxes[:remaining_window_boxes]
                        remaining_window_boxes -= len(item["ocr_boxes"])
                        remaining_window_ocr -= len(text.encode("utf-8"))
                    item["ocr_diagnostics"] = ocr_diagnostics
            item["_source_index"] = source_index
            windows.append(item)
        if not windows:
            raise RuntimeError("No non-excluded windows were available for Privacy Recall")
        stamp = datetime.now(timezone.utc).strftime("recall-%Y%m%d-%H%M%S-%f")
        if preview and ocr_enabled:
            ocr_text, ocr_boxes = self._ocr(preview)
            display_ocr_diagnostics = {
                "state": "completed", "engine": "tesseract",
                "word_count": len(ocr_text.split()), "recognized_characters": len(ocr_text),
            }
        else:
            ocr_text, ocr_boxes, display_ocr_diagnostics = "", [], {
                "state": "disabled" if not ocr_enabled else "no-display-preview",
                "engine": "tesseract",
            }
        search_text = "\n".join(
            str(value)
            for item in windows
            for value in (
                item.get("app_name"),
                item.get("title"),
                item.get("accessible_text"),
                *item.get("open_files", []),
                item.get("ocr_text"),
            )
            if value
        ) + "\n" + ocr_text
        files = list(dict.fromkeys(
            str(value)
            for item in windows
            for value in item.get("open_files", [])
            if value
        ))
        urls = list(dict.fromkeys(URL_RE.findall("\n".join(str(item.get("title") or "") for item in windows))))
        excluded_domains = tuple(
            value.strip().casefold().lstrip(".")
            for value in excluded_websites
            if value.strip()
        )
        if any(
            domain == excluded or domain.endswith(f".{excluded}")
            for domain in map(_domain, urls)
            if domain
            for excluded in excluded_domains
        ):
            raise RuntimeError("Recall capture discarded because an excluded website is visible")
        if sensitive_filter and _contains_sensitive(search_text):
            raise RuntimeError("Recall capture discarded because likely sensitive information was detected")
        image_name = ""
        if preview:
            if len(preview) > MAX_PREVIEW_BYTES:
                raise ValueError("Recall preview exceeds the safety limit")
            image_name = f"{stamp}.ssimg"
        image_writes: list[tuple[str, bytes]] = []
        if image_name and preview:
            image_writes.append((image_name, preview))
        for window_index, item in enumerate(windows[:MAX_WINDOW_PREVIEWS]):
            window_preview = item.pop("_preview", None)
            item.pop("_source_index")
            if window_preview:
                window_image_name = f"{stamp}-window-{window_index}.ssimg"
                item["image"] = window_image_name
                image_writes.append((window_image_name, window_preview))
        for item in windows[MAX_WINDOW_PREVIEWS:]:
            item.pop("_preview", None)
            item.pop("_source_index", None)
        payload = {
            "recall_schema": RECALL_SCHEMA,
            "captured_at": session.captured_at,
            "modified": time.time(),
            "platform": session.platform,
            "desktop": session.desktop,
            "include_file_paths": bool(include_file_paths),
            "windows": windows,
            "ocr_text": ocr_text,
            "ocr_boxes": ocr_boxes,
            "ocr_diagnostics": display_ocr_diagnostics,
            "urls": urls,
            "targets": [
                *[str(target) for item in windows for target in item.get("targets", [])],
                *[Path(value).as_uri() for value in (files if include_file_paths else []) if Path(value).is_absolute() and Path(value).is_file()],
                *urls,
            ][:128],
            "image": image_name,
            "scene_id": self._visual_hash(preview or next((data for _name, data in image_writes), b"")),
            "annotations": {"bookmarked": False, "collection": "", "note": ""},
            "capture_diagnostics": {
                **session.capture_diagnostics,
                "expected_windows": len(session.windows),
                "eligible_windows": len(windows),
                "captured_window_images": sum(
                    1 for item in windows if item.get("image")
                ),
                "missing_window_images": max(
                    0, len(windows) - sum(1 for item in windows if item.get("image"))
                ),
                "excluded_windows": sum(
                    1 for window in session.windows if _matches_exclusion(window, exclusions)
                ),
                "protected_windows": sum(
                    1 for window in session.windows if window.capture_protection
                ),
            },
            "privacy": {
                "sensitive_filter": bool(sensitive_filter),
                "excluded_application_visible": bool(has_excluded_window),
                "protected_context_visible": bool(has_protected_window),
                "shared_display_withheld": bool(
                    (has_excluded_window or has_protected_window) and not preview
                ),
            },
        }
        contents = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        if len(contents) > MAX_RECALL_BYTES:
            raise ValueError("Privacy Recall entry is too large to store safely")
        path = self.vault_dir / f"{stamp}.ssrec"
        written_images: list[Path] = []
        try:
            for name, data in image_writes:
                image_path = self.vault_dir / name
                self._write_encrypted(image_path, data)
                written_images.append(image_path)
            self._write_encrypted(path, contents)
        except Exception:
            for image_path in written_images:
                image_path.unlink(missing_ok=True)
            raise
        self.prune(retention_hours, quota_mb)
        return path

    @staticmethod
    def _ocr(preview: bytes) -> tuple[str, list[dict]]:
        text, boxes, _diagnostics = RecallStore._ocr_detailed(preview)
        return text, boxes

    @staticmethod
    def _ocr_detailed(preview: bytes) -> tuple[str, list[dict], dict[str, object]]:
        started = time.monotonic()
        diagnostics: dict[str, object] = {
            "state": "failed", "engine": "tesseract", "word_count": 0,
            "mean_confidence": 0, "duration_ms": 0,
        }
        descriptor, name = tempfile.mkstemp(suffix=".jpg")
        path = Path(name)
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(preview)
            working_path = _prepare_ocr_image(path)
            language_args = _tesseract_language_args()
            result = subprocess.run(
                [
                    "tesseract", str(working_path), "stdout", *language_args, "--oem", "1",
                    "--psm", "11", "--dpi", "180", "-c",
                    "preserve_interword_spaces=1", "tsv",
                ],
                check=False,
                capture_output=True,
                timeout=20,
            )
            diagnostics["languages"] = " ".join(language_args)
            diagnostics["return_code"] = result.returncode
            if result.returncode != 0:
                diagnostics["error"] = result.stderr.decode("utf-8", "replace")[:512]
                return "", [], diagnostics
            reader = csv.DictReader(
                io.StringIO(result.stdout[:1024 * 1024].decode("utf-8", "replace")),
                delimiter="\t",
            )
            page_width = page_height = 0
            words = []
            boxes = []
            confidences: list[float] = []
            for row in reader:
                try:
                    level = int(row.get("level") or 0)
                    if level == 1:
                        page_width = max(page_width, int(row.get("width") or 0))
                        page_height = max(page_height, int(row.get("height") or 0))
                        continue
                    text = str(row.get("text") or "").strip()[:128]
                    confidence = float(row.get("conf") or -1)
                    if (
                        level != 5 or not page_width or not page_height or not text
                        or confidence < MIN_OCR_CONFIDENCE
                        or not any(character.isalnum() for character in text)
                        or len(boxes) >= MAX_OCR_BOXES_PER_IMAGE
                    ):
                        continue
                    left = max(0, int(row.get("left") or 0))
                    top = max(0, int(row.get("top") or 0))
                    width = min(max(1, int(row.get("width") or 0)), page_width - left)
                    height = min(max(1, int(row.get("height") or 0)), page_height - top)
                    if left >= page_width or top >= page_height:
                        continue
                except (TypeError, ValueError):
                    continue
                words.append(text)
                confidences.append(confidence)
                boxes.append({
                    "t": text,
                    "x": round(left * 10000 / page_width),
                    "y": round(top * 10000 / page_height),
                    "w": max(1, round(width * 10000 / page_width)),
                    "h": max(1, round(height * 10000 / page_height)),
                    "c": round(confidence),
                })
            diagnostics.update({
                "state": "completed",
                "word_count": len(words),
                "mean_confidence": round(sum(confidences) / len(confidences), 1) if confidences else 0,
                "minimum_confidence": round(min(confidences), 1) if confidences else 0,
                "maximum_confidence": round(max(confidences), 1) if confidences else 0,
            })
            return " ".join(words)[:1024 * 1024], boxes, diagnostics
        except (OSError, subprocess.TimeoutExpired) as error:
            diagnostics["state"] = "timeout" if isinstance(error, subprocess.TimeoutExpired) else "unavailable"
            diagnostics["error"] = str(error)[:512]
            return "", [], diagnostics
        finally:
            diagnostics["duration_ms"] = round((time.monotonic() - started) * 1000)
            if "working_path" in locals() and working_path != path:
                working_path.unlink(missing_ok=True)
            path.unlink(missing_ok=True)

    @staticmethod
    def _visual_hash(preview: bytes) -> str:
        if not preview or Image is None:
            return ""
        try:
            with Image.open(io.BytesIO(preview)) as source:
                gray = source.convert("L").resize((8, 8), Image.Resampling.LANCZOS)
                values = list(gray.getdata())
            mean = sum(values) / len(values)
            bits = "".join("1" if value >= mean else "0" for value in values)
            return f"{int(bits, 2):016x}"
        except (OSError, ValueError):
            return ""

    def _paths(self) -> list[Path]:
        if not self.vault_dir.is_dir() or self.vault_dir.is_symlink():
            return []
        return sorted(
            (path for path in self.vault_dir.glob("*.ssrec") if path.is_file() and not path.is_symlink() and RECORD_RE.fullmatch(path.name)),
            key=lambda path: path.stat().st_mtime_ns,
            reverse=True,
        )

    def _load(self, path: Path) -> dict | None:
        with self._search_lock:
            return self._load_locked(path)

    def _load_locked(self, path: Path) -> dict | None:
        try:
            stat = path.stat()
            if stat.st_size > MAX_RECALL_BYTES + 128:
                return None
            signature = (stat.st_mtime_ns, stat.st_size)
            cached = self._record_cache.get(path.name)
            if cached and cached[0] == signature:
                self._record_cache.move_to_end(path.name)
                return cached[1]
            raw = self._decrypt(path.read_bytes(), path.name)
            payload = json.loads(raw)
            if payload.get("recall_schema") != RECALL_SCHEMA:
                return None
            previous = self._record_cache.pop(path.name, None)
            if previous:
                self._record_cache_bytes -= previous[2]
            self._record_cache[path.name] = (signature, payload, len(raw))
            self._record_cache_bytes += len(raw)
            while self._record_cache_bytes > MAX_RECORD_CACHE_BYTES and len(self._record_cache) > 1:
                _name, (_signature, _payload, size) = self._record_cache.popitem(last=False)
                self._record_cache_bytes -= size
            return payload
        except (OSError, ValueError, json.JSONDecodeError):
            return None

    @staticmethod
    def _path_signature(paths: list[Path]) -> tuple[tuple[str, int, int], ...]:
        signature = []
        for path in paths:
            with contextlib.suppress(OSError):
                stat = path.stat()
                signature.append((path.name, stat.st_mtime_ns, stat.st_size))
        return tuple(signature)

    def _ensure_search_index(
        self, records: list[tuple[Path, dict]],
        signature: tuple[tuple[str, int, int], ...],
    ) -> sqlite3.Connection:
        if self._index_connection is not None and signature == self._index_signature:
            return self._index_connection
        # The RLock serializes use; disabling the owner-thread check lets the
        # cached in-memory index survive successive UI worker threads.
        connection = sqlite3.connect(":memory:", check_same_thread=False)
        connection.execute(
            "CREATE VIRTUAL TABLE recall_windows USING fts5("
            "key UNINDEXED, app, title, files, accessible, ocr)"
        )
        connection.execute(
            "CREATE VIRTUAL TABLE recall_visual USING fts5(name UNINDEXED, ocr)"
        )
        for path, payload in records:
            annotations = dict(payload.get("annotations") or {})
            for index, window in enumerate(payload.get("windows", [])[:512]):
                if not isinstance(window, dict):
                    continue
                connection.execute(
                    "INSERT INTO recall_windows VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        f"{path.name}#{index}",
                        str(window.get("app_name") or window.get("app_id") or ""),
                        str(window.get("title") or ""),
                        "\n".join(str(value) for value in window.get("open_files", [])),
                        "\n".join((
                            str(window.get("accessible_text") or ""),
                            str(annotations.get("collection") or ""),
                            str(annotations.get("note") or ""),
                        )),
                        str(window.get("ocr_text") or ""),
                    ),
                )
            connection.execute(
                "INSERT INTO recall_visual VALUES (?, ?)",
                (path.name, str(payload.get("ocr_text") or "")),
            )
        connection.commit()
        previous = self._index_connection
        self._index_connection = connection
        self._index_signature = signature
        if previous is not None:
            previous.close()
        valid_names = {name for name, _modified, _size in signature}
        for name in list(self._record_cache):
            if name not in valid_names:
                _signature, _payload, size = self._record_cache.pop(name)
                self._record_cache_bytes -= size
        return connection

    def clear_search_cache(self) -> None:
        with self._search_lock:
            if self._index_connection is not None:
                self._index_connection.close()
            self._index_connection = None
            self._index_signature = ()
            self._record_cache.clear()
            self._record_cache_bytes = 0
            self.semantic.clear_cache()

    def prune(self, retention_hours: int, quota_mb: int = 512) -> None:
        hours = max(1, min(24 * 30, int(retention_hours)))
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        quota = max(64, min(16384, int(quota_mb))) * 1024 * 1024
        for index, path in enumerate(self._paths()):
            modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
            if index >= RECALL_MAX_ENTRIES or modified < cutoff or self.storage_bytes() > quota:
                self._delete_path(path)
        referenced = {
            name
            for path in self._paths()
            for payload in [self._load(path)]
            if payload
            for name in self._payload_images(payload)
        }
        for image in self.vault_dir.glob("*.ssimg"):
            if (
                IMAGE_RE.fullmatch(image.name)
                and image.name not in referenced
                and image.is_file()
                and not image.is_symlink()
            ):
                image.unlink(missing_ok=True)

    def _delete_path(self, path: Path) -> None:
        payload = self._load(path)
        if payload:
            for name in self._payload_images(payload):
                (self.vault_dir / name).unlink(missing_ok=True)
        path.unlink(missing_ok=True)

    @staticmethod
    def _payload_images(payload: dict) -> set[str]:
        names = {str(payload.get("image") or "")}
        names.update(
            str(window.get("image") or "")
            for window in payload.get("windows", [])
            if isinstance(window, dict)
        )
        return {name for name in names if IMAGE_RE.fullmatch(name)}

    def search(
        self,
        query: str = "",
        limit: int = 100,
        excluded_apps: list[str] | tuple[str, ...] = (),
        *,
        app: str = "",
        semantic: bool = False,
    ) -> list[dict[str, object]]:
        with self._search_lock:
            return self._search_locked(
                query, limit, excluded_apps, app=app, semantic=semantic,
            )

    def _search_locked(
        self,
        query: str = "",
        limit: int = 100,
        excluded_apps: list[str] | tuple[str, ...] = (),
        *,
        app: str = "",
        semantic: bool = False,
    ) -> list[dict[str, object]]:
        needle = query.strip().casefold()[:256]
        exclusions = self._exclusions(excluded_apps)
        paths = self._paths()
        signature = self._path_signature(paths)
        records = [(path, self._load(path)) for path in paths]
        records = [(path, payload) for path, payload in records if payload]
        connection = self._ensure_search_index(records, signature)
        try:
            loaded = []
            for path, payload in records:
                visible_windows = []
                excluded_visible = False
                for index, window in enumerate(payload.get("windows", [])[:512]):
                    if not isinstance(window, dict):
                        continue
                    identity = "\n".join((
                        str(window.get("app_id", "")),
                        str(window.get("app_name", "")),
                    )).casefold()
                    if any(token in identity for token in exclusions):
                        excluded_visible = True
                        continue
                    visible_windows.append((index, window))
                if not visible_windows:
                    continue
                preview_allowed = not excluded_visible
                loaded.append((path, payload, visible_windows, preview_allowed))

            window_candidates: dict[str, float] = {}
            visual_candidates: dict[str, float] = {}
            if needle:
                terms = re.findall(r"[\w.-]+", needle)[:16]
                expression = " OR ".join(
                    f'"{term.replace(chr(34), "")}"{("*" if len(terms) == 1 else "")}'
                    for term in terms
                )
                if expression:
                    with contextlib.suppress(sqlite3.OperationalError):
                        for key, rank in connection.execute(
                            "SELECT key, bm25(recall_windows,0,6,5,3,5,4) "
                            "FROM recall_windows WHERE recall_windows MATCH ? ORDER BY 2",
                            (expression,),
                        ):
                            window_candidates[key] = -float(rank)
                    with contextlib.suppress(sqlite3.OperationalError):
                        for name, rank in connection.execute(
                            "SELECT name, bm25(recall_visual,0,2) "
                            "FROM recall_visual WHERE recall_visual MATCH ? ORDER BY 2",
                            (expression,),
                        ):
                            visual_candidates[name] = -float(rank)
            if needle and semantic:
                documents: dict[str, str] = {}
                for path, _payload, windows, _preview_allowed in loaded:
                    for index, window in windows:
                        documents[f"{path.name}#{index}"] = " ".join([
                            str(window.get("app_name") or window.get("app_id") or ""),
                            str(window.get("title") or ""),
                            *(str(value) for value in window.get("open_files", [])),
                            str(window.get("accessible_text") or ""),
                            str(window.get("ocr_text") or ""),
                        ])
                for key, score in self.semantic.rank(needle, documents).items():
                    window_candidates[key] = max(window_candidates.get(key, 0.0), score * 4.0)

            results = []
            for path, payload, windows, preview_allowed in loaded:
                common = {
                    "name": path.name,
                    "captured_at": str(payload.get("captured_at") or "")[:128],
                    "modified": float(payload.get("modified") or path.stat().st_mtime),
                    "has_preview": bool(payload.get("image")) and preview_allowed,
                    "capture_diagnostics": dict(payload.get("capture_diagnostics") or {}),
                    "privacy": dict(payload.get("privacy") or {}),
                    "scene_id": str(payload.get("scene_id") or ""),
                    "annotations": dict(payload.get("annotations") or {}),
                    "ocr_diagnostics": dict(payload.get("ocr_diagnostics") or {}),
                }
                if not needle and not app:
                    apps = list(dict.fromkeys(
                        str(window.get("app_name") or window.get("app_id") or "")
                        for _index, window in windows
                        if window.get("app_name") or window.get("app_id")
                    ))
                    titles = list(dict.fromkeys(
                        str(window.get("title") or "")
                        for _index, window in windows if window.get("title")
                    ))
                    files = list(dict.fromkeys(
                        str(value) for _index, window in windows
                        for value in window.get("open_files", [])
                    ))
                    urls = list(dict.fromkeys(URL_RE.findall("\n".join(titles))))
                    results.append({
                        **common,
                        "apps": apps,
                        "titles": titles,
                        "files": files,
                        "targets": list(dict.fromkeys([
                            *(str(target) for _index, window in windows
                              for target in window.get("targets", [])),
                            *self._targets(files, urls),
                        ]))[:32],
                        "urls": urls,
                        "rank": 0.0,
                        "match_type": "Timeline",
                        "result_kind": "timeline",
                        "ocr_excerpt": "",
                    })
                    continue

                for index, window in windows:
                    app_token = app.casefold()
                    identities = {
                        str(window.get("app_id", "")).casefold(),
                        str(window.get("app_name", "")).casefold(),
                    }
                    if app and app_token not in identities:
                        continue
                    key = f"{path.name}#{index}"
                    if needle and key not in window_candidates:
                        continue
                    files = [str(value) for value in window.get("open_files", [])]
                    title = str(window.get("title") or "")
                    urls = list(dict.fromkeys(URL_RE.findall(title)))
                    results.append({
                        **common,
                        "has_preview": bool(window.get("image")) or common["has_preview"],
                        "apps": [str(window.get("app_name") or window.get("app_id") or "")],
                        "titles": [title] if title else [],
                        "files": files,
                        "targets": list(dict.fromkeys([
                            *(str(target) for target in window.get("targets", [])),
                            *self._targets(files, urls),
                        ]))[:32],
                        "urls": urls,
                        "rank": round(window_candidates.get(key, 0.0), 4),
                        "match_type": self._window_match_type(
                            window, needle,
                            semantic=semantic and key in window_candidates,
                        ),
                        "result_kind": "window",
                        "windows": [visible for _visible_index, visible in windows],
                        "matched_window": window,
                        "window_index": index,
                        "highlight_boxes": _matching_ocr_boxes(
                            window.get("ocr_boxes"), needle
                        ),
                        "highlight_image": str(window.get("image") or ""),
                        "ocr_excerpt": " ".join(
                            str(window.get("ocr_text") or "").split()
                        )[:320],
                    })

                if needle and not app and preview_allowed and path.name in visual_candidates:
                    ocr_text = str(payload.get("ocr_text") or "")
                    apps = list(dict.fromkeys(
                        str(window.get("app_name") or window.get("app_id") or "")
                        for _index, window in windows
                        if window.get("app_name") or window.get("app_id")
                    ))
                    results.append({
                        **common,
                        "apps": apps,
                        "titles": [],
                        "files": [],
                        "targets": [],
                        "urls": [],
                        "rank": round(visual_candidates[path.name], 4),
                        "match_type": "Visual text",
                        "result_kind": "visual",
                        "highlight_image": "",
                        "highlight_boxes": _matching_ocr_boxes(
                            payload.get("ocr_boxes"), needle
                        ),
                        "ocr_excerpt": " ".join(ocr_text.split())[:320],
                    })
            results.sort(
                key=lambda value: (-float(value["rank"]), -float(value["modified"]))
            )
            return results[:max(1, min(250, int(limit)))]
        finally:
            pass

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
    def _window_match_type(window: dict, needle: str, *, semantic: bool = False) -> str:
        if not needle:
            return "Window"
        if needle in str(window.get("title") or "").casefold():
            return "Window text"
        if any(needle in str(value).casefold() for value in window.get("open_files", [])):
            return "Window file"
        if needle in str(window.get("accessible_text") or "").casefold():
            return "Application content"
        if needle in "\n".join((
            str(window.get("app_name") or ""), str(window.get("app_id") or "")
        )).casefold():
            return "Application"
        if needle in str(window.get("ocr_text") or "").casefold():
            return "Window image text"
        return "Semantic match" if semantic else "Related window"

    @staticmethod
    def group_scenes(results: list[dict[str, object]]) -> list[dict[str, object]]:
        """Collapse adjacent near-identical timeline frames without losing evidence."""
        grouped: list[dict[str, object]] = []
        for result in results:
            visual = str(result.get("scene_id") or "")
            previous = grouped[-1] if grouped else None
            previous_visual = str(previous.get("scene_id") or "") if previous else ""
            distance = 65
            if visual and previous_visual:
                with contextlib.suppress(ValueError):
                    distance = (int(visual, 16) ^ int(previous_visual, 16)).bit_count()
            if previous and visual and distance <= 5:
                previous["scene_count"] = int(previous.get("scene_count") or 1) + 1
                previous["scene_started_at"] = result.get("captured_at")
                continue
            item = dict(result)
            item["scene_count"] = 1
            item["scene_started_at"] = result.get("captured_at")
            item["scene_finished_at"] = result.get("captured_at")
            grouped.append(item)
        return grouped

    def preview_bytes(self, record: str, *, image_name: str = "") -> bytes | None:
        if not RECORD_RE.fullmatch(record):
            return None
        payload = self._load(self.vault_dir / record)
        if not payload:
            return None
        allowed = self._payload_images(payload)
        name = image_name or str(payload.get("image") or "")
        if name not in allowed:
            return None
        with contextlib.suppress(OSError, ValueError):
            return self._decrypt((self.vault_dir / name).read_bytes(), name)
        return None

    def annotate(
        self,
        record: str,
        *,
        bookmarked: bool | None = None,
        collection: str | None = None,
        note: str | None = None,
    ) -> dict[str, object]:
        if not RECORD_RE.fullmatch(record):
            raise ValueError("Invalid Recall record")
        path = self.vault_dir / record
        payload = self._load(path)
        if not payload:
            raise ValueError("Recall record is unavailable")
        annotations = dict(payload.get("annotations") or {})
        if bookmarked is not None:
            annotations["bookmarked"] = bool(bookmarked)
        if collection is not None:
            annotations["collection"] = str(collection).strip()[:128]
        if note is not None:
            annotations["note"] = str(note).strip()[:4096]
        payload["annotations"] = annotations
        payload["modified"] = time.time()
        self._write_encrypted(
            path, json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        )
        return annotations

    def ocr_diagnostics(self, record: str) -> dict[str, object]:
        if not RECORD_RE.fullmatch(record):
            raise ValueError("Invalid Recall record")
        payload = self._load(self.vault_dir / record)
        if not payload:
            raise ValueError("Recall record is unavailable")
        windows = [
            {
                "application": str(window.get("app_name") or window.get("app_id") or ""),
                "title": str(window.get("title") or ""),
                **dict(window.get("ocr_diagnostics") or {"state": "not-indexed"}),
            }
            for window in payload.get("windows", [])
            if isinstance(window, dict)
        ]
        return {
            "display": dict(payload.get("ocr_diagnostics") or {"state": "not-indexed"}),
            "windows": windows,
            "semantic": self.semantic.diagnostics(),
        }

    def reindex(self, record: str) -> dict[str, object]:
        """Re-run OCR only for a selected encrypted local record."""
        if not RECORD_RE.fullmatch(record):
            raise ValueError("Invalid Recall record")
        path = self.vault_dir / record
        payload = self._load(path)
        if not payload:
            raise ValueError("Recall record is unavailable")
        indexed = 0
        display_name = str(payload.get("image") or "")
        if display_name:
            preview = self.preview_bytes(record, image_name=display_name)
            if preview:
                text, boxes, diagnostics = self._ocr_detailed(preview)
                payload.update({"ocr_text": text, "ocr_boxes": boxes, "ocr_diagnostics": diagnostics})
                indexed += 1
        for window in payload.get("windows", [])[:MAX_WINDOW_PREVIEWS]:
            if not isinstance(window, dict):
                continue
            image_name = str(window.get("image") or "")
            preview = self.preview_bytes(record, image_name=image_name) if image_name else None
            if not preview:
                window["ocr_diagnostics"] = {"state": "no-preview", "engine": "tesseract"}
                continue
            text, boxes, diagnostics = self._ocr_detailed(preview)
            window.update({"ocr_text": text, "ocr_boxes": boxes, "ocr_diagnostics": diagnostics})
            indexed += 1
        payload["modified"] = time.time()
        contents = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        if len(contents) > MAX_RECALL_BYTES:
            raise ValueError("Reindexed Recall record exceeds the safety limit")
        self._write_encrypted(path, contents)
        return {"record": record, "images_indexed": indexed, **self.ocr_diagnostics(record)}

    def ask(self, question: str, *, limit: int = 8) -> dict[str, object]:
        """Answer locally with extractive text and explicit snapshot citations."""
        question = question.strip()[:256]
        if not question:
            raise ValueError("A question is required")
        matches = self.search(question, limit=limit, semantic=True)
        citations = []
        excerpts = []
        for result in matches[:max(1, min(12, limit))]:
            excerpt = str(result.get("ocr_excerpt") or "")
            if not excerpt:
                excerpt = " — ".join(str(value) for value in result.get("titles", [])[:2])
            citations.append({
                "record": result.get("name"),
                "captured_at": result.get("captured_at"),
                "application": next(iter(result.get("apps", [])), ""),
                "title": next(iter(result.get("titles", [])), ""),
                "excerpt": excerpt[:320],
                "image": result.get("highlight_image", ""),
            })
            if excerpt:
                excerpts.append(excerpt[:240])
        answer = (
            "No matching local history was found."
            if not citations else
            "The closest evidence in your local history is: " + " ".join(excerpts[:3])
        )
        return {"question": question, "answer": answer, "citations": citations}

    def export_records(self):
        for path in self._paths():
            payload = self._load(path)
            if not payload:
                continue
            images: dict[str, bytes] = {}
            for image_name in self._payload_images(payload):
                preview = self.preview_bytes(path.name, image_name=image_name)
                if preview is not None:
                    images[image_name] = preview
            yield path.stem, payload, images

    def import_record(self, metadata: dict, images: dict[str, bytes]) -> Path:
        self._ensure_directory()
        if metadata.get("recall_schema") != RECALL_SCHEMA or not isinstance(metadata.get("windows"), list):
            raise ValueError("Recall archive record is incompatible")
        payload = json.loads(json.dumps(metadata))
        stamp = datetime.now(timezone.utc).strftime("recall-%Y%m%d-%H%M%S-%f")
        mapping: dict[str, str] = {}
        display = str(payload.get("image") or "")
        if display:
            mapping[display] = f"{stamp}.ssimg"
        for index, window in enumerate(payload.get("windows", [])[:MAX_WINDOW_PREVIEWS]):
            if isinstance(window, dict) and window.get("image"):
                mapping[str(window["image"])] = f"{stamp}-window-{index}.ssimg"
        if any(name not in images or not isinstance(images[name], bytes) or len(images[name]) > MAX_PREVIEW_BYTES for name in mapping):
            raise ValueError("Recall archive is missing a bounded preview")
        payload["image"] = mapping.get(display, "")
        for window in payload.get("windows", []):
            if isinstance(window, dict):
                window["image"] = mapping.get(str(window.get("image") or ""), "")
        payload["modified"] = time.time()
        contents = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        if len(contents) > MAX_RECALL_BYTES:
            raise ValueError("Imported Recall record exceeds the safety limit")
        record_path = self.vault_dir / f"{stamp}.ssrec"
        written: list[Path] = []
        try:
            for old_name, new_name in mapping.items():
                target = self.vault_dir / new_name
                self._write_encrypted(target, images[old_name])
                written.append(target)
            self._write_encrypted(record_path, contents)
        except Exception:
            for target in written:
                target.unlink(missing_ok=True)
            raise
        return record_path

    def diagnostics(self) -> dict[str, object]:
        return {
            "entries": self.entry_count(),
            "storage_bytes": self.storage_bytes(),
            "ocr_languages": " ".join(_tesseract_language_args()),
            "semantic": self.semantic.diagnostics(),
        }

    def delete(self, *, record: str = "", app: str = "", website: str = "") -> int:
        removed = 0
        for path in self._paths():
            payload = self._load(path)
            apps = "\n".join(str(item.get("app_name") or item.get("app_id") or "") for item in (payload or {}).get("windows", []))
            if record and path.name != record:
                continue
            if app and app.casefold() not in apps.casefold():
                continue
            if website and website.casefold() not in "\n".join((payload or {}).get("urls", [])).casefold():
                continue
            self._delete_path(path)
            removed += 1
        if removed:
            self.clear_search_cache()
        return removed

    def clear(self) -> int:
        return self.delete()

    def entry_count(self) -> int:
        return len(self._paths())

    def storage_bytes(self) -> int:
        if not self.vault_dir.is_dir():
            return 0
        with contextlib.suppress(OSError):
            modified = self.vault_dir.stat().st_mtime_ns
            if self._storage_cache and self._storage_cache[0] == modified:
                return self._storage_cache[1]
            size = sum(path.stat().st_size for path in self.vault_dir.iterdir() if path.is_file() and not path.is_symlink())
            self._storage_cache = (modified, size)
            return size
        return 0
