"""auth/key_validator.py

Validates RSA-signed deployment keys using the embedded public key.

A deployment key is a base64url-encoded RSA signature over a JSON payload,
separated by a dot:

    <base64url(signature)>.<base64url(payload)>

where payload is:
    {"org": "Acme Corp", "issued_at": "2026-03-17", "expires_at": "2027-03-17"}

The public key is embedded in auth/public_key.pem (safe to distribute).
The private key is never included in deployments — only the key issuer holds it.

Public API
----------
validate_deployment_key(key: str) -> tuple[bool, str]
    Returns (is_valid, message).
"""

import base64
import json
import datetime
from pathlib import Path

try:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.exceptions import InvalidSignature
    _CRYPTO_AVAILABLE = True
except ImportError:
    _CRYPTO_AVAILABLE = False

_PUBLIC_KEY_PATH = Path(__file__).parent / "public_key.pem"


def _load_public_key():
    pem = _PUBLIC_KEY_PATH.read_bytes()
    return serialization.load_pem_public_key(pem)


def _verify_with_public_key_pem(key: str, public_key_pem: bytes) -> tuple:
    """Validate a deployment key using an explicitly supplied public key PEM.

    This variant is used by the test suite so tests can inject a throwaway key
    pair without touching the real auth/public_key.pem file.

    Parameters
    ----------
    key : str
        Deployment key string as issued by keygen.py.
    public_key_pem : bytes
        PEM-encoded public key bytes to use for verification.

    Returns
    -------
    tuple[bool, str]
        (True, org_name) on success, (False, error_message) on failure.
    """
    if not key or not key.strip():
        return False, "No deployment key provided."

    if not _CRYPTO_AVAILABLE:
        return False, "cryptography package is not installed."

    try:
        parts = key.strip().split(".")
        if len(parts) != 2:
            return False, "Invalid key format."
        signature = base64.urlsafe_b64decode(parts[0] + "==")
        payload_bytes = base64.urlsafe_b64decode(parts[1] + "==")
    except Exception:
        return False, "Key could not be decoded."

    try:
        public_key = serialization.load_pem_public_key(public_key_pem)
        public_key.verify(signature, payload_bytes, padding.PKCS1v15(), hashes.SHA256())
    except InvalidSignature:
        return False, "Deployment key signature is invalid."
    except Exception as e:
        return False, f"Key validation error: {e}"

    try:
        payload = json.loads(payload_bytes.decode())
    except Exception:
        return False, "Key payload could not be parsed."

    expires_at = payload.get("expires_at")
    if expires_at:
        try:
            expiry = datetime.date.fromisoformat(expires_at)
            if datetime.date.today() > expiry:
                return False, f"Deployment key expired on {expires_at}."
        except ValueError:
            pass

    org = payload.get("org")
    if not org:
        return False, "Key payload is missing the 'org' field."
    return True, org


def validate_deployment_key(key: str) -> tuple:
    """Validate a deployment key.

    Parameters
    ----------
    key : str
        Deployment key string as issued by keygen.py.

    Returns
    -------
    tuple[bool, str]
        (True, org_name) on success.
        (False, error_message) on failure.
    """
    if not key or not key.strip():
        return False, "No deployment key provided."

    if not _CRYPTO_AVAILABLE:
        return False, "cryptography package is not installed. Run: pip install cryptography"

    if not _PUBLIC_KEY_PATH.exists():
        return False, "Public key file not found. Ensure auth/public_key.pem is present."

    try:
        parts = key.strip().split(".")
        if len(parts) != 2:
            return False, "Invalid key format."

        signature = base64.urlsafe_b64decode(parts[0] + "==")
        payload_bytes = base64.urlsafe_b64decode(parts[1] + "==")
    except Exception:
        return False, "Key could not be decoded. Ensure the key was copied correctly."

    try:
        public_key = _load_public_key()
        public_key.verify(signature, payload_bytes, padding.PKCS1v15(), hashes.SHA256())
    except InvalidSignature:
        return False, "Deployment key signature is invalid. Contact the issuer for a valid key."
    except Exception as e:
        return False, f"Key validation error: {e}"

    try:
        payload = json.loads(payload_bytes.decode())
    except Exception:
        return False, "Key payload could not be parsed."

    # Check expiry if present
    expires_at = payload.get("expires_at")
    if expires_at:
        try:
            expiry = datetime.date.fromisoformat(expires_at)
            if datetime.date.today() > expiry:
                return False, f"Deployment key expired on {expires_at}. Contact the issuer to renew."
        except ValueError:
            pass  # Malformed date — treat as no expiry

    org = payload.get("org", "Unknown organisation")
    return True, org
