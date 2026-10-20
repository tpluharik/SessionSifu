#!/usr/bin/env python3
"""Signed portable metadata regressions; ephemeral test key, no network."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import unittest
from unittest import mock
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'portable'))
from sessionsifu_portable import update_trust


class UpdateTrustTests(unittest.TestCase):
    def test_authentication_lifetime_and_boundaries(self):
        key = Ed25519PrivateKey.generate()
        public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        now = datetime.now(timezone.utc)
        value = {'schema': 1, 'channel': 'stable', 'version': '3.5.35', 'artifacts': {},
                 'issued_at': now.isoformat(), 'expires_at': (now + timedelta(days=30)).isoformat()}
        def verify(change=None, signature=None, version='3.5.35'):
            raw = json.dumps({**value, **(change or {})}).encode()
            return update_trust.verify_release_index(raw, signature or key.sign(raw), version)
        with mock.patch.object(update_trust, 'PUBLIC_KEY', public):
            self.assertEqual(verify()['version'], '3.5.35')
            for change in [
                {'channel': 'testing'}, {'version': '3.5.34'}, {'schema': 2}, {'artifacts': []},
                {'expires_at': (now - timedelta(seconds=1)).isoformat()},
                {'issued_at': (now + timedelta(days=2)).isoformat()},
                {'expires_at': (now + timedelta(days=100)).isoformat()},
                {'issued_at': '2026-01-01T00:00:00'},
            ]:
                with self.assertRaises((ValueError, TypeError)):
                    verify(change)
            with self.assertRaisesRegex(ValueError, 'signature'):
                verify(signature=b'0' * 64)
            with self.assertRaisesRegex(ValueError, 'size'):
                update_trust.verify_release_index(b'x' * (256 * 1024 + 1), b'0' * 64, '3.5.35')


if __name__ == '__main__':
    unittest.main()
