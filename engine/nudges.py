"""Day-before email nudges (retention plan, phase 1).

Once a day (worker, from config.NUDGE_HOUR_IST) each active user with open legs gets at most one
email listing what happens tomorrow: a stop-loss that arms (positions.sl_activates_on) or a leg the
time exit will close (virtual.time_exit_date). Users turn it off with the email_nudges preference.
A Redis key per user and day stops a second email when the worker restarts.
"""

import logging
from datetime import date, timedelta

from . import cache, db, mail, users, virtual

log = logging.getLogger("theta.nudges")


def items(user_id: int, tomorrow: date) -> list[str]:
    """One line per open leg with something happening `tomorrow`; empty when there is nothing."""
    with db.tx(user_id) as c:
        if c.value("SELECT email_nudges FROM user_prefs WHERE user_id=:u", u=user_id) is False:
            return []
        legs = c.all("SELECT symbol, expiry, side, strike, qty, sl_mode, sl_activates_on FROM positions "
                     "WHERE user_id=:u AND status='open' ORDER BY symbol, expiry, side, strike", u=user_id)
    out = []
    for p in legs:
        name = f"{p['symbol']} {p['expiry']} {float(p['strike']):g} {p['side']}"
        if p["qty"] < 0 and p["sl_mode"] != "off" and str(p["sl_activates_on"]) == str(tomorrow):
            out.append(f"{name}: the stop-loss arms tomorrow")
        if virtual.time_exit_date(str(p["expiry"])) == str(tomorrow):
            out.append(f"{name}: the time exit closes it tomorrow")
    return out


def send_all(today: date) -> int:
    """Emails everyone with something happening tomorrow. Returns how many were sent."""
    sent = 0
    for uid in users.active_user_ids():
        key = f"nudge:{uid}:{today}"
        if cache.exists(key):
            continue
        lines = items(uid, today + timedelta(days=1))
        if not lines:
            continue
        with db.tx() as c:
            u = c.one("SELECT email, name FROM users WHERE id=:u", u=uid)
        body = "\n".join([f"Hi {u['name']},", "", "Tomorrow on your virtual account:", "",
                          *(f"- {line}" for line in lines), "",
                          "Open Portfolio to review them. Turn these emails off on My progress.",
                          "", "Paper trading, educational."])
        try:
            mail.send(u["email"], "Tomorrow on your virtual account", body)
            cache.set_json(key, 1, ttl=2 * 86400)
            sent += 1
        except Exception:
            log.exception("nudge email to user %s failed", uid)
    return sent
