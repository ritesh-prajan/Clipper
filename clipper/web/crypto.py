"""Fernet encryption for API key storage at rest.

The encryption key is loaded from env var CLIPPER_SECRET_KEY (base64url-encoded
32-byte Fernet key).  If absent, a fresh key is generated and saved to
.clipper_keyfile in the working directory.  This file must be in .gitignore.
"""

import base64
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger("clipper.web.crypto")

_KEY_FILE = Path(".clipper_keyfile")
_ENV_KEY = "CLIPPER_SECRET_KEY"

_fernet: Optional[object] = None  # lazy init


def _get_fernet():
    global _fernet
    if _fernet is not None:
        return _fernet

    try:
        from cryptography.fernet import Fernet
    except ImportError as exc:
        raise RuntimeError(
            "cryptography package is required for key encryption. "
            "Run: pip install cryptography"
        ) from exc

    raw_key = os.environ.get(_ENV_KEY)
    if raw_key:
        key = raw_key.encode()
    elif _KEY_FILE.exists():
        key = _KEY_FILE.read_bytes().strip()
    else:
        key = Fernet.generate_key()
        _KEY_FILE.write_bytes(key)
        # Restrict permissions (best-effort on Windows)
        try:
            os.chmod(_KEY_FILE, 0o600)
        except OSError:
            pass
        logger.info("Generated new Fernet key and saved to %s", _KEY_FILE)

    _fernet = Fernet(key)
    return _fernet


def encrypt_key(plaintext: str) -> str:
    """Encrypt a secret string to a URL-safe base64 ciphertext."""
    f = _get_fernet()
    return f.encrypt(plaintext.encode()).decode()


def decrypt_key(ciphertext: str) -> str:
    """Decrypt a ciphertext string back to plaintext."""
    f = _get_fernet()
    return f.decrypt(ciphertext.encode()).decode()


def mask_key(plaintext: str) -> str:
    """Return a masked representation: '••••••••{last4}'."""
    if not plaintext:
        return "••••••••"
    tail = plaintext[-4:] if len(plaintext) >= 4 else plaintext
    return f"••••••••{tail}"
