"""Encrypted, bounded and searchable cross-platform Privacy Recall vault."""

from __future__ import annotations

import base64
import contextlib
import json
import os
import re
import sqlite3
import subprocess
import tempfile
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

try:
    import keyring
except ImportError:  # Linux system packages may intentionally omit it.
    keyring = None

from .model import SessionSnapshot, WindowSnapshot

RECALL_SCHEMA = 3
RECALL_MAX_ENTRIES = 500
MAX_RECALL_BYTES = 3 * 1024 * 1024
MAX_PREVIEW_BYTES = 8 * 1024 * 1024
DEFAULT_RETENTION_HOURS = 24
DEFAULT_EXCLUSIONS = ("sessionsifu",)
MAGIC = b"SSRF1\0"
KEYRING_SERVICE = "org.sessionsifu.RecallVault"
KEYRING_ACCOUNT = "default"
RECORD_RE = re.compile(r"^recall-\d{8}-\d{6}-\d{6}\.ssrec$")
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


def _matches_exclusion(window: WindowSnapshot, exclusions: tuple[str, ...]) -> bool:
    identity = "\n".join((window.app_id, window.app_name, Path(window.executable).name)).casefold()
    return any(token and token in identity for token in exclusions)


class RecallStore:
    """AES-GCM activity records with ephemeral FTS5 indexing."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.recall_dir = root / "recall"
        self.vault_dir = self.recall_dir / "vault"

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
        ocr_enabled: bool = False,
        sensitive_filter: bool = True,
        quota_mb: int = 512,
    ) -> Path:
        self._ensure_directory()
        exclusions = self._exclusions(excluded_apps)
        windows = []
        for window in session.windows:
            if _matches_exclusion(window, exclusions):
                continue
            item = {
                "app_id": window.app_id,
                "app_name": window.app_name,
                "title": window.title,
                "geometry": list(window.geometry),
                "workspace": window.workspace,
                "monitor": window.monitor,
            }
            if include_file_paths:
                item["open_files"] = list(window.open_files)
            windows.append(item)
        if not windows:
            raise RuntimeError("No non-excluded windows were available for Privacy Recall")
        stamp = datetime.now(timezone.utc).strftime("recall-%Y%m%d-%H%M%S-%f")
        ocr_text = self._ocr(preview) if preview and ocr_enabled else ""
        search_text = "\n".join(
            str(value)
            for item in windows
            for value in (item.get("app_name"), item.get("title"), *item.get("open_files", []))
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
            self._write_encrypted(self.vault_dir / image_name, preview)
        payload = {
            "recall_schema": RECALL_SCHEMA,
            "captured_at": session.captured_at,
            "modified": time.time(),
            "platform": session.platform,
            "desktop": session.desktop,
            "include_file_paths": bool(include_file_paths),
            "windows": windows,
            "ocr_text": ocr_text,
            "urls": urls,
            "targets": [
                *[Path(value).as_uri() for value in (files if include_file_paths else []) if Path(value).is_absolute() and Path(value).is_file()],
                *urls,
            ][:128],
            "image": image_name,
        }
        contents = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        if len(contents) > MAX_RECALL_BYTES:
            raise ValueError("Privacy Recall entry is too large to store safely")
        path = self.vault_dir / f"{stamp}.ssrec"
        self._write_encrypted(path, contents)
        self.prune(retention_hours, quota_mb)
        return path

    @staticmethod
    def _ocr(preview: bytes) -> str:
        descriptor, name = tempfile.mkstemp(suffix=".jpg")
        path = Path(name)
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(preview)
            result = subprocess.run(
                ["tesseract", str(path), "stdout", "--psm", "6"],
                check=False,
                capture_output=True,
                timeout=20,
            )
            return result.stdout[:1024 * 1024].decode("utf-8", "replace").strip() if result.returncode == 0 else ""
        except (OSError, subprocess.TimeoutExpired):
            return ""
        finally:
            path.unlink(missing_ok=True)

    def _paths(self) -> list[Path]:
        if not self.vault_dir.is_dir() or self.vault_dir.is_symlink():
            return []
        return sorted(
            (path for path in self.vault_dir.glob("*.ssrec") if path.is_file() and not path.is_symlink() and RECORD_RE.fullmatch(path.name)),
            key=lambda path: path.stat().st_mtime_ns,
            reverse=True,
        )

    def _load(self, path: Path) -> dict | None:
        try:
            if path.stat().st_size > MAX_RECALL_BYTES + 128:
                return None
            payload = json.loads(self._decrypt(path.read_bytes(), path.name))
            return payload if payload.get("recall_schema") == RECALL_SCHEMA else None
        except (OSError, ValueError, json.JSONDecodeError):
            return None

    def prune(self, retention_hours: int, quota_mb: int = 512) -> None:
        hours = max(1, min(24 * 30, int(retention_hours)))
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        quota = max(64, min(16384, int(quota_mb))) * 1024 * 1024
        for index, path in enumerate(self._paths()):
            modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
            if index >= RECALL_MAX_ENTRIES or modified < cutoff or self.storage_bytes() > quota:
                self._delete_path(path)
        referenced = {
            str(payload.get("image"))
            for path in self._paths()
            for payload in [self._load(path)]
            if payload and payload.get("image")
        }
        for image in self.vault_dir.glob("*.ssimg"):
            if (
                re.fullmatch(r"recall-\d{8}-\d{6}-\d{6}\.ssimg", image.name)
                and image.name not in referenced
                and image.is_file()
                and not image.is_symlink()
            ):
                image.unlink(missing_ok=True)

    def _delete_path(self, path: Path) -> None:
        payload = self._load(path)
        if payload and payload.get("image"):
            (self.vault_dir / str(payload["image"])).unlink(missing_ok=True)
        path.unlink(missing_ok=True)

    def search(
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
        connection = sqlite3.connect(":memory:")
        try:
            connection.execute(
                "CREATE VIRTUAL TABLE recall_windows USING fts5("
                "key UNINDEXED, app, title, files)"
            )
            connection.execute(
                "CREATE VIRTUAL TABLE recall_visual USING fts5(name UNINDEXED, ocr)"
            )
            loaded = []
            for path in self._paths():
                payload = self._load(path)
                if not payload:
                    continue
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
                    connection.execute(
                        "INSERT INTO recall_windows VALUES (?, ?, ?, ?)",
                        (
                            f"{path.name}#{index}",
                            str(window.get("app_name") or window.get("app_id") or ""),
                            str(window.get("title") or ""),
                            "\n".join(str(value) for value in window.get("open_files", [])),
                        ),
                    )
                if not visible_windows:
                    continue
                preview_allowed = not excluded_visible
                if preview_allowed:
                    connection.execute(
                        "INSERT INTO recall_visual VALUES (?, ?)",
                        (path.name, str(payload.get("ocr_text") or "")),
                    )
                loaded.append((path, payload, visible_windows, preview_allowed))

            window_candidates: dict[str, float] = {}
            visual_candidates: dict[str, float] = {}
            if needle:
                terms = re.findall(r"[\w.-]+", needle)[:16]
                expression = " OR ".join(f'"{term.replace(chr(34), "")}"' for term in terms)
                if expression:
                    with contextlib.suppress(sqlite3.OperationalError):
                        for key, rank in connection.execute(
                            "SELECT key, bm25(recall_windows,0,6,5,3) "
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
                query_terms = set(re.findall(r"[\w]+", needle))
                for path, _payload, windows, _preview_allowed in loaded:
                    for index, window in windows:
                        text_terms = set(re.findall(
                            r"[\w]+",
                            " ".join([
                                str(window.get("app_name") or window.get("app_id") or ""),
                                str(window.get("title") or ""),
                                *(str(value) for value in window.get("open_files", [])),
                            ]).casefold(),
                        ))
                        related = len(query_terms & text_terms) / max(
                            1, len(query_terms | text_terms)
                        )
                        if related >= 0.08:
                            key = f"{path.name}#{index}"
                            window_candidates[key] = max(
                                window_candidates.get(key, 0.0), related
                            )

            results = []
            for path, payload, windows, preview_allowed in loaded:
                common = {
                    "name": path.name,
                    "captured_at": str(payload.get("captured_at") or "")[:128],
                    "modified": float(payload.get("modified") or path.stat().st_mtime),
                    "has_preview": bool(payload.get("image")) and preview_allowed,
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
                        "targets": self._targets(files, urls),
                        "urls": urls,
                        "rank": 0.0,
                        "match_type": "Timeline",
                        "result_kind": "timeline",
                        "ocr_excerpt": "",
                    })
                    continue

                for index, window in windows:
                    identity = "\n".join((
                        str(window.get("app_id", "")),
                        str(window.get("app_name", "")),
                    )).casefold()
                    if app and app.casefold() not in identity:
                        continue
                    key = f"{path.name}#{index}"
                    if needle and key not in window_candidates:
                        continue
                    files = [str(value) for value in window.get("open_files", [])]
                    title = str(window.get("title") or "")
                    urls = list(dict.fromkeys(URL_RE.findall(title)))
                    results.append({
                        **common,
                        "apps": [str(window.get("app_name") or window.get("app_id") or "")],
                        "titles": [title] if title else [],
                        "files": files,
                        "targets": self._targets(files, urls),
                        "urls": urls,
                        "rank": round(window_candidates.get(key, 0.0), 4),
                        "match_type": self._window_match_type(window, needle),
                        "result_kind": "window",
                        "matched_window": window,
                        "window_index": index,
                        "ocr_excerpt": "",
                    })

                if needle and not app and path.name in visual_candidates:
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
                        "ocr_excerpt": " ".join(ocr_text.split())[:320],
                    })
            results.sort(
                key=lambda value: (-float(value["rank"]), -float(value["modified"]))
            )
            return results[:max(1, min(250, int(limit)))]
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
    def _window_match_type(window: dict, needle: str) -> str:
        if not needle:
            return "Window"
        if needle in str(window.get("title") or "").casefold():
            return "Window text"
        if any(needle in str(value).casefold() for value in window.get("open_files", [])):
            return "Window file"
        if needle in "\n".join((
            str(window.get("app_name") or ""), str(window.get("app_id") or "")
        )).casefold():
            return "Application"
        return "Related window"

    def preview_bytes(self, record: str) -> bytes | None:
        if not RECORD_RE.fullmatch(record):
            return None
        payload = self._load(self.vault_dir / record)
        name = str(payload.get("image") or "") if payload else ""
        if not re.fullmatch(r"recall-\d{8}-\d{6}-\d{6}\.ssimg", name):
            return None
        with contextlib.suppress(OSError, ValueError):
            return self._decrypt((self.vault_dir / name).read_bytes(), name)
        return None

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
        return removed

    def clear(self) -> int:
        return self.delete()

    def storage_bytes(self) -> int:
        if not self.vault_dir.is_dir():
            return 0
        return sum(path.stat().st_size for path in self.vault_dir.iterdir() if path.is_file() and not path.is_symlink())
