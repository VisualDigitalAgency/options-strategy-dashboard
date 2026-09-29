// Display names for the corporate-event types the server sends (engine/market_calendar.py).
export const EVENT_LABEL = {
  results: 'Results', dividend: 'Ex-dividend', split: 'Split', bonus: 'Bonus', agm: 'AGM',
  buyback: 'Buyback', board_meeting: 'Board meeting',
}

// Types that can move the stock or its strikes. The screener badge shows only these: an AGM or a
// plain board meeting rarely matters to a short strike, and they stay on the calendar and detail page.
export const SCREENER_TYPES = new Set(['results', 'dividend', 'split', 'bonus', 'buyback'])

export const screenerEvents = (events) => (events ?? []).filter((e) => SCREENER_TYPES.has(e.type))

// NSE's purpose text often just restates the type ("Financial Results" under Results). Keep it only
// when it adds something: a dividend amount, a split ratio, what a board meeting is for.
const GENERIC = new Set(['results', 'financial results', 'annual general meeting', 'agm', 'dividend', 'bonus', 'split', 'buyback', 'board meeting'])
export function eventNote(e) {
  const p = (e.purpose ?? '').trim()
  const bare = p.toLowerCase().replace(/[^a-z ]+/g, ' ').replace(/\s+/g, ' ').trim()
  return !p || GENERIC.has(bare) || bare === (EVENT_LABEL[e.type] ?? '').toLowerCase() ? '' : p
}

export const awayText = (d) => (d === 0 ? 'Today' : d === 1 ? 'Tomorrow' : `${d}d`)

// "Fri, 9 Oct": the weekday matters for events and holidays; shortDate has no weekday.
export const dayDate = (iso) =>
  new Date(`${iso}T00:00:00`).toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short' })
export const dayMonth = (iso) => new Date(`${iso}T00:00:00`).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })
