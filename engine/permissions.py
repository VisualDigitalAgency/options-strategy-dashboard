"""Roles and owner-managed feature toggles (issue #46).

Hierarchy: owner (exactly one) > sub_admin > beta, user. The owner has every feature, always, and
is the only one who can edit the toggles or make someone a sub-admin; nobody can be made owner.
Which features the other roles have lives in the `role_features` table, edited from the admin
page. The list of features is fixed here, because each one needs a check in code to mean anything.

Hard rules that no toggle overrides:
- the owner keeps every feature and can't be demoted or managed by anyone;
- only the owner changes the toggles or grants/removes sub-admin;
- a role manager only acts on accounts ranked below their own;
- auto-trade stays on the virtual account (engine/autotrade.py never calls a broker).
"""

from . import db

ROLES = ("owner", "sub_admin", "beta", "user")
TOGGLED_ROLES = ROLES[1:]
RANK = {"owner": 3, "sub_admin": 2, "beta": 1, "user": 1}

FEATURES = {
    "manage_users": "Admin page: approve, disable and reset passwords of lower-ranked accounts; activity log",
    "manage_roles": "Move lower-ranked accounts between Beta and User",
    "live_trading": "Connect a real broker and place real orders (manual confirm only)",
    "autotrade": "Auto-trade on the virtual account",
    "market_calendar": "Market Calendar page",
}


class Forbidden(ValueError):
    pass


def features_for(role: str | None) -> list[str]:
    """The features a role has right now. Read on every request, so a toggle applies at once."""
    if role == "owner":
        return list(FEATURES)
    if role not in TOGGLED_ROLES:
        return []
    with db.tx() as c:
        rows = c.all("SELECT feature FROM role_features WHERE role=:r AND enabled", r=role)
    return [r["feature"] for r in rows if r["feature"] in FEATURES]


def allowed(role: str | None, feature: str) -> bool:
    if feature == "owner":
        return role == "owner"
    return feature in features_for(role)


def require(user: dict | None, feature: str) -> None:
    if not user or not allowed(user["role"], feature):
        raise Forbidden("You don't have access to this")


def outranks(actor_role: str, target_role: str) -> bool:
    return RANK.get(actor_role, 0) > RANK.get(target_role, 0)


def matrix() -> dict:
    """Every toggled role's features, for the owner's editor."""
    with db.tx() as c:
        rows = c.all("SELECT role, feature, enabled FROM role_features")
    out = {r: {f: False for f in FEATURES} for r in TOGGLED_ROLES}
    for r in rows:
        if r["role"] in out and r["feature"] in FEATURES:
            out[r["role"]][r["feature"]] = r["enabled"]
    return {"roles": list(TOGGLED_ROLES), "features": [{"key": k, "label": v} for k, v in FEATURES.items()],
            "matrix": out}


def set_feature(owner_id: int, role: str, feature: str, enabled: bool, ip: str | None = None) -> dict:
    from . import auth  # auth imports this module
    if role not in TOGGLED_ROLES:
        raise ValueError("The owner always has every feature")
    if feature not in FEATURES:
        raise ValueError("Unknown feature")
    with db.tx() as c:
        was = c.value("SELECT enabled FROM role_features WHERE role=:r AND feature=:f", r=role, f=feature)
        if was is None:
            raise ValueError("Unknown feature")
        c.run("UPDATE role_features SET enabled=:e, updated_at=now(), updated_by=:o WHERE role=:r AND feature=:f",
              e=enabled, o=owner_id, r=role, f=feature)
    if was != enabled:
        auth.audit("feature_on" if enabled else "feature_off", actor_id=owner_id, ip=ip, role=role, feature=feature)
    return matrix()
