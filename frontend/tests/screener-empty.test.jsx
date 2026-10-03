// Screener empty states (#198): with no filter to blame, an empty screen says no setups passed
// today instead of offering "Clear filters".
import { GlobalRegistrator } from '@happy-dom/global-registrator'

GlobalRegistrator.register({ width: 1280, height: 800 })
globalThis.IS_REACT_ACT_ENVIRONMENT = true

const React = await import('react')
const { createRoot } = await import('react-dom/client')
const { MemoryRouter } = await import('react-router-dom')
const { ScreenProvider } = await import('../src/screen.jsx')
const { SettingsProvider } = await import('../src/settings.jsx')
const { default: Overview } = await import('../src/pages/Overview.jsx')
const { act, createElement: h } = React

let ok = true
const check = (name, cond, got = '') => { ok &&= cond; console.log(`${cond ? 'PASS' : 'FAIL'} ${name}`, got) }

globalThis.fetch = async (_url, opts) => {
  const { method, id } = JSON.parse(opts.body)
  const result = {
    get_screened_candidates: { candidates: [], refreshing: false, generated_at: '2026-10-02T10:00:00', progress: {} },
    va_get_account: { account_value: 1000000, available_margin: 1000000 },
    va_get_autotrade: { max_trade_pct: 10 },
  }[method] ?? null
  return { status: 200, json: async () => ({ jsonrpc: '2.0', id, result }) }
}

const root = createRoot(document.body.appendChild(document.createElement('div')))
await act(async () => root.render(h(MemoryRouter, null,
  h(SettingsProvider, null, h(ScreenProvider, { enabled: true }, h(Overview))))))
await act(async () => { await new Promise((r) => setTimeout(r, 60)) })
const text = document.body.textContent
check('empty screen says no setups today', text.includes('No setups pass the screen today'), text.slice(0, 300))
check('no Clear filters when nothing filtered', ![...document.querySelectorAll('button')].some((b) => b.textContent.includes('Clear filters')))

process.exit(ok ? 0 : 1)
