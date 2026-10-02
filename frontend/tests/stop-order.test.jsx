// Stop-loss dialog (#183): a sold leg needs a trigger above the price; SL needs a limit at or above
// it; SL-M sends no limit.
import { GlobalRegistrator } from '@happy-dom/global-registrator'

GlobalRegistrator.register({ width: 375, height: 800 })
globalThis.IS_REACT_ACT_ENVIRONMENT = true

const React = await import('react')
const { createRoot } = await import('react-dom/client')
const { default: StopOrderDialog } = await import('../src/components/StopOrderDialog.jsx')
const { act, createElement: h } = React

let ok = true
const check = (name, cond, got = '') => { ok &&= cond; console.log(`${cond ? 'PASS' : 'FAIL'} ${name}`, got) }
let sent = null
const root = createRoot(document.body.appendChild(document.createElement('div')))
await act(async () => root.render(h(StopOrderDialog, { leg: { id: 7, qty: -100, strike: 900, side: 'PE', mark: 5 }, symbol: 'SBIN',
  busy: false, onSubmit: (p) => { sent = p }, onClose: () => {} })))
const set = async (el, v) => act(async () => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(el, v); el.dispatchEvent(new Event('input', { bubbles: true })) })
const inputs = () => [...document.querySelectorAll('.stop-form input')]
const submitBtn = () => [...document.querySelectorAll('.stop-form button')].find((b) => b.textContent.includes('Place'))

check('says it buys back a sold leg', document.querySelector('.stop-form').textContent.includes('Buys back all 100 qty'))
await set(inputs()[0], '4')
check('trigger below the price for a sold leg: refused', submitBtn().disabled && document.body.textContent.includes('must be above'))
await set(inputs()[0], '8')
check('trigger above: allowed', !submitBtn().disabled)
await act(async () => document.querySelector('.stop-form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })))
check('SL-M sends no limit', sent && sent.order_type === 'slm' && sent.trigger === 8 && !('limit' in sent), sent)
await act(async () => [...document.querySelectorAll('[role=radio]')][1].click())
await set(inputs()[1], '7.5')
check('SL limit below the trigger: refused', submitBtn().disabled)
await set(inputs()[1], '8.5')
await act(async () => document.querySelector('.stop-form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })))
check('SL sends trigger and limit', sent.order_type === 'sl' && sent.limit === 8.5, sent)
process.exit(ok ? 0 : 1)
