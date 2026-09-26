import { Plug } from 'lucide-react'
import { BROKERS } from '../brokers'
import BrokerCard from '../components/BrokerCard'

export default function Broker() {
  return (
    <div className="detail">
      <header className="page-head">
        <div>
          <h1 className="display">Connect a broker</h1>
          <p className="lede">
            Broker execution isn't wired up yet — every trade here stays virtual. This is a preview
            of the brokers Theta Desk will support for placing real orders.
          </p>
        </div>
      </header>
      <div className="card broker-grid">
        {BROKERS.map((b) => <BrokerCard key={b.id} b={b} />)}
      </div>
      <p className="muted small broker-note">
        <Plug size={14} aria-hidden /> None of these accounts are connected. Nothing you do in the
        screener, portfolio or virtual account sends orders to a real broker.
      </p>
    </div>
  )
}
