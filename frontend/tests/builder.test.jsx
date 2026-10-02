// Strategy builder (issue #137): chain and templates, expiry stats (unlimited vs capped), rule
// warnings that never block, sell/buy colouring, the lot stepper, the phone dock and chain toggle, the server's buy-leg reason shown and the button disabled, and placing.
import { GlobalRegistrator } from '@happy-dom/global-registrator'

GlobalRegistrator.register({ width: 375, height: 800 })
globalThis.IS_REACT_ACT_ENVIRONMENT = true

const React = await import('react')
const { createRoot } = await import('react-dom/client')
const { MemoryRouter, Route, Routes } = await import('react-router-dom')
const { AuthProvider } = await import('../src/auth.jsx')
const { default: Builder } = await import('../src/pages/Builder.jsx')
const { addLot, curve, netLegs, pnlOn, probProfit, safeStrike, scorecard, stats, TEMPLATES, zoneAt } = await import('../src/strategy.js')
const { act, createElement: h } = React

let ok = true
const check = (name, cond, got = '') => { ok &&= cond; console.log(`${cond ? 'PASS' : 'FAIL'} ${name}`, got) }
const settle = (ms = 30) => act(async () => { await new Promise((r) => setTimeout(r, ms)) })

// 1. Maths.
const L = (side, strike, action, premium) => ({ side, strike, action, lots: 1, premium })
let st = stats([L('CE', 1100, 'SELL', 5), L('PE', 900, 'SELL', 5)], 1000, 100)
check('short strangle: credit 1000, unlimited loss', st.net === 1000 && st.maxLoss === -Infinity && st.maxProfit === 1000, st)
check('short strangle breakevens', st.breakevens.join() === '890,1110', st.breakevens)
st = stats([L('PE', 900, 'SELL', 5), L('PE', 800, 'BUY', 2)], 1000, 100)
check('bull put spread: capped loss 9700', st.maxLoss === -9700 && st.maxProfit === 300, st)
st = stats([L('CE', 1100, 'BUY', 5)], 1000, 100)
check('long call: debit, unlimited profit, loss = premium', st.net === -500 && st.maxProfit === Infinity && st.maxLoss === -500, st)

// 2. Page.
const strike = (k, cd, pd) => ({ strike: k, CE: { bid: 5, ask: 5.2, ltp: 5.1, iv: 20, oi: 1000, oi_chg: 250, pchg: 4.25, delta: cd }, PE: { bid: 4, ask: 4.2, ltp: 4.1, iv: 20, oi: 1000, oi_chg: -300, pchg: -2.5, delta: pd } })
const chain = {
  symbol: 'SBIN', expiry: '2026-12-29', expiries: ['2026-11-24', '2026-12-29'], spot: 1000, dte: 20, lot_size: 100,
  rows: [800, 850, 900, 950, 1000, 1050, 1100, 1150, 1200].map((k) => strike(k, Math.max(0.02, 0.5 - (k - 1000) / 500), -Math.max(0.02, 0.5 - (1000 - k) / 500))),
  events: [{ symbol: 'SBIN', date: '2026-11-05', type: 'results', risky: true }],
  rules: { min_dte: 30, delta_max_abs: 0.15, long_sl_pct: 50, time_exit_dte: 7 },
  summary: { pcr: 0.7, max_pain: 1000, atm_strike: 1000, atm_iv: 20 },
}
const condor = TEMPLATES.iron_condor.legs(chain)
check('iron condor: 4 legs, each buy 2 strikes beyond its sell', condor.length === 4
  && condor[1][1] - condor[0][1] === 100 && condor[2][1] - condor[3][1] === 100, condor)
