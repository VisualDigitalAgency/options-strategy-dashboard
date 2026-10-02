// Market clock (#181): an NSE holiday reads "Closed · Market holiday", not "Open".
import { GlobalRegistrator } from '@happy-dom/global-registrator'

GlobalRegistrator.register({ width: 375, height: 800 })
const { marketState, setHolidays } = await import('../src/market.js')

let ok = true
const check = (name, cond, got = '') => { ok &&= cond; console.log(`${cond ? 'PASS' : 'FAIL'} ${name}`, got) }
// 11:00 IST = 05:30 UTC.
const fri = new Date('2026-10-02T05:30:00Z')
const thu = new Date('2026-10-01T05:30:00Z')
check('no holiday list: a weekday at 11:00 is open', marketState(fri).key === 'open')
setHolidays(['2026-10-02'])
const s = marketState(fri)
check('holiday: closed, says why', s.key === 'closed' && s.note === 'Market holiday', s)
check('the day before is still open', marketState(thu).key === 'open')
process.exit(ok ? 0 : 1)
