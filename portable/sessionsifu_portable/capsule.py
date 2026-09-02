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
import threading
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
FLATPAK_ALIASES = {
    "signal": "org.signal.Signal",
    "signal-desktop": "org.signal.Signal",
    "firefox": "org.mozilla.firefox",
    "code": "com.visualstudio.code",
    "codium": "com.vscodium.codium",
}
KEYRING_SERVICE = "org.sessionsifu.WorkspaceCapsules"
KEYRING_ACCOUNT = "default"
AAD = b"SessionSifuWorkspaceCapsule:v1"


def _bounded_text(value: Any, maximum: int = 512) -> str:
    return str(value or "").strip()[:maximum]


@dataclass(slots=True)
class CapsuleApplication:
    identity: str
    profile: str = "auto"

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "CapsuleApplication":
        identity = _bounded_text(value.get("identity"))
        if not identity or any(ord(char) < 32 for char in identity):
            raise ValueError("Capsule application identity is invalid")
        profile = _bounded_text(value.get("profile") or "auto", 64)
        if profile not in {
            "auto",
            "communications",
            "browser",
            "development",
            "documents",
            "standard",
        }:
            raise ValueError("Capsule application profile is invalid")
        return cls(identity=identity, profile=profile)


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
        capsule_key = self._filename(name).removesuffix(".json")
        targets = [
            (profiles, profiles / capsule_key),
            (
                _firefox_snap_profile_base(),
                _firefox_snap_profile_base() / capsule_key,
            ),
        ]
        try:
            capsule = self.load(name)
        except (OSError, ValueError):
            capsule = None
        if capsule is not None and capsule.backend == "flatpak":
            for application in capsule.applications:
                app_id = FLATPAK_ALIASES.get(
                    application.identity.casefold(), application.identity
                )
                if not FLATPAK_ID_RE.fullmatch(app_id):
                    continue
                app_root = _real_home() / ".var" / "app" / app_id
                for data_kind in ("config", "data", "cache"):
                    base = app_root / data_kind / "sessionsifu-capsules"
                    targets.append((base, base / capsule_key))
        deleted = False
        for base, target in targets:
            if target.is_symlink():
                raise ValueError("Refusing symbolic-link capsule profile data")
            if not target.exists():
                continue
            if target.resolve().parent != base.resolve():
                raise ValueError("Capsule profile data is outside SessionSifu storage")
            shutil.rmtree(target)
            deleted = True
        return deleted


def _real_home() -> Path:
    """Return the host home even when SessionSifu itself runs from a snap."""
    candidate = Path(os.environ.get("SNAP_REAL_HOME") or Path.home()).expanduser()
    return candidate.resolve()


def _firefox_snap_profile_base() -> Path:
    # Firefox's strict snap may write inside its own SNAP_USER_COMMON but cannot
    # use SessionSifu's hidden ~/.config tree. Keep the directory non-hidden so
    # it also remains reachable through the snap home interface.
    return _real_home() / "snap" / "firefox" / "common" / "sessionsifu-profiles"


