// Order ticket: with an earlier order still waiting, "Place" asks first; "Don't place" sends nothing,
// "Yes, place another" sends confirm_waiting. With nothing waiting it places straight away.
import { GlobalRegistrator } from '@happy-dom/global-registrator'

GlobalRegistrator.register()
globalThis.IS_REACT_ACT_ENVIRONMENT = true

const React = await import('react')
const { createRoot } = await import('react-dom/client')
const { MemoryRouter } = await import('react-router-dom')
const { default: OrderModal } = await import('../src/components/OrderModal.jsx')
const { SettingsProvider } = await import('../src/settings.jsx')
const { act, createElement: h } = React

let waiting = []
const placed = []
globalThis.fetch = async (_url, opts) => {
  const { method, params, id } = JSON.parse(opts.body)
  let result = {}
  if (method === 'va_preview_order') {
    result = {
      symbol: 'SUNPHARMA', expiry: '2026-10-27', lot_size: 350, premium: 10000, margin_change: 50000,
      available_margin: 900000, sufficient: true, sl_mode_default: 'alert', notes: [], market_open: false, waiting,
      fills: [{ side: 'CE', strike: 2200, action: 'SELL', qty: 350, limit: 30, price: 30, fills_now: false, bid: 30, ask: 31, ltp: 30, spot: 2000 }],
    }
  } else if (method === 'va_place_order') {
    placed.push(params)
    result = { filled: [], open: [{ side: 'CE', strike: 2200, limit: 30 }], open_ids: [9], premium: 10000, notes: [] }
  }
  return { status: 200, json: async () => ({ jsonrpc: '2.0', id, result }) }
}

const d = {
  symbol: 'SUNPHARMA', expiry: '2026-10-27', lot_size: 350, sl: { activates_on: '2026-10-10' },
  legs: [{ side: 'CE', strike: 2200 }],
}
const settle = () => act(async () => { await new Promise((r) => setTimeout(r, 450)) })
const text = () => document.body.textContent
const button = (label) => [...document.querySelectorAll('button')].find((b) => b.textContent.trim() === label)
const click = (label) => act(async () => { button(label).click() })

let ok = true
function check(name, cond) {
  ok &&= cond
  console.log(`${cond ? 'PASS' : 'FAIL'} ${name}`)
}

async function open() {
  document.body.replaceChildren(Object.assign(document.createElement('div'), { id: 'r' }))
  const root = createRoot(document.getElementById('r'))
  await act(async () => root.render(h(MemoryRouter, null, h(SettingsProvider, null, h(OrderModal, { d, lots: 1, onClose: () => {} })))))
  await settle()
  return root
}

// 1. An earlier order is waiting
waiting = [{ id: 1, side: 'CE', strike: 2200, action: 'SELL', qty: 350, limit_price: 29.5, reason: 'manual', created_at: '2026-09-26 15:37:52' }]
let root = await open()
await click('Place virtual limit order')
check('first click shows the warning, sends nothing', text().includes('Your previous order is not yet executed') && placed.length === 0)
check('warning lists the waiting order', text().includes('SELL 2200 CE × 350'))
check('asks to proceed', !!button('Yes, place another') && !!button("Don't place"))
await click("Don't place")
check("Don't place hides the warning and sends nothing", !text().includes('not yet executed') && placed.length === 0)
await click('Place virtual limit order')
await click('Yes, place another')
await settle()
check('proceed sends confirm_waiting: true', placed.length === 1 && placed[0].confirm_waiting === true)
check('success screen shown', text().includes('Virtual limit order placed'))
await act(async () => root.unmount())

// 2. Nothing waiting: places on the first click, no warning
waiting = []
placed.length = 0
root = await open()
await click('Place virtual limit order')
await settle()
check('no waiting order: places at once without confirm', placed.length === 1 && placed[0].confirm_waiting === false && !text().includes('not yet executed'))
await act(async () => root.unmount())

console.log(ok ? 'ALL PASS' : 'SOME FAILED')
process.exit(ok ? 0 : 1)
