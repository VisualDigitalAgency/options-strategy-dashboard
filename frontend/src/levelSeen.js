// The last level this browser celebrated (issue #126). Drives the nav badge and the level-up screen.
const KEY = 'theta-seen-level'

/** null when nothing is recorded yet (new browser, or storage blocked). */
export function seenLevel() {
  try { const v = Number(localStorage.getItem(KEY)); return v > 0 ? v : null } catch { return null }
}

export function markSeen(level) {
  try { localStorage.setItem(KEY, String(level)) } catch { /* storage blocked */ }
}
