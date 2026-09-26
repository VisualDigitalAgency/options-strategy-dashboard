import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import { rpc } from './rpc'

const KEY = 'options-screener-settings'
const POLL_MS = 30000
const BudgetContext = createContext(null)

function readPct() {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) || '{}').maxPct
    return typeof v === 'number' && v > 0 ? v : 10
  } catch {
    return 10
  }
}

/**
 * One source of truth for trading capital: the virtual account.
 * Capital = account value; per-trade budget = min(capital x max %, free funds).
 * Max % per trade lives on the backend with the auto-trade settings, so manual lot
 * suggestions and auto-trade sizing always use the same limit.
 */
export function SettingsProvider({ children }) {
  const [maxPct, setMaxPctLocal] = useState(readPct)
  const [account, setAccount] = useState(null)
  const [auto, setAuto] = useState(null)
  const [error, setError] = useState(null)
  const timer = useRef(null)
  const pctTimer = useRef(null)
  const alive = useRef(false) // see screen.jsx: no re-arming the poll after unmount

  const refresh = useCallback(async () => {
    clearTimeout(timer.current)
    try {
      const [a, s] = await Promise.all([rpc('va_get_account'), rpc('va_get_autotrade')])
      setAccount(a)
      setAuto(s)
      setError(null)
    } catch (e) {
      setError(e.message)
    } finally {
      if (alive.current) timer.current = setTimeout(refresh, POLL_MS)
    }
  }, [])

  useEffect(() => {
    alive.current = true
    refresh()
    return () => {
      alive.current = false
      clearTimeout(timer.current)
      clearTimeout(pctTimer.current)
    }
  }, [refresh])

  // Backend value wins once loaded; the local copy only covers the first paint.
  useEffect(() => {
    if (auto?.max_trade_pct) setMaxPctLocal(auto.max_trade_pct)
  }, [auto?.max_trade_pct])

  useEffect(() => {
    try {
      localStorage.setItem(KEY, JSON.stringify({ maxPct }))
    } catch {
      /* storage blocked: the % just won't persist locally */
    }
  }, [maxPct])

  const updateAuto = useCallback(async (patch) => {
    setAuto((s) => (s ? { ...s, ...patch } : s))
    try {
      const s = await rpc('va_set_autotrade', patch)
      setAuto(s)
      return s
    } catch (e) {
      rpc('va_get_autotrade').then(setAuto).catch(() => {})
      throw e
    }
  }, [])

  const setMaxPct = useCallback((v) => {
    setMaxPctLocal(v)
    clearTimeout(pctTimer.current)
    // Typing "25" passes through "2"; wait for a pause before saving.
    if (v >= 1 && v <= 100) pctTimer.current = setTimeout(() => updateAuto({ max_trade_pct: v }).catch(() => {}), 600)
  }, [updateAuto])

  const value = useMemo(() => {
    const capital = account?.account_value ?? 0
    const free = account?.available_margin ?? 0
    const perTrade = Math.max(0, Math.min((capital * maxPct) / 100, free))
    return { account, error, refresh, maxPct, setMaxPct, capital, free, perTrade, auto, updateAuto }
  }, [account, error, refresh, maxPct, setMaxPct, auto, updateAuto])

  return <BudgetContext.Provider value={value}>{children}</BudgetContext.Provider>
}

export const useBudget = () => useContext(BudgetContext)
