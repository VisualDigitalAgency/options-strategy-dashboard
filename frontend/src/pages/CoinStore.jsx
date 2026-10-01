import { Link } from 'react-router-dom'
import { Info, ShoppingCart, Sparkles } from 'lucide-react'
import { rupee } from '../format'
import { useTitle } from '../brand'

// Coin store (#175), phase 1: the page only. Payments aren't wired yet, so Buy is disabled; coins
// will be credited by the server from a verified payment, never from this page. Prices are
// placeholders until pricing is decided (#49).
const COIN_RUPEES = 100 // virtual capital per coin (config.COIN_RUPEES)
export const PACKS = [
  { id: 'starter', coins: 50, price: 49 },
  { id: 'trader', coins: 120, price: 99, tag: 'Popular' },
  { id: 'pro', coins: 300, price: 199, tag: 'Best value' },
]

export default function CoinStore() {
  useTitle('Coin store')
  return (
    <div className="detail coin-store">
      <header className="page-head">
        <div>
          <h1 className="display"><ShoppingCart size={26} aria-hidden /> Coin store</h1>
          <p className="lede">Top up your coins and exchange them for virtual capital on the <Link to="/coins">Coins</Link> page,
            at {rupee(COIN_RUPEES)} of virtual capital per coin.</p>
        </div>
      </header>
      <div className="alert info" role="status"><Info size={18} aria-hidden /> Payments are coming soon. You can't buy coins yet.</div>
      <div className="store-grid">
        {PACKS.map((p) => (
          <section key={p.id} className={`card store-pack${p.tag ? ' featured' : ''}`} aria-labelledby={`pk-${p.id}`}>
            {p.tag && <span className="chip"><Sparkles size={12} aria-hidden /> {p.tag}</span>}
            <h2 id={`pk-${p.id}`}><b className="mono">{p.coins}</b> coins</h2>
            <p className="muted small">= {rupee(p.coins * COIN_RUPEES)} of virtual capital</p>
            <p className="store-price mono">{rupee(p.price)}</p>
            <button className="btn primary" disabled title="Payments are coming soon">Buy</button>
          </section>
        ))}
      </div>
      <section className="card store-rules" aria-labelledby="sr-h">
        <h2 id="sr-h">Before you buy</h2>
        <ul>
          <li>Coins are for paper trading only. They have no cash value and can't be withdrawn, transferred or refunded as cash.</li>
          <li>Capital you exchange coins for adds to your virtual account, not to your profit: return %, levels and the leaderboard measure trading only.</li>
          <li>Coins you earn by trading with discipline work exactly the same. Buying is optional.</li>
        </ul>
      </section>
    </div>
  )
}
