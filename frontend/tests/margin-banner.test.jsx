// RMS margin banner (#178): hidden while margin is fine, a warning at 80%, square-off wording at 90%.
import { GlobalRegistrator } from '@happy-dom/global-registrator'

GlobalRegistrator.register({ width: 375, height: 800 })
globalThis.IS_REACT_ACT_ENVIRONMENT = true

const React = await import('react')
const { createRoot } = await import('react-dom/client')
const { default: MarginBanner } = await import('../src/components/MarginBanner.jsx')
const { act, createElement: h } = React

let ok = true
const check = (name, cond, got = '') => { ok &&= cond; console.log(`${cond ? 'PASS' : 'FAIL'} ${name}`, got) }
const root = createRoot(document.body.appendChild(document.createElement('div')))
const show = (a) => act(async () => root.render(h(MarginBanner, { account: a })))
const banner = () => document.querySelector('.margin-banner')

await show({ margin_status: 'ok', margin_used_pct: 40 })
check('fine: no banner', !banner())
await show({ margin_status: 'warning', margin_used_pct: 84.5 })
check('warning: low-margin banner with the figure', banner()?.classList.contains('warning') && banner().textContent.includes('84.5%'))
await show({ margin_status: 'squareoff', margin_used_pct: null })
check('square-off: says positions are being closed, value at or below zero', banner()?.textContent.includes('being squared off')
  && banner().textContent.includes('more than your account value') && banner().textContent.includes('₹50 per order'))
process.exit(ok ? 0 : 1)
