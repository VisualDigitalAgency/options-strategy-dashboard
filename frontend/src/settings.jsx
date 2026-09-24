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
 */
export function SettingsProvider({ children }) {
  const [maxPct, setMaxPct] = useState(readPct)
  const [account, setAccount] = useState(null)
  const [error, setError] = useState(null)
  const timer = useRef(null)

  const refresh = useCallback(async () => {
    clearTimeout(timer.current)
    try {
      setAccount(await rpc('va_get_account'))
      setError(null)
    } catch (e) {
      setError(e.message)
    } finally {
      timer.current = setTimeout(refresh, POLL_MS)
    }
  }, [])

  useEffect(() => {
    refresh()
    return () => clearTimeout(timer.current)
  }, [refresh])

  useEffect(() => {
    try {
      localStorage.setItem(KEY, JSON.stringify({ maxPct }))
    } catch {
      /* storage blocked: the % just won't persist */
    }
  }, [maxPct])

  const value = useMemo(() => {
    const capital = account?.account_value ?? 0
    const free = account?.available_margin ?? 0
    const perTrade = Math.max(0, Math.min((capital * maxPct) / 100, free))
    return { account, error, refresh, maxPct, setMaxPct, capital, free, perTrade }
  }, [account, error, refresh, maxPct])

  return <BudgetContext.Provider value={value}>{children}</BudgetContext.Provider>
}

export const useBudget = () => useContext(BudgetContext)
