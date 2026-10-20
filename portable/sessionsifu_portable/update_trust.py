"""Offline signature and lifetime verification; used only during updates."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from cryptography.hazmat.primitives.serialization import load_pem_public_key
from cryptography.exceptions import InvalidSignature

PUBLIC_KEY = b"""-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEAEnakL3ds5kGLSASytcdZ2mTmBY7A1R298zO/L5843gY=
-----END PUBLIC KEY-----
"""

def verify_release_index(payload: bytes, signature: bytes, version: str) -> dict:
    if not payload or len(payload) > 256 * 1024 or len(signature) != 64:
        raise ValueError('Signed release manifest has an invalid size')
    try:
        load_pem_public_key(PUBLIC_KEY).verify(signature, payload)
    except InvalidSignature as error:
        raise ValueError('Release manifest signature verification failed') from error
    value = json.loads(payload)
    now = datetime.now(timezone.utc)
    issued = datetime.fromisoformat(value['issued_at'].replace('Z', '+00:00'))
    expires = datetime.fromisoformat(value['expires_at'].replace('Z', '+00:00'))
    if (value.get('schema') != 1 or value.get('channel') != 'stable' or value.get('version') != version or
            issued.tzinfo is None or expires.tzinfo is None or issued > now + timedelta(hours=24) or
            expires <= now or expires <= issued or expires - issued > timedelta(days=90)):
        raise ValueError('Release manifest version or lifetime is invalid')
    if not isinstance(value.get('artifacts'), dict):
        raise ValueError('Release manifest artifact inventory is invalid')
    return value
