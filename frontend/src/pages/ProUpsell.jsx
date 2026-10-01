import { Link } from 'react-router-dom'
import { Lock } from 'lucide-react'
import { useTitle } from '../brand'

// What a free account sees in place of the screener (issue #136). There is no payment flow yet:
// the owner turns Pro on per account under Admin → Per-user overrides.

export default function ProUpsell() {
  useTitle('Screener (Pro)')
  return (
    <div className="card pro-upsell">
      <h1><Lock size={20} aria-hidden /> The screener is a Pro feature</h1>
      <p>Pro scans every Nifty 50 stock several times a day and picks option-selling setups for you:</p>
      <ul>
        <li>Strikes picked by the 30+ day, |delta| &lt; 0.15 and support/resistance rules</li>
        <li>Probability of profit, margin and risk : reward for each setup</li>
        <li>Full stock analysis pages and the Strategy lab</li>
        <li>Auto-trade on your virtual account</li>
      </ul>
      <p className="muted">To upgrade, ask the admin to turn Pro on for your account.</p>
      <div className="modal-actions">
        <Link className="btn primary" to="/learn">Keep learning</Link>
        <Link className="btn" to="/virtual">Virtual account</Link>
      </div>
    </div>
  )
}
