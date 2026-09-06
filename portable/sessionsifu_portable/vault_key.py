"""Fail-closed key continuity for legacy and new encrypted Recall vaults."""
import base64
import contextlib
import hashlib
import json
import os
import threading
from pathlib import Path

_mutex = threading.RLock()


@contextlib.contextmanager
def _locked(root):
    # An OS lock is released on process death (unlike a sentinel file).
    with _mutex:
        path = root / ".key-lock"
        if path.is_symlink():
            raise RuntimeError("Refusing symbolic-link Recall key lock")
        fd = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(fd, "r+b") as stream:
            if os.name == "nt":
                import msvcrt
                if not stream.read(1):
                    stream.write(b"0"); stream.flush()
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if os.name == "nt":
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def vault_key(root: Path, vault: Path, keyring, service: str, account: str, *, encoded_file: bool):
    """Never rotate a key because credentials are unavailable; preserve legacy formats."""
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with _locked(root):
        fallback = root / ".vault-key"
        descriptor = root / ".key-identity.json"
        if fallback.is_symlink() or descriptor.is_symlink():
            raise RuntimeError("Refusing symbolic-link Recall key metadata")
        identity = json.loads(descriptor.read_text()) if descriptor.exists() else {}
        existing = bool(identity) or any(vault.glob("*.ssrec")) or any(vault.glob("*.ssimg"))
        backend = identity.get("backend")
        key = None
        if fallback.exists() and backend != "credential-store":
            raw = fallback.read_bytes()
            key = base64.urlsafe_b64decode(raw.strip()) if encoded_file else raw
            backend = "private fallback key file"
        elif keyring is not None:
            try:
                encoded = keyring.get_password(service, identity.get("account", account))
                if encoded:
                    key = base64.urlsafe_b64decode(encoded)
                    backend = "credential-store"
            except Exception as error:
                if existing:
                    raise RuntimeError("Recall vault is locked: unlock the credential store and retry. No key was changed.") from error
        if key is None and existing:
            raise RuntimeError("Recall vault key is unavailable. Unlock the credential store or recover the original key; no replacement was created.")
        if key is None:
            key = os.urandom(32)
            # New vaults use a distinct account; legacy vaults retain 'default'.
            scoped = account + "-" + hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:24]
            if keyring is not None:
                try:
                    encoded = base64.urlsafe_b64encode(key).decode("ascii")
                    keyring.set_password(service, scoped, encoded)
                    if keyring.get_password(service, scoped) == encoded:
                        backend = "credential-store"
                        identity["account"] = scoped
                except Exception:
                    pass
            if backend != "credential-store":
                raw = base64.urlsafe_b64encode(key) if encoded_file else key
                fd = os.open(fallback, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "wb") as stream:
                    stream.write(raw); stream.flush(); os.fsync(stream.fileno())
                backend = "private fallback key file"
        if len(key) != 32:
            raise RuntimeError("Invalid Recall vault key; original data was left unchanged")
        fingerprint = hashlib.sha256(key).hexdigest()
        if identity.get("fingerprint", fingerprint) != fingerprint:
            raise RuntimeError("Recall vault key does not match its identity; original data was left unchanged")
        if not descriptor.exists():
            # Never pin a wrong credential-store key to legacy ciphertext.
            samples = [p for p in vault.glob("*.ssrec")
                       if p.is_file() and not p.is_symlink()]
            if samples:
                from cryptography.exceptions import InvalidTag
                from cryptography.hazmat.primitives.ciphers.aead import AESGCM
                verified = False
                for sample in samples[:32]:
                    if sample.stat().st_size > 4 * 1024 * 1024:
                        continue
                    raw = sample.read_bytes()
                    if not raw.startswith(b"SSRF1\0") or len(raw) < 34:
                        continue
                    try:
                        AESGCM(key).decrypt(raw[6:18], raw[18:], sample.name.encode())
                        verified = True
                        break
                    except InvalidTag:
                        continue
                if not verified:
                    raise RuntimeError("Existing Recall records do not authenticate with this key. Preserve keys/history and investigate corruption or the original credential store.")
            identity.update(backend=backend, fingerprint=fingerprint)
            fd = os.open(descriptor, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as stream:
                json.dump(identity, stream); stream.flush(); os.fsync(stream.fileno())
        return key, backend
