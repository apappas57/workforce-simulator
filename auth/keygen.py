#!/usr/bin/env python3
"""auth/keygen.py — Deployment key generator.

Run this script to issue a signed deployment key for a new installation.
Requires auth/private_key.pem — NEVER commit or share this file.

Usage:
    python auth/keygen.py --org "Acme Corp"
    python auth/keygen.py --org "Acme Corp" --days 365
    python auth/keygen.py --org "Acme Corp" --no-expiry

The generated key is printed to stdout. Send it to the recipient securely.
"""

import argparse
import base64
import datetime
import json
import sys
from pathlib import Path
from typing import Optional

try:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
except ImportError:
    print("ERROR: cryptography package required. Run: pip install cryptography")
    sys.exit(1)

_PRIVATE_KEY_PATH = Path(__file__).parent / "private_key.pem"


def generate_key(org: str, days: Optional[int] = 365) -> str:
    """Generate a signed deployment key for the given organisation.

    Parameters
    ----------
    org : str
        Organisation name embedded in the key payload.
    days : int or None
        Key validity in days from today. None = no expiry.

    Returns
    -------
    str
        Deployment key string to send to the recipient.
    """
    if not _PRIVATE_KEY_PATH.exists():
        print(f"ERROR: Private key not found at {_PRIVATE_KEY_PATH}")
        print("Keep auth/private_key.pem in a secure location and never commit it.")
        sys.exit(1)

    pem = _PRIVATE_KEY_PATH.read_bytes()
    private_key = serialization.load_pem_private_key(pem, password=None)

    payload = {
        "org": org,
        "issued_at": datetime.date.today().isoformat(),
        "expires_at": (datetime.date.today() + datetime.timedelta(days=days)).isoformat() if days else None,
    }
    payload_bytes = json.dumps(payload, separators=(",", ":")).encode()

    signature = private_key.sign(payload_bytes, padding.PKCS1v15(), hashes.SHA256())

    key = (
        base64.urlsafe_b64encode(signature).decode().rstrip("=")
        + "."
        + base64.urlsafe_b64encode(payload_bytes).decode().rstrip("=")
    )
    return key


def main():
    parser = argparse.ArgumentParser(description="Generate a deployment key for the Workforce Simulator.")
    parser.add_argument("--org", required=True, help="Organisation name (e.g. 'Acme Corp')")
    parser.add_argument("--days", type=int, default=365, help="Key validity in days (default: 365)")
    parser.add_argument("--no-expiry", action="store_true", help="Issue a key with no expiry date")
    args = parser.parse_args()

    days = None if args.no_expiry else args.days
    key = generate_key(args.org, days)

    expiry_msg = "no expiry" if days is None else f"expires {(datetime.date.today() + datetime.timedelta(days=days)).isoformat()}"
    print(f"\nDeployment key for: {args.org} ({expiry_msg})\n")
    print(key)
    print("\nSend this key to the recipient. They set it as DEPLOYMENT_KEY in their .env file.\n")


if __name__ == "__main__":
    main()