const calls = []
globalThis.fetch = async (_url, opts) => {
  const { method, id, params } = JSON.parse(opts.body)
  calls.push({ method, params })
  const buys = params.legs?.filter((l) => l.action === 'BUY') ?? []
  const sells = params.legs?.filter((l) => l.action === 'SELL') ?? []
  const result = {
    auth_me: { id: 1, name: 'A', email: 'a@x', role: 'user', level: 1, features: [], prefs: {}, nickname: 'a',
      sell_levels: { naked: 3, strangle: 5 } },
    app_info: { name: 'X', logo: null },
    get_config: { universe: ['RELIANCE', 'SBIN'] },
    builder_chain: chain,
    builder_levels: { symbol: 'SBIN', pivots: { P: 1000, R1: 1080, S1: 920 }, zones: [{ level: 1110, type: 'resistance', touches: 3 }], zone_width_pct: 1.5 },
    va_preview_order: { fills: [], margin_change: 12345, available_margin: 1e6, sufficient: true, notes: [], illiquid: [], waiting: [],
      buy_rule: buys.length && !sells.length ? 'Buying a CE on its own unlocks at Level 6.' : null },
    va_place_order: { filled: [1, 2, 3, 4], open: [] },
  }[method]
  return { status: 200, json: async () => ({ jsonrpc: '2.0', id, result }) }
}

const root = createRoot(document.body.appendChild(document.createElement('div')))
await act(async () => root.render(h(MemoryRouter, { initialEntries: ['/builder?symbol=SBIN'] },
  h(AuthProvider, null, h(Routes, null, h(Route, { path: '/builder', element: h(Builder) }))))))
await settle(80)
const text = () => document.body.textContent
const btn = (t) => [...document.querySelectorAll('button')].find((b) => b.textContent.trim() === t || b.getAttribute('aria-label') === t)

// Buy/Sell are hidden until the strike row is tapped (#158).
const tapTrade = async (label) => {
  if (!btn(label)) {
    const k = Number(label.split(' ')[1]).toLocaleString('en-IN')
    const th = [...document.querySelectorAll('.chain-row th.chain-k')].find((t) => t.textContent.startsWith(k))
    await act(async () => th.closest('tr').click())
  }
  await act(async () => btn(label).click())
}
check('chain loaded for the stock in the URL', calls.some((c) => c.method === 'builder_chain' && c.params.symbol === 'SBIN') && !!document.querySelector('.chain-table'))
check('OI rising green (oi-chg up), falling red (down)', document.querySelector('td.chain-oi.ce .oi-chg.up')?.textContent === '+250'
  && document.querySelector('td.chain-oi.pe .oi-chg.down')?.textContent === '−300')
check('OI legend explains the colours', document.querySelector('.oi-legend')?.textContent.includes('green'))
check('price change: + green, − red, two decimals', document.querySelector('td.chain-ltp.ce .px-chg.up')?.textContent === '+4.25%'
  && document.querySelector('td.chain-ltp.pe .px-chg.down')?.textContent === '−2.50%')
check('OI bar is thin', !!document.querySelector('.oi-bar'))
check('free account: buy rule explained up front', text().includes('until Level 6'))

const tpl = (t) => [...document.querySelectorAll('.tpl')].find((b) => b.textContent.startsWith(t))
check('Level 1: strangle and straddle templates locked with their level', tpl('Short strangle')?.disabled && tpl('Short straddle')?.disabled
  && tpl('Short strangle').textContent.includes('Level 5'))
check('Level 1: spreads and the condor stay open', ['Iron condor', 'Bull put spread', 'Bear call spread'].every((t) => !tpl(t)?.disabled))
await act(async () => btn('Iron condor').click())
await settle(500)
check('iron condor: 4 legs on the page', document.querySelectorAll('.builder-leg').length === 4)
check('warnings: DTE and results, never blocking', text().includes('20 days to expiry') && text().includes('Results on 2026-11-05')
  && !btn('Place on virtual account').disabled)
