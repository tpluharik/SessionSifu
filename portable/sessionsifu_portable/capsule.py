"""Encrypted, fail-closed workspace capsule manifests and launch backends.

Capsules deliberately distinguish profile separation from an OS-enforced
sandbox.  Callers must show :meth:`CapsuleManager.preflight` before launch.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import platform
import re
import secrets
import shutil
import stat
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

try:
    import keyring
except ImportError:  # pragma: no cover - release packages include keyring
    keyring = None


CAPSULE_SCHEMA = 1
MAX_CAPSULE_BYTES = 256 * 1024
MAX_APPLICATIONS = 32
MAX_MAPPED_FOLDERS = 16
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,63}$")
FLATPAK_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*(?:\.[A-Za-z0-9_-]+){2,}$")
KEYRING_SERVICE = "org.sessionsifu.WorkspaceCapsules"
KEYRING_ACCOUNT = "default"
AAD = b"SessionSifuWorkspaceCapsule:v1"


def _bounded_text(value: Any, maximum: int = 512) -> str:
    return str(value or "").strip()[:maximum]


@dataclass(slots=True)
class CapsuleApplication:
    identity: str

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "CapsuleApplication":
        identity = _bounded_text(value.get("identity"))
        if not identity or any(ord(char) < 32 for char in identity):
            raise ValueError("Capsule application identity is invalid")
        return cls(identity=identity)


@dataclass(slots=True)
class WorkspaceCapsule:
    name: str
    backend: str
    applications: list[CapsuleApplication]
    offline: bool = False
    mapped_folders: list[str] = field(default_factory=list)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    schema: int = CAPSULE_SCHEMA

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "WorkspaceCapsule":
        if int(value.get("schema") or 0) != CAPSULE_SCHEMA:
            raise ValueError("Capsule schema is unsupported")
        name = CapsuleStore.validate_name(value.get("name"))
        backend = _bounded_text(value.get("backend"), 64)
        if backend not in {"profile", "flatpak", "windows-sandbox"}:
            raise ValueError("Capsule backend is unsupported")
        raw_apps = value.get("applications")
        if not isinstance(raw_apps, list) or len(raw_apps) > MAX_APPLICATIONS:
            raise ValueError("Capsule application list is invalid")
        applications = [
            CapsuleApplication.from_dict(item)
            for item in raw_apps
            if isinstance(item, dict)
        ]
        if backend != "windows-sandbox" and not applications:
            raise ValueError("Capsule requires at least one application")
        folders = [_bounded_text(item, 4096) for item in list(value.get("mapped_folders") or [])]
        if len(folders) > MAX_MAPPED_FOLDERS or any(not item for item in folders):
            raise ValueError("Capsule mapped-folder list is invalid")
        return cls(
            name=name,
            backend=backend,
            applications=applications,
            offline=bool(value.get("offline")),
            mapped_folders=folders,
            created_at=_bounded_text(value.get("created_at"), 128),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "name": self.name,
            "backend": self.backend,
            "applications": [asdict(item) for item in self.applications],
            "offline": self.offline,
            "mapped_folders": list(self.mapped_folders),
            "created_at": self.created_at,
        }


class CapsuleStore:
    """Owner-private encrypted capsule storage with atomic replacement."""

    def __init__(self, root: Path, test_key: bytes | None = None) -> None:
        self.root = Path(root)
        self.capsule_dir = self.root / "capsules"
        self.key_path = self.root / "capsules.key"
        self._test_key = test_key

    @staticmethod
    def validate_name(value: Any) -> str:
        name = _bounded_text(value, 64)
        if not NAME_RE.fullmatch(name):
            raise ValueError(
                "Capsule names may use letters, numbers, spaces, dots, dashes and underscores"
            )
        return name

    @staticmethod
    def _filename(name: str) -> str:
        digest = hashlib.sha256(name.casefold().encode("utf-8")).hexdigest()
        return f"capsule-{digest}.json"

    def _prepare_directory(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.capsule_dir.mkdir(parents=True, exist_ok=True)
        for directory in (self.root, self.capsule_dir):
            info = directory.lstat()
            if stat.S_ISLNK(info.st_mode):
                raise ValueError("Refusing symbolic-link capsule storage")
            if os.name != "nt":
                if info.st_uid != os.getuid():
                    raise ValueError("Refusing capsule storage owned by another user")
                os.chmod(directory, 0o700)

    def _key(self) -> bytes:
        if self._test_key is not None:
            if len(self._test_key) != 32:
                raise ValueError("Invalid test capsule key")
            return self._test_key
        self._prepare_directory()
        # A file fallback created while the desktop keyring was unavailable
        # remains authoritative. Otherwise a later-working keyring would
        # silently create a different key and strand existing capsules.
        if self.key_path.exists():
            info = self.key_path.lstat()
            if stat.S_ISLNK(info.st_mode):
                raise ValueError("Refusing symbolic-link capsule key")
            if os.name != "nt" and info.st_uid != os.getuid():
                raise ValueError("Refusing capsule key owned by another user")
            candidate = self.key_path.read_bytes()
            if len(candidate) != 32:
                raise ValueError("Invalid capsule key")
            return candidate
        if keyring is not None:
            try:
                encoded = keyring.get_password(KEYRING_SERVICE, KEYRING_ACCOUNT)
                if encoded:
                    candidate = base64.b64decode(encoded, validate=True)
                    if len(candidate) == 32:
                        return candidate
                candidate = secrets.token_bytes(32)
                keyring.set_password(
                    KEYRING_SERVICE, KEYRING_ACCOUNT, base64.b64encode(candidate).decode("ascii")
                )
                return candidate
            except Exception:
                pass
        candidate = secrets.token_bytes(32)
        descriptor = os.open(self.key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as output:
            output.write(candidate)
        return candidate

    def _path(self, name: str) -> Path:
        return self.capsule_dir / self._filename(self.validate_name(name))

    def save(self, capsule: WorkspaceCapsule) -> Path:
        capsule = WorkspaceCapsule.from_dict(capsule.to_dict())
        self._prepare_directory()
        plaintext = json.dumps(
            capsule.to_dict(), ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        if len(plaintext) > MAX_CAPSULE_BYTES:
            raise ValueError("Capsule manifest is too large")
        nonce = secrets.token_bytes(12)
        envelope = json.dumps(
            {
                "format": "sessionsifu-capsule-aesgcm-v1",
                "nonce": base64.b64encode(nonce).decode("ascii"),
                "ciphertext": base64.b64encode(
                    AESGCM(self._key()).encrypt(nonce, plaintext, AAD)
                ).decode("ascii"),
            },
            separators=(",", ":"),
        ).encode("ascii")
        path = self._path(capsule.name)
        if path.exists() and path.is_symlink():
            raise ValueError("Refusing symbolic-link capsule manifest")
        with tempfile.NamedTemporaryFile("wb", dir=self.capsule_dir, delete=False) as output:
            output.write(envelope)
            temporary = Path(output.name)
        try:
            if os.name != "nt":
                os.chmod(temporary, 0o600)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        return path

    def _load_path(self, path: Path) -> WorkspaceCapsule:
        if path.is_symlink() or not path.is_file():
            raise ValueError("Capsule manifest is unavailable")
        if path.resolve().parent != self.capsule_dir.resolve():
            raise ValueError("Capsule manifest is outside SessionSifu storage")
        if path.stat().st_size > MAX_CAPSULE_BYTES * 2:
            raise ValueError("Capsule manifest is too large")
        envelope = json.loads(path.read_text(encoding="ascii"))
        if envelope.get("format") != "sessionsifu-capsule-aesgcm-v1":
            raise ValueError("Capsule envelope is unsupported")
        try:
            nonce = base64.b64decode(envelope["nonce"], validate=True)
            ciphertext = base64.b64decode(envelope["ciphertext"], validate=True)
            plaintext = AESGCM(self._key()).decrypt(nonce, ciphertext, AAD)
        except Exception as error:
            raise ValueError("Capsule authentication failed") from error
        if len(plaintext) > MAX_CAPSULE_BYTES:
            raise ValueError("Capsule manifest is too large")
        return WorkspaceCapsule.from_dict(json.loads(plaintext))

    def load(self, name: str) -> WorkspaceCapsule:
        return self._load_path(self._path(name))

    def list(self) -> list[WorkspaceCapsule]:
        self._prepare_directory()
        capsules: list[WorkspaceCapsule] = []
        for path in sorted(self.capsule_dir.glob("capsule-*.json"))[:1024]:
            if path.is_file() and not path.is_symlink():
                capsules.append(self._load_path(path))
        return sorted(capsules, key=lambda item: item.name.casefold())

    def delete(self, name: str) -> None:
        path = self._path(name)
        if path.is_symlink():
            raise ValueError("Refusing symbolic-link capsule manifest")
        path.unlink(missing_ok=True)
        # Profile data is intentionally not deleted recursively without a
        # separate user-facing data deletion workflow.

    def delete_data(self, name: str) -> bool:
        self._prepare_directory()
        profiles = self.capsule_dir / "profiles"
        target = profiles / self._filename(name).removesuffix(".json")
        if target.is_symlink():
            raise ValueError("Refusing symbolic-link capsule profile data")
        if not target.exists():
            return False
        if target.resolve().parent != profiles.resolve():
            raise ValueError("Capsule profile data is outside SessionSifu storage")
        shutil.rmtree(target)
        return True


class CapsuleManager:
    PROFILE_FLAGS = {
        "firefox": ("-profile",),
        "firefox-esr": ("-profile",),
        "code": ("--user-data-dir",),
        "codium": ("--user-data-dir",),
        "google-chrome": ("--user-data-dir",),
        "google-chrome-stable": ("--user-data-dir",),
        "chromium": ("--user-data-dir",),
        "chromium-browser": ("--user-data-dir",),
        "brave-browser": ("--user-data-dir",),
        "microsoft-edge": ("--user-data-dir",),
        "vivaldi": ("--user-data-dir",),
    }

    def __init__(self, store: CapsuleStore) -> None:
        self.store = store

    def create(
        self,
        name: str,
        backend: str,
        applications: list[str],
        *,
        offline: bool = False,
        mapped_folders: list[str] | None = None,
    ) -> Path:
        capsule = WorkspaceCapsule(
            name=self.store.validate_name(name),
            backend=backend,
            applications=[CapsuleApplication(identity=item) for item in applications],
            offline=offline,
            mapped_folders=mapped_folders or [],
        )
        return self.store.save(capsule)

    def _profile_command(self, capsule: WorkspaceCapsule, identity: str) -> tuple[list[str], str]:
        executable = identity if Path(identity).is_absolute() else shutil.which(identity)
        if not executable or not Path(executable).is_file():
            return [], "Application executable is unavailable"
        basename = Path(executable).name.casefold().removesuffix(".exe")
        flags = self.PROFILE_FLAGS.get(basename)
        if not flags:
            return [], "No reviewed profile adapter exists for this application"
        profile_root = (
            self.store.capsule_dir
            / "profiles"
            / self.store._filename(capsule.name).removesuffix(".json")
            / hashlib.sha256(identity.casefold().encode("utf-8")).hexdigest()[:16]
        )
        return [str(executable), *flags, str(profile_root)], ""

    def preflight(self, name: str) -> dict[str, Any]:
        capsule = self.store.load(name)
        commands: list[list[str]] = []
        errors: list[str] = []
        warnings: list[str] = []
        boundary = "profile separation"
        effective = {
            "network": "host access",
            "files": "application profile plus normal application permissions",
            "clipboard": "host access",
        }
        if capsule.backend == "profile":
            if capsule.offline:
                errors.append("Profile-only capsules cannot enforce offline networking")
            for application in capsule.applications:
                command, error = self._profile_command(capsule, application.identity)
                if error:
                    errors.append(f"{application.identity}: {error}")
                else:
                    commands.append(command)
            warnings.append("This mode separates supported profiles but is not a security sandbox")
        elif capsule.backend == "flatpak":
            boundary = "Flatpak application sandbox"
            effective = {
                "network": "disabled for this launch" if capsule.offline else "package permission",
                "files": "Flatpak permissions and user-mediated portals",
                "clipboard": "desktop/compositor policy",
            }
            flatpak = shutil.which("flatpak")
            if platform.system() != "Linux" or not flatpak:
                errors.append("Flatpak is unavailable on this system")
            else:
                for application in capsule.applications:
                    if not FLATPAK_ID_RE.fullmatch(application.identity):
                        errors.append(f"{application.identity}: invalid Flatpak application ID")
                        continue
                    probe = subprocess.run(
                        [flatpak, "info", application.identity],
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=8,
                        check=False,
                    )
                    if probe.returncode != 0:
                        errors.append(f"{application.identity}: Flatpak application is not installed")
                        continue
                    commands.append(
                        [
                            flatpak,
                            "run",
                            *(["--unshare=network"] if capsule.offline else []),
                            application.identity,
                        ]
                    )
            if capsule.mapped_folders:
                errors.append("Flatpak capsules require portal-selected files, not static mapped folders")
        else:
            boundary = "Windows Sandbox virtualized environment"
            effective = {
                "network": "disabled" if capsule.offline else "enabled",
                "files": "read-only mapped folders",
                "clipboard": "disabled",
            }
            if platform.system() != "Windows":
                warnings.append("The .wsb file can be exported here but runs only on supported Windows editions")
            if capsule.applications:
                warnings.append("Applications must be provisioned inside Windows Sandbox; host executables are not injected")
        return {
            "name": capsule.name,
            "backend": capsule.backend,
            "boundary": boundary,
            "security_boundary": capsule.backend in {"flatpak", "windows-sandbox"},
            "supported": not errors,
            "applications": [item.identity for item in capsule.applications],
            "commands": commands,
            "effective_permissions": effective,
            "errors": errors,
            "warnings": warnings,
        }

    def launch(self, name: str) -> dict[str, Any]:
        plan = self.preflight(name)
        if not plan["supported"]:
            raise RuntimeError("; ".join(plan["errors"]))
        if plan["backend"] == "windows-sandbox":
            raise RuntimeError("Export this capsule as a .wsb file and review it before launch")
        launched = 0
        for command in plan["commands"]:
            if plan["backend"] == "profile":
                profile = Path(command[-1])
                profile.mkdir(parents=True, exist_ok=True)
                if os.name != "nt":
                    os.chmod(profile, 0o700)
            subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=os.name != "nt",
            )
            launched += 1
        return {**plan, "launched": launched}

    def export_windows_sandbox(self, name: str, destination: Path) -> Path:
        capsule = self.store.load(name)
        if capsule.backend != "windows-sandbox":
            raise ValueError("Only a Windows Sandbox capsule can be exported as .wsb")
        destination = Path(destination)
        if destination.suffix.casefold() != ".wsb":
            destination = destination.with_suffix(".wsb")
        if destination.exists() and destination.is_symlink():
            raise ValueError("Refusing symbolic-link Windows Sandbox export")
        root = ET.Element("Configuration")
        for key, value in (
            ("VGpu", "Disable"),
            ("Networking", "Disable" if capsule.offline else "Enable"),
            ("AudioInput", "Disable"),
            ("VideoInput", "Disable"),
            ("PrinterRedirection", "Disable"),
            ("ClipboardRedirection", "Disable"),
            ("ProtectedClient", "Enable"),
            ("MemoryInMB", "4096"),
        ):
            ET.SubElement(root, key).text = value
        if capsule.mapped_folders:
            mapped = ET.SubElement(root, "MappedFolders")
            for raw in capsule.mapped_folders:
                if any(ord(char) < 32 for char in raw):
                    raise ValueError("Mapped folder contains control characters")
                folder = ET.SubElement(mapped, "MappedFolder")
                ET.SubElement(folder, "HostFolder").text = raw
                ET.SubElement(folder, "ReadOnly").text = "true"
        ET.indent(root, space="  ")
        payload = ET.tostring(root, encoding="utf-8", xml_declaration=True)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("wb", dir=destination.parent, delete=False) as output:
            output.write(payload)
            temporary = Path(output.name)
        try:
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
        return destination
