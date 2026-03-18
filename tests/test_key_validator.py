"""tests/test_key_validator.py

Unit tests for auth/key_validator.py — RSA deployment key validation.

Tests are self-contained: they generate a fresh throwaway RSA key pair so they
never depend on the real auth/private_key.pem being present.

Requires: cryptography package.  Tests are skipped gracefully if not installed.
"""

import base64
import datetime
import json
import sys
import unittest
from typing import Optional

try:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
    _crypto_available = True
except ImportError:
    _crypto_available = False


def _generate_test_key_pair():
    """Return (private_key, public_key_pem_bytes) for a throwaway 2048-bit pair."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private_key, public_pem


def _build_key(private_key, org: str, days: Optional[int] = 365, issued_offset: int = 0) -> str:
    """Build a signed deployment key string using the given private key."""
    today = datetime.date.today() + datetime.timedelta(days=issued_offset)
    payload = {
        "org": org,
        "issued_at": today.isoformat(),
        "expires_at": (today + datetime.timedelta(days=days)).isoformat() if days is not None else None,
    }
    payload_bytes = json.dumps(payload, separators=(",", ":")).encode()
    signature = private_key.sign(payload_bytes, padding.PKCS1v15(), hashes.SHA256())

    def _b64(b: bytes) -> str:
        return base64.urlsafe_b64encode(b).decode().rstrip("=")

    return _b64(signature) + "." + _b64(payload_bytes)


@unittest.skipUnless(_crypto_available, "cryptography package not installed")
class TestKeyValidator(unittest.TestCase):
    """Integration-style tests using a throwaway key pair."""

    @classmethod
    def setUpClass(cls):
        cls.private_key, cls.public_pem = _generate_test_key_pair()

    def _validator(self):
        """Return a validate function bound to the test public key."""
        from auth.key_validator import _verify_with_public_key_pem
        return lambda key: _verify_with_public_key_pem(key, self.public_pem)

    def test_valid_key_returns_true(self):
        key = _build_key(self.private_key, "Test Org", days=365)
        valid, msg = self._validator()(key)
        self.assertTrue(valid)
        self.assertEqual(msg, "Test Org")

    def test_org_name_returned_in_message(self):
        key = _build_key(self.private_key, "Acme Corp", days=30)
        valid, msg = self._validator()(key)
        self.assertTrue(valid)
        self.assertEqual(msg, "Acme Corp")

    def test_no_expiry_key_is_valid(self):
        key = _build_key(self.private_key, "Unlimited Org", days=None)
        valid, msg = self._validator()(key)
        self.assertTrue(valid)

    def test_future_expiry_is_valid(self):
        key = _build_key(self.private_key, "Future Org", days=1)
        valid, msg = self._validator()(key)
        self.assertTrue(valid)

    def test_expired_key_returns_false(self):
        # Issued 400 days ago, 365-day validity → expired 35 days ago
        key = _build_key(self.private_key, "Old Org", days=365, issued_offset=-400)
        valid, msg = self._validator()(key)
        self.assertFalse(valid)
        self.assertIn("expired", msg.lower())

    def test_tampered_payload_returns_false(self):
        key = _build_key(self.private_key, "Legit Org", days=365)
        sig_part, payload_part = key.split(".")
        # Replace org in payload
        payload = json.loads(base64.urlsafe_b64decode(payload_part + "=="))
        payload["org"] = "Hacker Org"
        bad_payload = base64.urlsafe_b64encode(
            json.dumps(payload, separators=(",", ":")).encode()
        ).decode().rstrip("=")
        tampered_key = sig_part + "." + bad_payload
        valid, msg = self._validator()(tampered_key)
        self.assertFalse(valid)

    def test_wrong_key_returns_false(self):
        other_private, _ = _generate_test_key_pair()
        key = _build_key(other_private, "Wrong Key Org", days=365)
        valid, msg = self._validator()(key)
        self.assertFalse(valid)

    def test_empty_string_returns_false(self):
        from auth.key_validator import _verify_with_public_key_pem
        valid, msg = _verify_with_public_key_pem("", self.public_pem)
        self.assertFalse(valid)

    def test_missing_dot_separator_returns_false(self):
        from auth.key_validator import _verify_with_public_key_pem
        valid, msg = _verify_with_public_key_pem("nodotinhere", self.public_pem)
        self.assertFalse(valid)

    def test_garbage_input_returns_false(self):
        from auth.key_validator import _verify_with_public_key_pem
        valid, msg = _verify_with_public_key_pem("!!!.###", self.public_pem)
        self.assertFalse(valid)

    def test_missing_org_field_returns_false(self):
        payload = {"issued_at": datetime.date.today().isoformat(), "expires_at": None}
        payload_bytes = json.dumps(payload, separators=(",", ":")).encode()
        signature = self.private_key.sign(payload_bytes, padding.PKCS1v15(), hashes.SHA256())
        key = (
            base64.urlsafe_b64encode(signature).decode().rstrip("=")
            + "."
            + base64.urlsafe_b64encode(payload_bytes).decode().rstrip("=")
        )
        valid, msg = self._validator()(key)
        self.assertFalse(valid)


if __name__ == "__main__":
    unittest.main()
