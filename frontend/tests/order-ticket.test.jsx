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
let marketOpen = false
let bid = 30
let failDefaultPrice = false // the refresh (a preview with no typed price) fails
let brokerStatus = 'disconnected'
let illiquid = []
globalThis.fetch = async (_url, opts) => {
  const { method, params, id } = JSON.parse(opts.body)
  let result = {}
  if (method === 'va_preview_order') {
    const typed = params.legs[0].price
    if (typed === undefined && failDefaultPrice)
      return { status: 200, json: async () => ({ jsonrpc: '2.0', id, error: { code: -32000, message: 'NSE timed out' } }) }
    const limit = typed ?? bid
    result = {
      symbol: 'SUNPHARMA', expiry: '2026-10-27', lot_size: 350, premium: 10000, margin_change: 50000,
      available_margin: 900000, sufficient: true, sl_mode_default: 'alert', notes: [], market_open: marketOpen, waiting, illiquid,
      fills: [{ side: 'CE', strike: 2200, action: 'SELL', qty: 350, limit, price: limit, fills_now: false, bid, ask: bid + 1, ltp: bid, spot: 2000 }],
    }
  } else if (method === 'broker_account_summary') {
    result = { status: brokerStatus, available_margin_total: 100000, available_cash: 60000, total_collateral: 40000 }
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

async function open(intent) {
  document.body.replaceChildren(Object.assign(document.createElement('div'), { id: 'r' }))
  const root = createRoot(document.getElementById('r'))
  await act(async () => root.render(h(MemoryRouter, null, h(SettingsProvider, null, h(OrderModal, { d, lots: 1, intent, onClose: () => {} })))))
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

// 3. Refresh price (#42): disabled with the market closed
const refreshBtn = () => document.querySelector('button[aria-label="Refresh price"]')
const limitInput = () => document.querySelector('input.limit-input')
async function type(v) {
  await act(async () => {
    const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set
    set.call(limitInput(), v)
    limitInput().dispatchEvent(new Event('input', { bubbles: true }))
  })
}
root = await open()
check('refresh disabled while the market is closed', refreshBtn().disabled === true)
await act(async () => root.unmount())

// 4. Market open: replaces a typed limit with the current bid
marketOpen = true
root = await open()
check('refresh enabled with live bid/ask', refreshBtn().disabled === false)
await type('25')
await settle()
bid = 32.35
await act(async () => { refreshBtn().click() })
await settle()
check('refresh replaces the limit with the current best price', limitInput().value === '32.35')

// 5. Failure keeps the typed value and shows the reason
await type('26')
await settle()
failDefaultPrice = true
await act(async () => { refreshBtn().click() })
await settle()
check('failed refresh keeps the typed limit', limitInput().value === '26')
check('failed refresh explains itself', refreshBtn().title.includes('NSE timed out') && refreshBtn().disabled === false)
await act(async () => root.unmount())

// 6. Primary button follows the intent (#41)
const primary = () => document.querySelector('.modal-actions .btn.primary')?.textContent.trim()
const last = () => [...document.querySelectorAll('.modal-actions button')].at(-1).textContent.trim()
root = await open('virtual')
check('virtual intent: virtual order is the primary, last button', primary() === 'Place virtual limit order' && last() === primary())
check('no broker: live button disabled with a reason', button('Place live order').disabled && button('Place live order').title.includes('Connect a broker'))
await act(async () => root.unmount())
root = await open('live')
check('live intent without a broker falls back to virtual primary', primary() === 'Place virtual limit order')
await act(async () => root.unmount())
brokerStatus = 'active'
root = await open('live')
check('live intent with a broker: live order is the primary, last button', primary() === 'Place live order' && last() === primary())
check('live button enabled once connected', !button('Place live order').disabled)
await act(async () => root.unmount())
root = await open('virtual')
check('virtual intent with a broker keeps virtual primary', primary() === 'Place virtual limit order')
await act(async () => root.unmount())
brokerStatus = 'disconnected'

// 7. Illiquid strike (stale LTP / wide spread): the reason shows, the button asks "Place anyway",
// and that click sends confirm_illiquid; a liquid strike sends it false.
failDefaultPrice = false
placed.length = 0
illiquid = [{ side: 'CE', strike: 2200, reason: 'last trade ₹6.00 is 69% outside the ₹3.40/₹3.60 book (stale)', bid: 3.4, ask: 3.6, ltp: 6 }]
root = await open('virtual')
check('illiquid: reason shown', text().includes('Illiquid strike') && text().includes('outside the ₹3.40/₹3.60 book'))
await click('Place anyway')
await settle()
check('illiquid: Place anyway sends confirm_illiquid', placed.length === 1 && placed[0].confirm_illiquid === true)
await act(async () => root.unmount())
illiquid = []
placed.length = 0
root = await open('virtual')
check('liquid: no warning', !text().includes('Illiquid strike'))
await click('Place virtual limit order')
await settle()
check('liquid: confirm_illiquid false', placed.length === 1 && placed[0].confirm_illiquid === false)
await act(async () => root.unmount())

console.log(ok ? 'ALL PASS' : 'SOME FAILED')
process.exit(ok ? 0 : 1)
