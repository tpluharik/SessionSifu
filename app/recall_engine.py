"""Encrypted, local-only Recall vault used by the GNOME manager.

GNOME Shell only captures bounded metadata and display images.  This module
finalizes those temporary files outside the compositor: it compresses/searches
text, applies privacy policy, encrypts persistent data and builds an in-memory
FTS index for each search process.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import tempfile
import time
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


RECORD_RE = re.compile(r"^recall-\d{8}-\d{6}-\d{3}\.json$")
VAULT_RE = re.compile(r"^recall-\d{8}-\d{6}-\d{3}\.ssrec$")
IMAGE_RE = re.compile(r"^recall-\d{8}-\d{6}-\d{3}-display-(\d+)\.jpg$")
VAULT_IMAGE_RE = re.compile(r"^recall-\d{8}-\d{6}-\d{3}-display-\d+\.ssimg$")
URL_RE = re.compile(r"https?://[^\s<>{}\[\]\"']+", re.IGNORECASE)
CARD_RE = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
SENSITIVE_RE = re.compile(
    r"\b(?:password|passcode|one[- ]time code|security code|cvv|cvc|secret key|"
    r"recovery phrase|private key)\b",
    re.IGNORECASE,
)
MAGIC = b"SSRF1\0"
MAX_RECORD_BYTES = 2 * 1024 * 1024
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_OCR_BYTES = 1024 * 1024
MAX_ENTRIES = 500
SERVICE = "org.gnome.SessionSifu.Recall"
ACCOUNT = "local-vault-v1"


def _private(path: Path, mode: int) -> None:
    with contextlib.suppress(OSError):
        path.chmod(mode)


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

    def __init__(self, root: Path, *, test_key: bytes | None = None) -> None:
        self.root = root.resolve()
        self.vault = self.root / "vault"
        self.status_path = self.root / "capture-status.json"
        self._test_key = test_key
        self._key_source = "test" if test_key else "unavailable"

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

    def _ocr(self, image: Path) -> str:
        try:
            result = subprocess.run(
                ["tesseract", str(image), "stdout", "--psm", "6"],
                check=False,
                capture_output=True,
                timeout=20,
            )
        except (OSError, subprocess.TimeoutExpired):
            return ""
        if result.returncode != 0:
            return ""
        return result.stdout[:MAX_OCR_BYTES].decode("utf-8", "replace").strip()

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
        image_paths = sorted(self.root.glob(f"{stem}-display-*.jpg"))[:8]
        valid_images = []
        ocr_parts = []
        for image in image_paths:
            if image.is_symlink() or not IMAGE_RE.fullmatch(image.name):
                continue
            if not 0 < image.stat().st_size <= MAX_IMAGE_BYTES:
                continue
            valid_images.append(image)
            if policy.ocr:
                text = self._ocr(image)
                if text:
                    ocr_parts.append(text)

        windows = payload.get("windows")
        if not isinstance(windows, list):
            windows = payload.get("x_session_config_objects")
        if not isinstance(windows, list):
            windows = []
        apps, titles, files, targets, urls = [], [], [], [], []
        for window in windows[:512]:
            if not isinstance(window, dict):
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
        targets.extend(
            Path(value).as_uri()
            for value in files
            if Path(value).is_absolute() and Path(value).is_file()
        )
        targets.extend(urls)
        searchable = "\n".join([*apps, *titles, *files, *ocr_parts])
        excluded_domains = tuple(value.strip().casefold().lstrip(".") for value in policy.excluded_websites if value.strip())
        if any(any(domain == excluded or domain.endswith(f".{excluded}") for excluded in excluded_domains) for domain in map(_domain, urls) if domain):
            self._discard_legacy(capture, image_paths)
            self._write_status(state="skipped", reason="excluded website", duration_ms=round((time.monotonic() - started) * 1000))
            return {"saved": False, "reason": "excluded website"}
        if policy.sensitive_filter and contains_sensitive_text(searchable):
            self._discard_legacy(capture, image_paths)
            self._write_status(state="skipped", reason="sensitive information detected", duration_ms=round((time.monotonic() - started) * 1000))
            return {"saved": False, "reason": "sensitive information detected"}

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
        for image in valid_images:
            raw = image.read_bytes()
            target = self.vault / f"{image.stem}.ssimg"
            self._atomic_encrypted(target, raw)
            image_names.append(target.name)
            image_hashes.append(hashlib.sha256(raw).hexdigest())
        normalized_windows = []
        for window in windows[:512]:
            if not isinstance(window, dict):
                continue
            position = window.get("window_position") or {}
            normalized_windows.append({
                "app": str(window.get("app_name") or window.get("app_id") or window.get("desktop_file_id") or "")[:512],
                "title": str(window.get("title") or window.get("window_title") or "")[:4096],
                "files": [str(value)[:4096] for value in list(window.get("open_files") or [])[:32]],
                "monitor": int(window.get("monitor_number", window.get("monitor", 0)) or 0),
                "x": int(position.get("x_offset", (window.get("geometry") or [0, 0, 0, 0])[0]) or 0),
                "y": int(position.get("y_offset", (window.get("geometry") or [0, 0, 0, 0])[1]) or 0),
                "width": int(position.get("width", (window.get("geometry") or [0, 0, 0, 0])[2]) or 0),
                "height": int(position.get("height", (window.get("geometry") or [0, 0, 0, 0])[3]) or 0),
            })
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
            "ocr_text": "\n".join(ocr_parts)[:MAX_OCR_BYTES],
            "windows": normalized_windows,
            "images": image_names,
            "image_hashes": image_hashes,
        }
        record_target = self.vault / f"{stem}.ssrec"
        self._atomic_encrypted(record_target, json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        self._discard_legacy(capture, image_paths)
        self.prune(policy.quota_mb, policy.retention_hours)
        duration = round((time.monotonic() - started) * 1000)
        self._write_status(
            state="saved", duration_ms=duration, screenshots=len(image_names),
            ocr_characters=len(record["ocr_text"]), record=record_target.name,
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
        connection = sqlite3.connect(":memory:")
        try:
            connection.execute("CREATE VIRTUAL TABLE recall USING fts5(name UNINDEXED, apps, titles, files, ocr)")
            for path, value in records:
                identity = "\n".join(value.get("apps", [])).casefold()
                if any(token.strip().casefold() in identity for token in excluded_apps if token.strip()):
                    continue
                connection.execute(
                    "INSERT INTO recall VALUES (?, ?, ?, ?, ?)",
                    (path.name, "\n".join(value.get("apps", [])), "\n".join(value.get("titles", [])), "\n".join(value.get("files", [])), value.get("ocr_text", "")),
                )
            candidates: dict[str, float] = {}
            needle = query.strip()[:256]
            if needle:
                tokens = re.findall(r"[\w.-]+", needle.casefold())[:16]
                expression = " OR ".join(f'"{token.replace(chr(34), "")}"' for token in tokens if token)
                if expression:
                    with contextlib.suppress(sqlite3.OperationalError):
                        for name, rank in connection.execute("SELECT name, bm25(recall, 0, 6, 4, 3, 2) FROM recall WHERE recall MATCH ? ORDER BY 2 LIMIT 250", (expression,)):
                            candidates[name] = -float(rank)
            else:
                candidates = {path.name: 0.0 for path, _value in records}
            if needle and semantic:
                query_terms = set(re.findall(r"[\w]+", needle.casefold()))
                for path, value in records:
                    text_terms = set(re.findall(r"[\w]+", " ".join([*value.get("apps", []), *value.get("titles", []), str(value.get("ocr_text", ""))]).casefold()))
                    related = len(query_terms & text_terms) / max(1, len(query_terms | text_terms))
                    if related >= 0.08:
                        candidates[path.name] = max(candidates.get(path.name, 0.0), related)
            output = []
            for path, value in records:
                if path.name not in candidates:
                    continue
                identity = "\n".join(value.get("apps", [])).casefold()
                if any(token.strip().casefold() in identity for token in excluded_apps if token.strip()):
                    continue
                if app and app.casefold() not in "\n".join(value.get("apps", [])).casefold():
                    continue
                captured = str(value.get("captured_at") or "")
                if day and not captured.startswith(day):
                    continue
                summary = {key: value.get(key) for key in ("captured_at", "modified", "apps", "titles", "files", "urls", "targets", "windows")}
                summary.update({"name": path.name, "rank": round(candidates[path.name], 4), "match_type": self._match_type(value, needle), "ocr_excerpt": self._excerpt(str(value.get("ocr_text", "")), needle), "image_count": len(value.get("images", []))})
                output.append(summary)
            output.sort(key=lambda item: (-float(item["rank"]), -float(item.get("modified") or 0)))
            return output[:max(1, min(250, int(limit)))]
        finally:
            connection.close()

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
        if not re.fullmatch(r"recall-\d{8}-\d{6}-\d{3}-display-\d+\.ssimg", image_name):
            return None
        with contextlib.suppress(OSError, ValueError):
            return self._read_encrypted(self.vault / image_name, MAX_IMAGE_BYTES + 128)
        return None

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
