import { useEffect, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { AlertTriangle, CheckCircle2 } from 'lucide-react'
import { rpc } from '../rpc'
import { Logo, useBrand } from '../brand'

/** Where Zerodha's login redirects back to (KITE_REDIRECT_URL must point here exactly). Reads
 *  the one-time request_token from the query string and exchanges it server-side — the API
 *  secret never reaches the browser, only this token does. */
export default function BrokerCallback() {
  const { search } = useLocation()
  const nav = useNavigate()
  const { name: appName } = useBrand()
  const [state, setState] = useState('working') // working | done | error
  const [error, setError] = useState(null)

  useEffect(() => {
    const params = new URLSearchParams(search)
    const requestToken = params.get('request_token')
    const kiteStatus = params.get('status')
    if (kiteStatus && kiteStatus !== 'success') {
      setState('error')
      setError('Zerodha login did not complete')
      return
    }
    if (!requestToken) {
      setState('error')
      setError('No login token was returned by Zerodha')
      return
    }
    let oauthState = null
    try { oauthState = sessionStorage.getItem('broker_oauth_state') } catch { /* ignore */ }
    try { sessionStorage.removeItem('broker_oauth_state') } catch { /* ignore */ }
    if (!oauthState) {
      setState('error')
      setError('This connect attempt has expired or is invalid; start connecting again')
      return
    }
    rpc('broker_exchange_token', { request_token: requestToken, state: oauthState })
      .then(() => setState('done'))
      .catch((e) => { setState('error'); setError(e.message) })
  }, [search])

  useEffect(() => {
    if (state === 'done') {
      const t = setTimeout(() => nav('/broker', { replace: true }), 1200)
      return () => clearTimeout(t)
    }
  }, [state, nav])

  return (
    <div className="auth-page">
      <div className="auth-card">
        <div className="brand auth-brand"><Logo /><span className="wordmark">{appName}</span></div>
        {state === 'working' && <p className="auth-lede">Connecting your Zerodha account…</p>}
        {state === 'done' && (
          <p className="auth-done"><CheckCircle2 size={20} aria-hidden /> Connected. Taking you back…</p>
        )}
        {state === 'error' && (
          <>
            <p className="form-error" role="alert"><AlertTriangle size={16} aria-hidden /> {error}</p>
            <Link className="btn primary" to="/broker">Back to Broker</Link>
          </>
        )}
      </div>
    </div>
  )
}
