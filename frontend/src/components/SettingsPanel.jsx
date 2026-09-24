import { Link } from 'react-router-dom'
import { X } from 'lucide-react'
import { useBudget } from '../settings'
import { rupee, signedRupee } from '../format'

export default function SettingsPanel({ onClose }) {
  const { account, error, maxPct, setMaxPct, perTrade, capital, free } = useBudget()
  const capped = capital && perTrade < (capital * maxPct) / 100

  return (
    <div className="settings" role="region" aria-label="Wallet">
      <div className="settings-inner">
        {error && <p className="form-error">Couldn't load the virtual account: {error}</p>}
        <dl className="wallet-figures">
          <div><dt>Account value</dt><dd className="display-num">{account ? rupee(account.account_value) : '—'}</dd></div>
          <div><dt>Funds free</dt><dd className="num-lg">{account ? rupee(free) : '—'}</dd></div>
          <div><dt>Margin in use</dt><dd className="num-lg">{account ? rupee(account.used_margin) : '—'}</dd></div>
          <div><dt>Open P&L</dt><dd className={`num-lg ${account?.unrealized_pnl > 0 ? 'pos' : account?.unrealized_pnl < 0 ? 'neg' : ''}`}>{account ? signedRupee(account.unrealized_pnl) : '—'}</dd></div>
        </dl>
        <div className="wallet-controls">
          <div className="field">
            <label htmlFor="maxpct">Max margin per trade, % of account value</label>
            <input
              id="maxpct"
              type="number"
              inputMode="decimal"
              min="1"
              max="100"
              step="1"
              value={maxPct}
              onChange={(e) => setMaxPct(Math.min(100, Math.max(0, Number(e.target.value) || 0)))}
            />
          </div>
          <p className="helper">
            Lot suggestions can use up to <strong className="num">{rupee(perTrade)}</strong> per trade
            {capped ? ', capped by your free funds.' : '.'} This is your virtual account balance; change the starting
            amount on the <Link to="/virtual" onClick={onClose}>Virtual account</Link> page.
          </p>
        </div>
        <button className="icon-btn" onClick={onClose} aria-label="Close wallet">
          <X size={18} />
        </button>
      </div>
    </div>
  )
}
