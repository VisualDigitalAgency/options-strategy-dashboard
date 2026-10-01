import { useCallback, useEffect, useState } from 'react'
import { rpc } from '../rpc'
import RealAccountView from '../components/RealAccountView'
import { useTitle } from '../brand'

/** Real Zerodha account: funds/margin and open positions exactly as the broker reports them —
 *  unlike the virtual account, this is not simulated, so figures come straight from the worker's
 *  broker_snap cache (engine/brokers/poller.py), not recomputed here. When no broker is connected,
 *  engine.broker.account_summary falls back to the virtual account's own numbers so this page
 *  always shows something, clearly flagged as approximate. The Portfolio page can toggle this same
 *  view into place (issue #52) via the shared RealAccountView component. */
export default function BrokerAccount() {
  const [summary, setSummary] = useState(null)
  const [positions, setPositions] = useState(null)
  const [stops, setStops] = useState(null)
  const [error, setError] = useState(null)

  const load = useCallback(async () => {
    try {
      const s = await rpc('broker_account_summary')
      setSummary(s)
      if (s.source === 'broker') {
        const [p, st] = await Promise.all([rpc('broker_get_positions'), rpc('broker_stop_alerts')])
        setPositions(p)
        setStops(st)
      }
      setError(null)
    } catch (e) {
      setError(e.message)
    }
  }, [])

  useTitle('Real account')
  useEffect(() => { load() }, [load])

  return (
    <div className="detail">
      <RealAccountView summary={summary} positions={positions} stops={stops} error={error} heading="Real account" />
    </div>
  )
}
