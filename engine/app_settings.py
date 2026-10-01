"""Owner-managed app switches (issue #121), stored in `app_settings`.

Only the keys in SETTINGS exist; each has a type and a default used if its row is ever missing.
Read on every use, so a change applies at once.
"""

import json

from . import db

SETTINGS = {
    "auto_approve": (bool, True, "New accounts can use the app as soon as their email is confirmed. "
                                  "Off: they wait for approval on the Admin page."),
}


def get(key: str):
    kind, default, _ = SETTINGS[key]
    with db.tx() as c:
        v = c.value("SELECT value FROM app_settings WHERE key=:k", k=key)
    return default if v is None else kind(v)


def all_settings() -> list[dict]:
    """Every setting with its current value and description, for the owner's Admin tab."""
    return [{"key": k, "value": get(k), "label": label} for k, (_, _, label) in SETTINGS.items()]


def set_value(owner_id: int, key: str, value, ip: str | None = None) -> list[dict]:
    from . import auth  # auth imports this module
    if key not in SETTINGS:
        raise ValueError("Unknown setting")
    kind = SETTINGS[key][0]
    if type(value) is not kind:
        raise ValueError(f"{key} must be a {kind.__name__}")
    was = get(key)
    with db.tx() as c:
        c.run("INSERT INTO app_settings (key, value, updated_at, updated_by) VALUES (:k, CAST(:v AS jsonb), now(), :o) "
              "ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=now(), updated_by=:o",
              k=key, v=json.dumps(value), o=owner_id)
    if was != value:
        auth.audit("setting_changed", actor_id=owner_id, ip=ip, key=key, was=was, value=value)
    return all_settings()
