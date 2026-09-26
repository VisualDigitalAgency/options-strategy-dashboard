"""Encryption at rest for real broker credentials (phase 1: Zerodha access/public tokens).

Nothing in the app encrypts a reversible secret before this: password hashes are one-way
(Argon2id) and session tokens are only ever stored as a SHA-256 hash. A broker access token
must be decrypted and reused to call the broker, so it needs real symmetric encryption instead.

The key comes from settings.secret("BROKER_ENC_KEY"), the same *_FILE-or-env-var mechanism
already used for the DB and Redis passwords: a Docker secret file in production, a plain env
var in dev. Generate one with `Fernet.generate_key()` and never commit it.
"""

from cryptography.fernet import Fernet, InvalidToken

from . import settings

_fernet: Fernet | None = None


def _get() -> Fernet:
    global _fernet
    if _fernet is None:
        key = settings.secret("BROKER_ENC_KEY")
        if not key:
            raise RuntimeError(
                "BROKER_ENC_KEY (or BROKER_ENC_KEY_FILE) is not set; broker credentials can't be "
                "encrypted. Generate one with Fernet.generate_key() and keep it out of git.")
        _fernet = Fernet(key.encode() if isinstance(key, str) else key)
    return _fernet


def encrypt(plaintext: str) -> bytes:
    return _get().encrypt(plaintext.encode())


def decrypt(ciphertext: bytes) -> str:
    try:
        return _get().decrypt(bytes(ciphertext)).decode()
    except InvalidToken as e:
        # Never surfaces the ciphertext or key; only that decryption failed (wrong/rotated key,
        # or corrupted row) so the caller can tell the user to reconnect rather than crash oddly.
        raise ValueError("Stored broker credentials could not be read; please reconnect the broker") from e