check('margin from the preview', text().includes('12,345'))
check('payoff chart drawn', !!document.querySelector('.chart'))
check('levels fetched for the stock', calls.some((c) => c.method === 'builder_levels' && c.params.symbol === 'SBIN'))
check('chain: OI tab, LTP both sides, strike in the middle', [...document.querySelectorAll('.chain-cols th')].map((t) => t.textContent).join('|') === 'OI|Call LTP|Strike|Put LTP|OI')
check('Buy/Sell hidden until a strike row is tapped', !document.querySelector('.chain-actions') && !btn('Buy 1100 CE'))
check('footer: PCR, max pain, ATM IV', ['PCR', 'Max pain', 'ATM IV'].every((t) => document.querySelector('.chain-foot')?.textContent.includes(t)))
check('expiry pills, current one pressed', document.querySelector('.expiry-pills button[aria-pressed="true"]')?.textContent.startsWith(''))
check('strike bar splits call and put OI', !!document.querySelector('.pair-bar .pb-ce') && !!document.querySelector('.pair-bar .pb-pe'))
check('analysis: probability of profit, return on margin, vega, 1σ move', ['Probability of profit', 'Return on margin', 'Vega / IV pt', '1σ move by expiry'].every((t) => text().includes(t)))
check('rule check lists rows and a count to review', !!document.querySelector('.builder-score') && /\d+ to review/.test(text()))
check('rule check: a sold strike in the S/R zone is flagged', text().includes('resistance zone at 1110'))
const slider = document.querySelector('input[aria-label="Days from today"]')
await act(async () => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(slider, '10'); slider.dispatchEvent(new Event('input', { bubbles: true })) })
check('date slider moves the T+N curve label', text().includes('In 10 days'), slider.value)
await act(async () => btn('Pin to compare an adjustment').click())
check('pinning shows the comparison', text().includes('Against the pinned version'))
await act(async () => btn('Unpin').click())
check('sell legs orange-red, buy legs blue (classes)', document.querySelectorAll('.builder-leg.is-sell').length === 2
  && document.querySelectorAll('.builder-leg.is-buy').length === 2)
check('mobile dock shows the net and a Place button', !!document.querySelector('.builder-dock .btn.primary')
  && /(credit|debit)/.test(document.querySelector('.builder-dock').textContent))
await act(async () => document.querySelector('.builder-leg.is-buy [aria-label="Buy or sell"] button.tone-sell').click())
check('flipping a leg to sell recolours it', document.querySelectorAll('.builder-leg.is-sell').length === 3)
await act(async () => btn('More lots').click())
check('lot stepper adds a lot', document.querySelector('.builder-leg input[aria-label=Lots]').value === '2')
await act(async () => btn('Iron condor').click())
await settle(500)
check('phone shows calls and puts side by side (no toggle)', !btn('Puts') && !!document.querySelector('td.chain-ltp.ce') && !!document.querySelector('td.chain-ltp.pe'))

await act(async () => btn('Place on virtual account').click())
await settle()
const placed = calls.find((c) => c.method === 'va_place_order')
check('places all 4 legs on the virtual account', placed?.params.legs.length === 4 && placed.params.symbol === 'SBIN', placed?.params)
check('success links to Portfolio', text().includes('Order placed: 4 filled'))

await tapTrade('Buy 1200 CE')
await settle(500)
check('naked buy: server reason shown', text().includes('unlocks at Level 6') && btn('Place on virtual account').disabled)
check('tapped row shows Buy then Sell', [...(document.querySelector('.act-strip')?.querySelectorAll('button') ?? [])].map((b) => b.textContent).join('') === 'BuySell')
check('bottom bar says it is a virtual order', [...document.querySelectorAll('.builder-dock button')].some((b) => b.textContent === 'Place virtual order'))

