"""Password-encrypted, user-controlled SessionSifu export/import archives."""

from __future__ import annotations

import io
import json
import os
import re
import tempfile
import zipfile
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from .model import SessionSnapshot

ARCHIVE_MAGIC = b"SSXA1\0"
MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
MAX_ARCHIVE_FILES = 40_000
SAFE_MEMBER_RE = re.compile(r"^(manifest\.json|sessions/[^/]+\.json|history/[^/]+\.json|recall/[^/]+\.(?:json|bin))$")


def _derive(passphrase: str, salt: bytes) -> bytes:
    if len(passphrase) < 12:
        raise ValueError("Archive passphrase must contain at least 12 characters")
    return Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(
        passphrase.encode("utf-8")[:4096]
    )


class ArchiveManager:
    def __init__(self, session_store, recall_store) -> None:
        self.sessions = session_store
        self.recall = recall_store

    def export(self, destination: Path, passphrase: str) -> dict[str, int]:
        destination = destination.expanduser()
        if destination.exists() and destination.is_symlink():
            raise ValueError("Refusing to overwrite a symbolic-link archive")
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = io.BytesIO()
        counts = {"sessions": 0, "history": 0, "recall": 0, "images": 0}
        with zipfile.ZipFile(payload, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            archive.writestr("manifest.json", json.dumps({
                "format": 1,
                "application": "SessionSifu",
                "contents": ["sessions", "history", "privacy-recall"],
            }))
            for kind, paths in (
                ("sessions", self.sessions.list_named()),
                ("history", self.sessions.list_history()),
            ):
                for path in paths:
                    session = self.sessions.load(path)
                    archive.writestr(
                        f"{kind}/{path.name}",
                        json.dumps(session.to_dict(), ensure_ascii=False),
                    )
                    counts[kind] += 1
            for record, metadata, images in self.recall.export_records():
                archive.writestr(
                    f"recall/{record}.json",
                    json.dumps(metadata, ensure_ascii=False, separators=(",", ":")),
                )
                counts["recall"] += 1
                for image_name, image in images.items():
                    archive.writestr(f"recall/{record}--{image_name}.bin", image)
                    counts["images"] += 1
            if payload.tell() > MAX_ARCHIVE_BYTES:
                raise ValueError("Export exceeds the archive size limit")
        salt, nonce = os.urandom(16), os.urandom(12)
        encrypted = ARCHIVE_MAGIC + salt + nonce + AESGCM(_derive(passphrase, salt)).encrypt(
            nonce, payload.getvalue(), ARCHIVE_MAGIC
        )
        if len(encrypted) > MAX_ARCHIVE_BYTES:
            raise ValueError("Encrypted export exceeds the archive size limit")
        descriptor, name = tempfile.mkstemp(prefix=".sessionsifu-export-", dir=destination.parent)
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(encrypted)
                output.flush()
                os.fsync(output.fileno())
            temporary.chmod(0o600)
            os.replace(temporary, destination)
            destination.chmod(0o600)
        finally:
            temporary.unlink(missing_ok=True)
        return counts

    def import_archive(self, source: Path, passphrase: str) -> dict[str, int]:
        source = source.expanduser()
        if source.is_symlink() or not source.is_file() or not 0 < source.stat().st_size <= MAX_ARCHIVE_BYTES:
            raise ValueError("Archive is not a bounded regular file")
        encrypted = source.read_bytes()
        if not encrypted.startswith(ARCHIVE_MAGIC) or len(encrypted) < len(ARCHIVE_MAGIC) + 44:
            raise ValueError("Archive has an invalid envelope")
        offset = len(ARCHIVE_MAGIC)
        salt, nonce, ciphertext = encrypted[offset:offset + 16], encrypted[offset + 16:offset + 28], encrypted[offset + 28:]
        try:
            raw = AESGCM(_derive(passphrase, salt)).decrypt(nonce, ciphertext, ARCHIVE_MAGIC)
        except Exception as error:
            raise ValueError("Archive passphrase is incorrect or the archive is damaged") from error
        counts = {"sessions": 0, "history": 0, "recall": 0, "images": 0}
        with zipfile.ZipFile(io.BytesIO(raw), "r") as archive:
            members = archive.infolist()
            if len(members) > MAX_ARCHIVE_FILES:
                raise ValueError("Archive contains too many files")
            if sum(member.file_size for member in members) > MAX_ARCHIVE_BYTES:
                raise ValueError("Archive expands beyond the size limit")
            if any(
                not SAFE_MEMBER_RE.fullmatch(member.filename)
                or member.is_dir()
                or member.file_size > MAX_ARCHIVE_BYTES
                for member in members
            ):
                raise ValueError("Archive contains an unsafe member")
            manifest = json.loads(archive.read("manifest.json"))
            if manifest.get("format") != 1 or manifest.get("application") != "SessionSifu":
                raise ValueError("Archive format is unsupported")
            recall_payloads: dict[str, dict] = {}
            recall_images: dict[str, dict[str, bytes]] = {}
            for member in members:
                name = member.filename
                if name.startswith("sessions/"):
                    session = SessionSnapshot.from_dict(json.loads(archive.read(member)))
                    stem = Path(name).stem[:48]
                    candidate = stem
                    suffix = 1
                    while (self.sessions.named_dir / f"{candidate}.json").exists():
                        suffix += 1
                        candidate = f"{stem}-imported-{suffix}"
                    self.sessions.save_named(candidate, session)
                    counts["sessions"] += 1
                elif name.startswith("history/"):
                    self.sessions.save_history(
                        SessionSnapshot.from_dict(json.loads(archive.read(member)))
                    )
                    counts["history"] += 1
                elif name.startswith("recall/") and name.endswith(".json"):
                    record = Path(name).stem
                    value = json.loads(archive.read(member))
                    if not isinstance(value, dict):
                        raise ValueError("Recall archive metadata is invalid")
                    recall_payloads[record] = value
                elif name.startswith("recall/") and name.endswith(".bin"):
                    combined = Path(name).name[:-4]
                    record, separator, image_name = combined.partition("--")
                    if not separator:
                        raise ValueError("Recall archive image name is invalid")
                    recall_images.setdefault(record, {})[image_name] = archive.read(member)
                    counts["images"] += 1
            for record, metadata in recall_payloads.items():
                self.recall.import_record(metadata, recall_images.get(record, {}))
                counts["recall"] += 1
        return counts
