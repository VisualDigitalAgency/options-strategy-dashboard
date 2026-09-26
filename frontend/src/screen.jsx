import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import { rpc } from './rpc'

// The backend refreshes the screen on its own timer; this only reads the cache.
const POLL_IDLE_MS = 60000 // nothing in flight: check once a minute for a newer screen
const POLL_ACTIVE_MS = 10000 // backend is refreshing: pick up new rows as batches land
const ScreenContext = createContext(null)

export function ScreenProvider({ children }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const timer = useRef(null)
  // False once unmounted (e.g. sign-out): a request still in flight then must not re-arm the poll,
  // or it keeps running forever next to the new provider's.
  const alive = useRef(false)

  const load = useCallback(async (force = false) => {
    clearTimeout(timer.current)
    let next = POLL_IDLE_MS
    try {
      const res = await rpc('get_screened_candidates', { force_refresh: force })
      setData(res) // replaces rows in place; never clears what is on screen
      setError(null)
      if (res.refreshing) next = POLL_ACTIVE_MS
    } catch (e) {
      setError(e.message) // keep showing the last data; the error shows as a banner
    } finally {
      if (alive.current) timer.current = setTimeout(() => load(false), next)
    }
  }, [])

  useEffect(() => {
    alive.current = true
    load()
    return () => {
      alive.current = false
      clearTimeout(timer.current)
    }
  }, [load])

  const refreshing = !!data?.refreshing
  // "loading" now means only the very first screen, before any cache exists.
  const loading = !data || (!data.candidates.length && refreshing)
  return <ScreenContext.Provider value={{ data, loading, refreshing, error, load }}>{children}</ScreenContext.Provider>
}

export const useScreen = () => useContext(ScreenContext)
