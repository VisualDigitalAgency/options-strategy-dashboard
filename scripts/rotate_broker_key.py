"""Re-encrypts every stored broker token under a new BROKER_ENC_KEY.

    BROKER_ENC_KEY=<new> BROKER_ENC_KEY_PREVIOUS=<old> python scripts/rotate_broker_key.py [--dry-run]

Both keys come from settings.secret(), so BROKER_ENC_KEY_FILE / BROKER_ENC_KEY_PREVIOUS_FILE
work too. Every broker_connections row (any status) has access_token_enc and public_token_enc
decrypted with whichever key still opens it and re-encrypted with the new one. Rows already on
the new key are left alone, so the script is safe to run again after a partial run.

A row neither key can open is reported by id and left untouched; that user has to reconnect.
The exit code is non-zero if any such row exists, so a deploy step can stop before the old
key is thrown away.

Order, with no downtime: deploy api and worker with the new BROKER_ENC_KEY and the old key as
BROKER_ENC_KEY_PREVIOUS (engine/broker_crypto.py reads with either), run this, then redeploy
without BROKER_ENC_KEY_PREVIOUS.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cryptography.fernet import Fernet, InvalidToken, MultiFernet  # noqa: E402

from engine import db, settings  # noqa: E402


def _key(name: str) -> Fernet:
    key = settings.secret(name)
    if not key:
        sys.exit(f"{name} (or {name}_FILE) is not set.")
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except ValueError:
        sys.exit(f"{name} is not a valid Fernet key.")


def rotate(new: Fernet, old: Fernet, dry_run: bool = False) -> dict:
    """Returns counts: rotated, current (already on the new key), unreadable (list of row ids)."""
    both = MultiFernet([new, old])
    out = {"rotated": 0, "current": 0, "unreadable": []}
    with db.tx() as c:
        user_ids = [r["id"] for r in c.all("SELECT id FROM users ORDER BY id")]
    for uid in user_ids:
        # broker_connections is under RLS, so each user's rows are reached through their own tx.
        with db.tx(uid) as c:
            rows = c.all("SELECT id, access_token_enc, public_token_enc FROM broker_connections "
                         "WHERE user_id=:u ORDER BY id FOR UPDATE", u=uid)
            for row in rows:
                cols = {k: bytes(row[k]) for k in ("access_token_enc", "public_token_enc") if row[k] is not None}
                try:
                    for v in cols.values():
                        new.decrypt(v)
                    out["current"] += 1
                    continue
                except InvalidToken:
                    pass
                try:
                    fresh = {k: both.rotate(v) for k, v in cols.items()}
                except InvalidToken:
                    out["unreadable"].append(row["id"])
                    continue
                if not dry_run:
                    c.run("UPDATE broker_connections SET access_token_enc=:at, "
                          "public_token_enc=COALESCE(:pt, public_token_enc) WHERE id=:id",
                          at=fresh["access_token_enc"], pt=fresh.get("public_token_enc"), id=row["id"])
                out["rotated"] += 1
    return out


def main() -> int:
    p = argparse.ArgumentParser(description="Re-encrypt broker tokens under a new BROKER_ENC_KEY.")
    p.add_argument("--dry-run", action="store_true", help="count what would change, write nothing")
    args = p.parse_args()
    new, old = _key("BROKER_ENC_KEY"), _key("BROKER_ENC_KEY_PREVIOUS")
    r = rotate(new, old, args.dry_run)
    verb = "Would re-encrypt" if args.dry_run else "Re-encrypted"
    print(f"{verb} {r['rotated']} connection(s); {r['current']} already on the new key.")
    if r["unreadable"]:
        print(f"{len(r['unreadable'])} connection(s) open with neither key, left as is "
              f"(those users must reconnect): ids {r['unreadable']}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
