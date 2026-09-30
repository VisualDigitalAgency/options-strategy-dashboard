import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { rpc } from './rpc'

const AuthContext = createContext(null)

const THEME_KEY = 'options-screener-theme'
const PALETTE_KEY = 'options-screener-palette'

/** Puts the account's saved theme and palette on the page, so they follow the user across devices. */
function applyPrefs(prefs) {
  const root = document.documentElement
  if (prefs?.theme) {
    root.dataset.theme = prefs.theme
    try { localStorage.setItem(THEME_KEY, prefs.theme) } catch { /* storage blocked */ }
  }
  if (prefs?.palette) {
    root.dataset.palette = prefs.palette
    try { localStorage.setItem(PALETTE_KEY, prefs.palette) } catch { /* storage blocked */ }
  }
}

/** Saves a theme or palette change to the account. Best effort: the page already shows it. */
export function savePref(pref) {
  rpc('prefs_set', pref).catch(() => {})
}

export function AuthProvider({ children }) {
  const [user, setUser] = useState(undefined) // undefined: still checking; null: signed out

  const refresh = useCallback(async () => {
    try {
      const me = await rpc('auth_me')
      if (me) applyPrefs(me.prefs)
      setUser(me)
    } catch {
      setUser((u) => (u === undefined ? null : u))
    }
  }, [])

  useEffect(() => {
    refresh()
    const onChange = () => refresh()
    window.addEventListener('auth:changed', onChange)
    return () => window.removeEventListener('auth:changed', onChange)
  }, [refresh])

  const login = async (email, password) => {
    const me = await rpc('auth_login', { email, password })
    applyPrefs(me.prefs)
    setUser(me)
    return me
  }
  const logout = async () => {
    try { await rpc('auth_logout') } finally { setUser(null) }
  }
  const changePassword = async (current_password, new_password) => {
    const me = await rpc('auth_change_password', { current_password, new_password })
    setUser(me)
    return me
  }

  return (
    <AuthContext.Provider value={{ user, login, logout, changePassword, refresh }}>{children}</AuthContext.Provider>
  )
}

export const useAuth = () => useContext(AuthContext)

/** Whether the signed-in user's role has a feature (engine/permissions.py). The server enforces the
 * same list; this only hides what would be refused. Read at sign-in and on reload. */
export const can = (user, feature) => Boolean(user?.features?.includes(feature))
export const useCan = (feature) => can(useAuth().user, feature)
