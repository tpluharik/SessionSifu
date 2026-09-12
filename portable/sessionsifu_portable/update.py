"""Bounded, repository-pinned update discovery for portable bundles."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import platform
import re
import tempfile
from pathlib import Path
import urllib.parse
import urllib.request

from . import VERSION

RELEASE_API = "https://api.github.com/repos/tpluharik/SessionSifu/releases/latest"
MAX_METADATA = 512 * 1024
MAX_CHECKSUMS = 256 * 1024
MAX_BUNDLE = 250 * 1024 * 1024
TRUSTED_DOWNLOAD_HOSTS = {
    "github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
}


@dataclass(frozen=True, slots=True)
class PortableUpdate:
    version: str
    asset_name: str
    asset_url: str
    checksums_url: str
    release_url: str
    size: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _version(value: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", value.strip())
    if not match:
        raise ValueError("Release version is invalid")
    return tuple(int(part) for part in match.groups())


def _asset_name(version: str) -> str:
    system = platform.system()
    machine = platform.machine().casefold()
    arch = "arm64" if machine in {"arm64", "aarch64"} else "x64"
    if system == "Windows":
        return f"SessionSifu-{version}-windows-{arch}.zip"
    if system == "Darwin":
        return f"SessionSifu-{version}-macos-{arch}.zip"
    if system == "Linux":
        return f"SessionSifu-{version}-linux-{arch}.tar.gz"
    raise ValueError(f"Portable updates are unavailable for {system}")


def _github_asset_url(value: object) -> str:
    url = str(value or "")
    parsed = urllib.parse.urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "github.com"
        or not parsed.path.startswith("/tpluharik/SessionSifu/releases/download/")
    ):
        raise ValueError("Release asset URL is outside GitHub")
    return url


def _read_json(url: str, timeout: int) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": f"SessionSifu/{VERSION}"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if urllib.parse.urlparse(response.geturl()).hostname != "api.github.com":
            raise ValueError("Update metadata was redirected outside GitHub")
        payload = response.read(MAX_METADATA + 1)
    if len(payload) > MAX_METADATA:
        raise ValueError("Update metadata exceeds the size limit")
    value = json.loads(payload)
    if not isinstance(value, dict):
        raise ValueError("Update metadata is invalid")
    return value


def check_portable_update(timeout: int = 8) -> PortableUpdate | None:
    release = _read_json(RELEASE_API, timeout)
    latest = str(release.get("tag_name") or "")
    if _version(latest) <= _version(VERSION):
        return None
    assets = [value for value in release.get("assets", []) if isinstance(value, dict)]
    expected_name = _asset_name(latest.removeprefix("v"))
    bundle = next((value for value in assets if value.get("name") == expected_name), None)
    checksums = next((value for value in assets if value.get("name") == "SHA256SUMS"), None)
    if bundle is None or checksums is None:
        raise ValueError("The release has no matching portable bundle or checksum file")
    size = int(bundle.get("size") or 0)
    if size <= 0 or size > MAX_BUNDLE:
        raise ValueError("Portable update size is outside the allowed range")
    release_url = str(release.get("html_url") or "")
    if urllib.parse.urlparse(release_url).hostname != "github.com":
        raise ValueError("Release page is outside the SessionSifu GitHub repository")
    return PortableUpdate(
        version=latest.removeprefix("v"),
        asset_name=str(bundle["name"]),
        asset_url=_github_asset_url(bundle.get("browser_download_url")),
        checksums_url=_github_asset_url(checksums.get("browser_download_url")),
        release_url=release_url,
        size=size,
    )


def _download(url: str, limit: int, timeout: int) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": f"SessionSifu/{VERSION}"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        final = urllib.parse.urlparse(response.geturl())
        if final.scheme != "https" or final.hostname not in TRUSTED_DOWNLOAD_HOSTS:
            raise ValueError("GitHub redirected the update to an untrusted location")
        payload = response.read(limit + 1)
    if len(payload) > limit:
        raise ValueError("Downloaded update exceeds the size limit")
    return payload


def download_portable_update(update: PortableUpdate, destination: Path, timeout: int = 30) -> Path:
    checksums = _download(update.checksums_url, MAX_CHECKSUMS, timeout).decode("utf-8")
    expected = ""
    for line in checksums.splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2 and parts[1].lstrip("*") == update.asset_name:
            expected = parts[0].casefold()
            break
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ValueError("Release checksum for this portable bundle is unavailable")
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / update.asset_name
    request = urllib.request.Request(
        update.asset_url, headers={"User-Agent": f"SessionSifu/{VERSION}"}
    )
    received = 0
    actual = hashlib.sha256()
    temporary: Path | None = None
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            final = urllib.parse.urlparse(response.geturl())
            if final.scheme != "https" or final.hostname not in TRUSTED_DOWNLOAD_HOSTS:
                raise ValueError("GitHub redirected the update to an untrusted location")
            with tempfile.NamedTemporaryFile(dir=destination, delete=False) as output:
                temporary = Path(output.name)
                while chunk := response.read(1024 * 1024):
                    received += len(chunk)
                    if received > MAX_BUNDLE:
                        raise ValueError("Downloaded update exceeds the size limit")
                    actual.update(chunk)
                    output.write(chunk)
        if received != update.size or actual.hexdigest() != expected:
            raise ValueError("Portable update failed size or SHA-256 verification")
        temporary.replace(target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return target
