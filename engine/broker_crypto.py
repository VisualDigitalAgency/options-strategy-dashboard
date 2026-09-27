"""Encryption at rest for real broker credentials (phase 1: Zerodha access/public tokens).

Nothing in the app encrypts a reversible secret before this: password hashes are one-way
(Argon2id) and session tokens are only ever stored as a SHA-256 hash. A broker access token
must be decrypted and reused to call the broker, so it needs real symmetric encryption instead.

The key comes from settings.secret("BROKER_ENC_KEY"), the same *_FILE-or-env-var mechanism
already used for the DB and Redis passwords: a Docker secret file in production, a plain env
var in dev. Generate one with `Fernet.generate_key()` and never commit it.

Rotation window: set BROKER_ENC_KEY to the new key and BROKER_ENC_KEY_PREVIOUS to the old one.
New tokens are encrypted with the new key only; stored ones decrypt with either, so nobody has
to reconnect while scripts/rotate_broker_key.py re-encrypts the rows. Unset the previous key
once the script reports nothing left on it.
"""

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from . import settings

_fernet: MultiFernet | None = None


def _get() -> MultiFernet:
    global _fernet
    if _fernet is None:
        key = settings.secret("BROKER_ENC_KEY")
        if not key:
            raise RuntimeError(
                "BROKER_ENC_KEY (or BROKER_ENC_KEY_FILE) is not set; broker credentials can't be "
                "encrypted. Generate one with Fernet.generate_key() and keep it out of git.")
        previous = settings.secret("BROKER_ENC_KEY_PREVIOUS")
        keys = [key, previous] if previous else [key]
        # MultiFernet encrypts with the first key and tries each in order to decrypt.
        _fernet = MultiFernet([Fernet(k.encode() if isinstance(k, str) else k) for k in keys])
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
