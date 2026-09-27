"""scripts/rotate_broker_key.py: re-encrypts every broker_connections row under the new key,
leaves rows already on it alone, and reports (without touching) rows neither key opens."""
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography.fernet import Fernet

from engine import db, users

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import rotate_broker_key  # noqa: E402

fails = []


def check(name, cond, got=""):
    print(("PASS " if cond else "FAIL ") + name, "->", got)
    if not cond:
        fails.append(name)


old, new, stray = Fernet(Fernet.generate_key()), Fernet(Fernet.generate_key()), Fernet(Fernet.generate_key())
expires = datetime.now(timezone.utc) + timedelta(hours=8)


def add(uid, key, token, public=None, status="active"):
    with db.tx(uid) as c:
        return c.value("INSERT INTO broker_connections (user_id, broker, status, access_token_enc, public_token_enc, "
                       "token_expires_at) VALUES (:u, 'zerodha', :s, :at, :pt, :e) RETURNING id",
                       u=uid, s=status, at=key.encrypt(token.encode()),
                       pt=key.encrypt(public.encode()) if public else None, e=expires)


def tokens(uid, rid):
    with db.tx(uid) as c:
        r = c.one("SELECT access_token_enc, public_token_enc FROM broker_connections WHERE id=:i", i=rid)
    return bytes(r["access_token_enc"]), r["public_token_enc"] and bytes(r["public_token_enc"])


a = users.create_user("a@test.example", "A", status="active")
b = users.create_user("b@test.example", "B", status="active")
ra = add(a, old, "tok-a", "pub-a")
rb_old = add(b, old, "tok-b-old", status="disconnected")
rb_new = add(b, new, "tok-b-new")
before_new = tokens(b, rb_new)

r = rotate_broker_key.rotate(new, old, dry_run=True)
check("dry run counts old-key rows", r == {"rotated": 2, "current": 1, "unreadable": []}, r)
check("dry run writes nothing", old.decrypt(tokens(a, ra)[0]) == b"tok-a")

r = rotate_broker_key.rotate(new, old)
check("rotates both old-key rows (any status)", r == {"rotated": 2, "current": 1, "unreadable": []}, r)
at, pt = tokens(a, ra)
check("access token now opens with new key", new.decrypt(at) == b"tok-a")
check("public token now opens with new key", new.decrypt(pt) == b"pub-a")
at, pt = tokens(b, rb_old)
check("row without public token rotates, public stays null", new.decrypt(at) == b"tok-b-old" and pt is None, pt)
check("row already on new key is untouched", tokens(b, rb_new) == before_new)

r = rotate_broker_key.rotate(new, old)
check("second run is a no-op", r == {"rotated": 0, "current": 3, "unreadable": []}, r)

rs = add(a, stray, "tok-stray", status="expired")
stray_before = tokens(a, rs)
r = rotate_broker_key.rotate(new, old)
check("unreadable row is reported", r["unreadable"] == [rs], r)
check("unreadable row is left as is", tokens(a, rs) == stray_before)

# CLI: refuses to run unless both keys are set.
p = subprocess.run([sys.executable, "scripts/rotate_broker_key.py", "--dry-run"], cwd=ROOT,
                   env={**os.environ, "BROKER_ENC_KEY_PREVIOUS": ""}, capture_output=True, text=True)
check("CLI refuses without a previous key", p.returncode != 0 and "BROKER_ENC_KEY_PREVIOUS" in (p.stdout + p.stderr), p.stderr)

sys.exit(1 if fails else 0)
