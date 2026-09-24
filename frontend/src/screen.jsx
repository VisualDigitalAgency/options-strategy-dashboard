import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import { rpc } from './rpc'

const POLL_MS = 2000
const ScreenContext = createContext(null)

export function ScreenProvider({ children }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const timer = useRef(null)

  const load = useCallback(async (force = false) => {
    clearTimeout(timer.current)
    setError(null)
    try {
      const res = await rpc('get_screened_candidates', { force_refresh: force })
      setData(res)
      if (res.progress.running) timer.current = setTimeout(() => load(false), POLL_MS)
    } catch (e) {
      setError(e.message)
    }
  }, [])

  useEffect(() => {
    load()
    return () => clearTimeout(timer.current)
  }, [load])

  const loading = !data || data.progress.running
  return <ScreenContext.Provider value={{ data, loading, error, load }}>{children}</ScreenContext.Provider>
}

export const useScreen = () => useContext(ScreenContext)
