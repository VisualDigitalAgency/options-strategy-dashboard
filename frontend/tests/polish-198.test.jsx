// UI polish (#198): S/R zone labels skip close neighbours; the public Levels page puts each fact on
// its own line and shows the capital reward.
import { GlobalRegistrator } from '@happy-dom/global-registrator'

GlobalRegistrator.register({ width: 1280, height: 800 })
globalThis.IS_REACT_ACT_ENVIRONMENT = true

const React = await import('react')
const { createRoot } = await import('react-dom/client')
const { MemoryRouter } = await import('react-router-dom')
const { AuthProvider } = await import('../src/auth.jsx')
const { zoneLabels } = await import('../src/components/Charts.jsx')
const { default: Progress } = await import('../src/pages/Progress.jsx')
const { act, createElement: h } = React

let ok = true
const check = (name, cond, got = '') => { ok &&= cond; console.log(`${cond ? 'PASS' : 'FAIL'} ${name}`, got) }

// 230 px over 700-930: 1 px per rupee. 779 sits 4 px above 775, so only one of the pair is labelled.
const zones = [{ level: 900 }, { level: 779 }, { level: 775 }, { level: 820 }]
const got = zoneLabels(zones, [700, 930], 230)
check('close zones: one label', got.has(2) && !got.has(1), [...got])
check('zones far apart: all labelled', got.has(0) && got.has(3), [...got])

globalThis.fetch = async (_url, opts) => {
  const { method, id } = JSON.parse(opts.body)
  const result = {
    auth_me: null, app_info: { name: 'X', logo: null, reader_pages: ['progress'] },
    levels_overview: [
      { level: 1, title: 'Learner', min_days: 60, capital: null, unlocks: [] },
      { level: 3, title: 'Seller', min_days: 60, capital: 25000, unlocks: ['Market Calendar page'] },
    ],
  }[method] ?? null
  return { status: 200, json: async () => ({ jsonrpc: '2.0', id, result }) }
}
const root = createRoot(document.body.appendChild(document.createElement('div')))
await act(async () => root.render(h(MemoryRouter, null, h(AuthProvider, null, h(Progress)))))
await act(async () => { await new Promise((r) => setTimeout(r, 50)) })
const l3 = [...document.querySelectorAll('.level-ladder li')][1]
const lines = [...(l3?.querySelectorAll('.level-line') ?? [])].map((e) => e.textContent)
check('levels: reward and unlock on their own lines', lines.length === 2 && lines[0].startsWith('Reward: ₹25,000') && lines[1] === 'Unlocks: Market Calendar page', lines)
check('levels: no reward line for Level 1', !document.querySelector('.level-ladder li')?.textContent.includes('Reward'))

process.exit(ok ? 0 : 1)