// 3. Analysis maths.
const strangle = [{ ...L('CE', 1100, 'SELL', 5), iv: 20 }, { ...L('PE', 900, 'SELL', 5), iv: 20 }]
const pop = probProfit(strangle, chain)
check('PoP: wide short strangle mostly wins', pop > 0.9 && pop < 1, pop)
const lcPop = probProfit([{ ...L('CE', 1100, 'BUY', 5), iv: 20 }], chain)
check('PoP: far OTM long call mostly loses', lcPop > 0 && lcPop < 0.1, lcPop)
check('T+0 P&L at spot is about zero (calibrated to the premium)', Math.abs(pnlOn(strangle, 1000, 20, 100, 1000, 20)) < 1)
const pts = curve(strangle, chain, { daysAhead: 10, baseline: strangle })
check('curve: expiry, day-N and baseline series', pts.length === 161 && pts.every((p) => Number.isFinite(p.now) && p.base === p.pnl))
const lv = { zones: [{ level: 1200, type: 'resistance', touches: 2 }], zone_width_pct: 1.5 }
check('zoneAt within the zone width', zoneAt(lv, 1190)?.level === 1200 && !zoneAt(lv, 1150))
check('safe strike: lowest delta under the limit, most premium', safeStrike(chain, 'CE', null).strike === 1200 && safeStrike(chain, 'PE', null).strike === 800)
check('safe strike skips an S/R zone', safeStrike(chain, 'CE', lv).strike === null)
const sc = scorecard({ ...chain, dte: 40, events: [] }, [{ ...L('CE', 1200, 'SELL', 5), delta: 0.1 }], lv)
check('scorecard: zone flagged, delta passes', sc.find((r) => r.label.endsWith('support/resistance'))?.ok === false
  && sc.find((r) => r.label.endsWith('delta'))?.ok === true, sc)

// 4. Active legs in the chain (#144).
let ls = addLot(chain, [], 'CE', 1100, 'SELL')
ls = addLot(chain, ls, 'CE', 1100, 'SELL')
check('S twice: one leg of 2 lots', ls.length === 1 && ls[0].lots === 2 && ls[0].action === 'SELL', ls)
ls = addLot(chain, ls, 'CE', 1100, 'BUY')
check('B on a sold strike takes a lot off', ls.length === 1 && ls[0].lots === 1)
check('...and the last one drops the leg', addLot(chain, ls, 'CE', 1100, 'BUY').length === 0)
check('netting flips past zero', netLegs(chain, [{ side: 'PE', strike: 900, action: 'SELL', lots: 1 }, { side: 'PE', strike: 900, action: 'BUY', lots: 3 }])[0]?.action === 'BUY')

const cellsOf = (label) => document.querySelector(`[aria-label="${label}"]`)?.closest('td')
check('bought 1200 CE shows in the chain, light blue', cellsOf('Bought 1,200 CE')?.className.includes('leg-buy'), cellsOf('Bought 1,200 CE')?.className)
await act(async () => btn('One lot more of 1,200 CE').click())
await settle(50)
check('+ in the chain adds a lot (list agrees)', cellsOf('Bought 1,200 CE')?.textContent.includes('2')
  && document.querySelectorAll('.builder-leg').length === 1)
await tapTrade('Sell 1100 CE')
await settle(50)
check('sold strike shows light red in the chain', cellsOf('Sold 1,100 CE')?.className.includes('leg-sell')
  && document.querySelector('.builder-leg.is-sell') != null)
await act(async () => btn('One lot less of 1,100 CE').click())
await settle(50)
check('- on the last lot removes the leg everywhere', !cellsOf('Sold 1,100 CE') && !document.querySelector('.builder-leg.is-sell')
  && !!btn('Sell 1100 CE'))

await act(async () => [...document.querySelectorAll('.chain-toolbar .seg button')].find((b) => b.textContent === 'Greeks').click())
check('Greeks tab: IV, delta, gamma, theta, vega and LTP', [...document.querySelectorAll('.chain-cols th')].map((t) => t.textContent).join('|') === 'Vega|Θ|Γ|Δ|IV|Call LTP|Strike|Put LTP|IV|Δ|Γ|Θ|Vega'
  && document.querySelectorAll('td.chain-g').length > 0)
await act(async () => root.unmount())
process.exit(ok ? 0 : 1)