class CapsuleManager:
    APPLICATION_ALIASES = {
        # The desktop-facing product name is commonly entered in launchers,
        # while the Debian/Ubuntu executable keeps its historical suffix.
        "signal": ("signal-desktop",),
    }
    PROFILE_FLAGS = {
        # The profile-taking option remains last: launch() can then create the
        # final command argument as an owner-private directory without trying
        # to parse application-specific flags.
        "firefox": ("--no-remote", "--profile"),
        "firefox-esr": ("--no-remote", "--profile"),
        "code": ("--new-window", "--user-data-dir"),
        "codium": ("--new-window", "--user-data-dir"),
        "google-chrome": ("--new-window", "--user-data-dir"),
        "google-chrome-stable": ("--new-window", "--user-data-dir"),
        "chromium": ("--new-window", "--user-data-dir"),
        "chromium-browser": ("--new-window", "--user-data-dir"),
        "brave-browser": ("--new-window", "--user-data-dir"),
        "microsoft-edge": ("--new-window", "--user-data-dir"),
        "vivaldi": ("--new-window", "--user-data-dir"),
    }
    PROFILE_LABELS = {
        "communications": "Private communications",
        "browser": "Private browsing",
        "development": "Isolated development",
        "documents": "Isolated documents",
        "standard": "Isolated application",
    }
    PROFILE_HINTS = {
        "communications": (
            "signal", "telegram", "discord", "slack", "element", "zulip",
            "teams", "thunderbird", "whatsapp", "messenger",
        ),
        "browser": (
            "firefox", "chromium", "chrome", "brave", "edge", "vivaldi",
            "browser", "epiphany",
        ),
        "development": (
            "visualstudio", "vscode", "codium", "jetbrains", "eclipse",
            "androidstudio", "builder", "gitg",
        ),
        "documents": (
            "libreoffice", "onlyoffice", "evince", "okular", "document",
            "texteditor", "gedit", "writer", "calc",
        ),
    }

    def __init__(self, store: CapsuleStore) -> None:
        self.store = store
        self._running_lock = threading.Lock()
        self._running: list[dict[str, Any]] = []

    @classmethod
    def application_profile(cls, identity: str, name: str = "") -> str:
        """Choose a conservative display/policy profile from trusted app metadata."""
        searchable = f"{identity} {name}".casefold()
        for profile, hints in cls.PROFILE_HINTS.items():
            if any(hint in searchable for hint in hints):
                return profile
        return "standard"

    def available_applications(self) -> list[dict[str, str]]:
        """Return only applications for which an enforceable capsule backend exists.

        Linux host executables are intentionally absent: listing them would imply a
        security boundary SessionSifu cannot provide. Flatpak supplies both the
        discoverable application catalog and the enforced sandbox boundary.
        """
        if platform.system() != "Linux":
            return []
        flatpak = shutil.which("flatpak")
        if not flatpak:
            return []
        try:
            result = subprocess.run(
                [flatpak, "list", "--app", "--columns=application,name"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=8,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return []
        if result.returncode != 0:
            return []
        applications: dict[str, dict[str, str]] = {}
        for raw_line in result.stdout.splitlines()[:4096]:
            columns = raw_line.split("\t", 1)
            app_id = columns[0].strip()
            if not FLATPAK_ID_RE.fullmatch(app_id):
                continue
            name = columns[1].strip() if len(columns) > 1 else ""
            profile = self.application_profile(app_id, name)
            applications[app_id.casefold()] = {
                "name": name or app_id,
                "identity": app_id,
                "backend": "flatpak",
                "profile": profile,
                "profile_label": self.PROFILE_LABELS[profile],
            }
        return sorted(
            applications.values(),
            key=lambda item: (item["name"].casefold(), item["identity"].casefold()),
        )

    @staticmethod
    def _is_firefox_snap_launcher(executable: str, basename: str) -> bool:
        if platform.system() != "Linux" or basename != "firefox":
            return False
        path = Path(executable)
        if path.as_posix() == "/snap/bin/firefox":
            return True
        try:
            return path.stat().st_size <= 128 * 1024 and "/snap/bin/firefox" in path.read_text(
                encoding="utf-8", errors="ignore"
            )
        except OSError:
            return False

    def _profile_base(
        self,
        capsule: WorkspaceCapsule,
        identity: str,
        executable: str,
        basename: str,
    ) -> Path:
        capsule_key = self.store._filename(capsule.name).removesuffix(".json")
        application_key = hashlib.sha256(identity.casefold().encode("utf-8")).hexdigest()[:16]
        if self._is_firefox_snap_launcher(executable, basename):
            return _firefox_snap_profile_base() / capsule_key / application_key
        return self.store.capsule_dir / "profiles" / capsule_key / application_key

    def _profile_is_busy(self, profile: Path) -> bool:
        profile_text = str(profile)
        with self._running_lock:
            for entry in self._running:
                process = entry["process"]
                if process.poll() is None and entry.get("profile") == profile_text:
                    return True
        return any(
            os.path.lexists(profile / marker)
            for marker in (
                ".parentlock",
                "parent.lock",
                "lock",
                "SingletonLock",
                "SingletonCookie",
                "SingletonSocket",
            )
        )

    def _available_profile(self, base: Path) -> Path:
        if not self._profile_is_busy(base):
            return base
        for instance in range(2, 34):
            candidate = base.with_name(f"{base.name}-instance-{instance}")
            if not self._profile_is_busy(candidate):
                return candidate
        return base.with_name(f"{base.name}-instance-{secrets.token_hex(6)}")

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
            applications=[
                CapsuleApplication(
                    identity=item,
                    profile=(
                        self.application_profile(self._flatpak_id(item))
                        if backend == "flatpak"
                        else "auto"
                    ),
                )
                for item in applications
            ],
            offline=offline,
            mapped_folders=mapped_folders or [],
        )
        return self.store.save(capsule)

    def _profile_command(self, capsule: WorkspaceCapsule, identity: str) -> tuple[list[str], str]:
        executable: str | None = None
        if Path(identity).is_absolute():
            executable = identity
        else:
            candidates = (identity, *self.APPLICATION_ALIASES.get(identity.casefold(), ()))
            executable = next(
                (path for candidate in candidates if (path := shutil.which(candidate))),
                None,
            )
        if not executable or not Path(executable).is_file():
            aliases = self.APPLICATION_ALIASES.get(identity.casefold(), ())
            hint = f" (also checked: {', '.join(aliases)})" if aliases else ""
            return [], f"Application executable is unavailable{hint}"
        basename = Path(executable).name.casefold().removesuffix(".exe")
        if basename == "signal-desktop":
            return [], (
                "Signal no longer honors its profile-directory switch; use the "
                "Flatpak sandbox backend (org.signal.Signal) so launch cannot join "
                "the existing host instance"
            )
        flags = self.PROFILE_FLAGS.get(basename)
        if not flags:
            return [], "No reviewed profile adapter exists for this application"
        profile_root = self._profile_base(capsule, identity, executable, basename)
        return [str(executable), *flags, str(profile_root)], ""

    @staticmethod
    def _flatpak_id(identity: str) -> str:
        return FLATPAK_ALIASES.get(identity.casefold(), identity)

    def _flatpak_command(
        self, flatpak: str, capsule: WorkspaceCapsule, identity: str
    ) -> tuple[list[str], str]:
        app_id = self._flatpak_id(identity)
        if not FLATPAK_ID_RE.fullmatch(app_id):
            return [], "invalid Flatpak application ID or unsupported application alias"
        probe = subprocess.run(
            [flatpak, "info", app_id],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=8,
            check=False,
        )
        if probe.returncode != 0:
            return [], (
                f"Flatpak application {app_id} is not installed; install and review it "
                f"first (for example: flatpak install flathub {app_id})"
            )
        capsule_key = self.store._filename(capsule.name).removesuffix(".json")
        application_key = hashlib.sha256(app_id.encode("utf-8")).hexdigest()[:16]
        relative_root = f"sessionsifu-capsules/{capsule_key}/{application_key}"
        private_root = f"/var/data/{relative_root}"
        app_key = app_id.casefold()
        application_arguments: list[str] = []
        if app_key == "org.mozilla.firefox":
            application_arguments = [
                "--no-remote", "--profile", f"{private_root}/browser-profile",
            ]
        elif app_key in {
            "org.chromium.chromium",
            "com.google.chrome",
            "com.brave.browser",
            "com.microsoft.edge",
            "com.vivaldi.vivaldi",
        }:
            application_arguments = [
                "--new-window", f"--user-data-dir={private_root}/browser-profile",
            ]
        elif app_key in {"com.visualstudio.code", "com.vscodium.codium"}:
            application_arguments = [
                "--new-window",
                f"--user-data-dir={private_root}/editor-data",
                f"--extensions-dir={private_root}/editor-extensions",
            ]
        command = [
            flatpak,
            "run",
            # Reset broad host filesystem grants inherited from the package or
            # lower-precedence overrides. Portals and app-specific storage stay
            # available, while unrelated host files remain outside the capsule.
            "--nofilesystem=host:reset",
            "--nosocket=ssh-auth",
            "--nosocket=gpg-agent",
            "--no-talk-name=org.freedesktop.secrets",
            "--no-talk-name=org.kde.kwalletd5",
            "--no-talk-name=org.kde.kwalletd6",
            f"--env=XDG_CONFIG_HOME=/var/config/{relative_root}",
            f"--env=XDG_DATA_HOME=/var/data/{relative_root}",
            f"--env=XDG_CACHE_HOME=/var/cache/{relative_root}",
            f"--env=XDG_STATE_HOME=/var/data/{relative_root}/state",
            f"--env=HOME={private_root}/home",
            "--env=SESSIONSIFU_CAPSULE=1",
            *(["--unshare=network"] if capsule.offline else []),
            app_id,
            *application_arguments,
        ]
        return command, ""

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
            "instance": "separate profile and process from an already-running host app",
        }
        if capsule.backend == "profile":
            boundary = "blocked legacy profile capsule"
            effective = {
                "network": "not isolated",
                "files": "normal host application permissions",
                "clipboard": "host access",
                "identity": "profile switches are not an OS security boundary",
            }
            errors.append(
                "Legacy profile-only capsules cannot meet strict container isolation; "
                "convert this capsule to an installed Flatpak application"
            )
            warnings.append(
                "The manifest remains available only for review, migration and data deletion"
            )
        elif capsule.backend == "flatpak":
            boundary = "isolated Flatpak capsule"
            effective = {
                "network": "disabled for this launch" if capsule.offline else "package permission",
                "files": "broad host grants removed; user-mediated portals remain",
                "clipboard": "desktop/compositor policy",
                "credentials": "host keyring and authentication-agent access removed",
                "identity": "capsule-specific clean application data",
                "anonymity": "local app state only; network address is not anonymized",
            }
            flatpak = shutil.which("flatpak")
            if platform.system() != "Linux" or not flatpak:
                errors.append("Flatpak is unavailable on this system")
            else:
                for application in capsule.applications:
                    command, error = self._flatpak_command(
                        flatpak, capsule, application.identity
                    )
                    if error:
                        errors.append(f"{application.identity}: {error}")
                    else:
                        commands.append(command)
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
            "separate_instance": capsule.backend == "flatpak",
            "supported": not errors,
            "applications": [item.identity for item in capsule.applications],
            "application_profiles": [
                {
                    "identity": item.identity,
                    "profile": (
                        self.application_profile(self._flatpak_id(item.identity))
                        if item.profile == "auto" and capsule.backend == "flatpak"
                        else item.profile
                    ),
                    "label": self.PROFILE_LABELS.get(
                        self.application_profile(self._flatpak_id(item.identity))
                        if item.profile == "auto" and capsule.backend == "flatpak"
                        else item.profile,
                        "Legacy profile",
                    ),
                }
                for item in capsule.applications
            ],
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
        launched_applications: list[dict[str, Any]] = []
        for identity, command in zip(plan["applications"], plan["commands"], strict=True):
            profile: Path | None = None
            if plan["backend"] == "profile":
                profile = self._available_profile(Path(command[-1]))
                command = [*command[:-1], str(profile)]
                profile.mkdir(parents=True, exist_ok=True)
                if os.name != "nt":
                    os.chmod(profile, 0o700)
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=os.name != "nt",
            )
            launched += 1
            entry = {
                "capsule": plan["name"],
                "backend": plan["backend"],
                "boundary": plan["boundary"],
                "application": identity,
                "pid": process.pid if isinstance(process.pid, int) else 0,
                "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "profile": str(profile) if profile is not None else "",
                "process": process,
            }
            with self._running_lock:
                self._running.append(entry)
            launched_applications.append({
                key: value for key, value in entry.items() if key != "process"
            })
        return {
            **plan,
            "launched": launched,
            "launched_applications": launched_applications,
        }

    def list_running(self) -> list[dict[str, Any]]:
        """Return applications launched by this manager that are still alive.

        This intentionally tracks only child processes started by SessionSifu.
        It does not inspect unrelated host processes or compositor windows.
        """
        live: list[dict[str, Any]] = []
        with self._running_lock:
            for entry in self._running:
                process = entry["process"]
                if process.poll() is not None:
                    continue
                live.append(entry)
            self._running = live
            return [
                {key: value for key, value in entry.items() if key != "process"}
                for entry in live
            ]

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
