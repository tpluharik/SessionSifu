#!/usr/bin/env python3
"""Select static OpenSSL only for the Intel macOS source-build path."""
import os
from pathlib import Path
import platform
import subprocess


def configure(*, environment=None):
    environment = os.environ if environment is None else environment
    if platform.system() != "Darwin" or platform.machine() != "x86_64":
        return {}
    prefix = Path(subprocess.check_output(
        ["brew", "--prefix", "openssl@3"], text=True, timeout=30).strip())
    if not prefix.is_absolute() or any(not (prefix / "lib" / name).is_file()
                                     for name in ("libssl.a", "libcrypto.a")):
        raise RuntimeError("Intel macOS needs OpenSSL static development libraries")
    values = {"OPENSSL_STATIC": "1", "OPENSSL_DIR": str(prefix),
              "PIP_NO_CACHE_DIR": "1", "PIP_NO_BINARY": "cryptography"}
    if any("\n" in value or "\r" in value for value in values.values()):
        raise ValueError("Invalid native build path")
    with Path(environment["GITHUB_ENV"]).open("a") as output:
        for key, value in values.items():
            output.write(f"{key}={value}\n")
    return values


if __name__ == "__main__":
    configured = configure()
    print("Intel macOS static OpenSSL configured" if configured else "Native wheel path unchanged")
