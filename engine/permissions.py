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

A user's features (#123) = their role's toggles + what their level unlocks (config.LEVEL_FEATURES),
then the owner's per-user overrides: a deny removes a feature, a grant adds one. Levels never unlock
NEVER_BY_LEVEL features: real trading, admin powers and Pro (the screener, #136) are only ever given
by the owner.
"""

from . import config, db

ROLES = ("owner", "sub_admin", "beta", "user")
TOGGLED_ROLES = ROLES[1:]
RANK = {"owner": 3, "sub_admin": 2, "beta": 1, "user": 1}

FEATURES = {
    "manage_users": "Admin page: approve, disable and reset passwords of lower-ranked accounts; activity log",
    "manage_roles": "Move lower-ranked accounts between Beta and User",
    "live_trading": "Connect a real broker and place real orders (manual confirm only)",
    "screener": "Pro: the screener and its stock analysis pages",
    "autotrade": "Auto-trade on the virtual account (needs the screener)",
    "market_calendar": "Market Calendar page (Level 3 unlock)",
    "saved_strategies": "Save strategies in the builder and open them again (Level 5 unlock)",
    "hedges": "Buy option legs on their own in the strategy builder (Level 6 unlock); without it a buy must protect a sell",
    "coin_store": "Coin store page: buy coin packs with real money, from Level 4 (payments not live yet, #175)",
}


NEVER_BY_LEVEL = frozenset({"live_trading", "manage_users", "manage_roles", "screener", "coin_store"})
# Features that mean nothing without another: auto-trade places the screen's picks.
NEEDS = {"autotrade": "screener"}


class Forbidden(ValueError):
    pass


def level_features(level: int) -> set[str]:
    """Features unlocked by reaching `level` (all levels up to it), minus anything a level may never
    grant and anything that doesn't exist yet."""
    got = {f for lv, fs in config.LEVEL_FEATURES.items() if lv <= level for f in fs}
    return {f for f in got if f in FEATURES and f not in NEVER_BY_LEVEL}


def user_features(user_id: int, role: str | None) -> list[str]:
    """Everything this user may use right now: role + level + owner overrides. Read on every
    request, so a level-up, toggle or override applies at once."""
    if role == "owner":
        return list(FEATURES)
    got = set(features_for(role))
    with db.tx(user_id) as c:  # user_levels is per-user (RLS)
        level = c.value("SELECT level FROM user_levels WHERE user_id=:u", u=user_id) or 1
    got |= level_features(level)
    got -= {f for f, lv in config.LEVEL_MIN.items() if level < lv}  # e.g. the coin store from Level 4
    with db.tx() as c:
        for o in c.all("SELECT feature, mode FROM user_feature_overrides WHERE user_id=:u", u=user_id):
            if o["feature"] in FEATURES:
                (got.add if o["mode"] == "grant" else got.discard)(o["feature"])
    got -= {f for f, need in NEEDS.items() if need not in got}
    return [f for f in FEATURES if f in got]


def user_allowed(user: dict | None, feature: str) -> bool:
    """`user` needs `id` and `role` (auth.active_user / ctx.user)."""
    if not user:
        return False
    if feature == "owner":
        return user["role"] == "owner"
    return feature in user_features(user["id"], user["role"])


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
    if not user_allowed(user, feature):
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


def overrides(user_id: int) -> list[dict]:
    """The owner's per-user overrides for one account."""
    with db.tx() as c:
        return c.all("SELECT feature, mode, set_at FROM user_feature_overrides WHERE user_id=:u ORDER BY feature",
                     u=user_id)


def set_override(owner_id: int, user_id: int, feature: str, mode: str, ip: str | None = None) -> list[dict]:
    """Grant or deny one feature for one user, or 'clear' to go back to role + level. Audited."""
    from . import auth
    if feature not in FEATURES:
        raise ValueError("Unknown feature")
    if mode not in ("grant", "deny", "clear"):
        raise ValueError("Mode must be grant, deny or clear")
    with db.tx() as c:
        role = c.value("SELECT role FROM users WHERE id=:u AND status <> 'unverified'", u=user_id)
        if role is None:
            raise ValueError("User not found")
        if role == "owner":
            raise ValueError("The owner always has every feature")
        if mode == "clear":
            c.run("DELETE FROM user_feature_overrides WHERE user_id=:u AND feature=:f", u=user_id, f=feature)
        else:
            c.run("INSERT INTO user_feature_overrides (user_id, feature, mode, set_by) VALUES (:u, :f, :m, :o) "
                  "ON CONFLICT (user_id, feature) DO UPDATE SET mode=EXCLUDED.mode, set_by=EXCLUDED.set_by, set_at=now()",
                  u=user_id, f=feature, m=mode, o=owner_id)
    auth.audit(f"override_{mode}", actor_id=owner_id, target_user_id=user_id, ip=ip, feature=feature)
    return overrides(user_id)
