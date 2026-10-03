// One minus format for money (#197): a negative amount reads −₹153, never ₹-153.
import { rupee, rupee2, signedRupee } from '../src/format.js'

let ok = true
const check = (name, cond, got) => {
  console.log(`${cond ? 'PASS' : 'FAIL'} ${name}${cond ? '' : ` -> ${got}`}`)
  if (!cond) ok = false
}

check('rupee negative', rupee(-153) === '−₹153', rupee(-153))
check('rupee positive', rupee(1234567) === '₹12,34,567', rupee(1234567))
check('rupee rounds to zero without a sign', rupee(-0.4) === '₹0', rupee(-0.4))
check('rupee null', rupee(null) === '—', rupee(null))
check('rupee2 negative', rupee2(-12.5) === '−₹12.50', rupee2(-12.5))
check('rupee2 rounds to zero without a sign', rupee2(-0.001) === '₹0.00', rupee2(-0.001))
check('matches signedRupee for negatives', rupee(-104) === signedRupee(-104), [rupee(-104), signedRupee(-104)])
process.exit(ok ? 0 : 1)
