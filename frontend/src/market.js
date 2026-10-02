import { useEffect, useState } from 'react'

// NSE equity derivatives session in IST. Trading holidays come from the server (app_info.holidays,
// NSE's own list) via setHolidays; until they arrive a holiday can read as open.
const PRE_OPEN = 9 * 60
const OPEN = 9 * 60 + 15
const CLOSE = 15 * 60 + 30

/** Wall-clock IST regardless of the machine's zone (fixed +5:30, no DST in India). */
export function istNow(d = new Date()) {
  return new Date(d.getTime() + d.getTimezoneOffset() * 60000 + 330 * 60000)
}

let HOLIDAYS = new Set()
const listeners = new Set()
export function setHolidays(dates) {
  HOLIDAYS = new Set(dates ?? [])
  listeners.forEach((f) => f())
}
const isoDate = (ist) => `${ist.getFullYear()}-${String(ist.getMonth() + 1).padStart(2, '0')}-${String(ist.getDate()).padStart(2, '0')}`

export function marketState(d = new Date()) {
  const ist = istNow(d)
  const mins = ist.getHours() * 60 + ist.getMinutes()
  const weekend = ist.getDay() === 0 || ist.getDay() === 6
  const time = `${String(ist.getHours()).padStart(2, '0')}:${String(ist.getMinutes()).padStart(2, '0')}`
  if (weekend) return { key: 'closed', label: 'Closed', note: 'Weekend', time }
  if (HOLIDAYS.has(isoDate(ist))) return { key: 'closed', label: 'Closed', note: 'Market holiday', time }
  if (mins < PRE_OPEN) return { key: 'closed', label: 'Closed', note: 'Opens 09:15', time }
  if (mins < OPEN) return { key: 'pre', label: 'Pre-open', note: 'Opens 09:15', time }
  if (mins < CLOSE) return { key: 'open', label: 'Open', note: 'Closes 15:30', time }
  return { key: 'closed', label: 'Closed', note: 'Opens 09:15', time }
}

export function useMarketClock() {
  const [state, setState] = useState(() => marketState())
  useEffect(() => {
    const tick = () => setState(marketState())
    const id = setInterval(tick, 15000)
    listeners.add(tick) // re-check as soon as the holiday list arrives
    return () => { clearInterval(id); listeners.delete(tick) }
  }, [])
  return state
}

/** Weekdays from today (exclusive) to expiry (inclusive). Holidays ignored, so treat as approximate. */
export function tradingDays(fromIso, toIso) {
  const d = new Date(fromIso + 'T00:00:00')
  const end = new Date(toIso + 'T00:00:00')
  let n = 0
  while (d < end) {
    d.setDate(d.getDate() + 1)
    if (d.getDay() !== 0 && d.getDay() !== 6) n++
  }
  return n
}
