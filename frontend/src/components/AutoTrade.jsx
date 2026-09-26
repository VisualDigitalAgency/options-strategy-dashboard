import { useCallback, useEffect, useState } from 'react'
import { Bot, CircleCheck, CircleMinus, Play } from 'lucide-react'
import { rpc } from '../rpc'
import { useBudget } from '../settings'
import { dateTime, pct, rupee } from '../format'
import { ConfirmDialog } from './Modal'

const nextRunLabel = (s) => {
  if (!s?.next_run) return null
  const [d, t] = s.next_run.split(' ')
  const day = new Date(d + 'T00:00:00').toLocaleDateString('en-IN', { weekday: 'short', day: '2-digit', month: 'short' })
  return `${day}, ${t} IST`
}

/** On/off switch for auto-trade. Turning it on asks for confirmation with the live limits. */
export function AutoTradeSwitch({ compact = false }) {
  const { auto, updateAuto, capital } = useBudget()
  const [confirm, setConfirm] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  if (!auto) return <span className="skeleton" style={{ width: 52, height: 28, borderRadius: 99 }} />

  const set = async (enabled) => {
    setBusy(true)
    setError(null)
    try {
      await updateAuto({ enabled })
      setConfirm(false)
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <button
        type="button"
        role="switch"
        aria-checked={auto.enabled}
        aria-label="Auto-trade"
        className={`switch ${compact ? 'compact' : ''}`}
        onClick={() => (auto.enabled ? set(false) : setConfirm(true))}
        disabled={busy}
      >
        <span className="switch-thumb" aria-hidden />
      </button>
      {confirm && (
        <ConfirmDialog
          title="Turn on auto-trade?"
          body={`Every trading day at ${auto.run_at} IST, setups with POP of at least ${auto.min_pop}% are sold into your virtual account, best POP-weighted ROI first. Each trade uses at most ${auto.max_trade_pct}% of account value (${rupee((capital * auto.max_trade_pct) / 100)}), and at least ${auto.reserve_pct}% (${rupee((capital * auto.reserve_pct) / 100)}) always stays free. Virtual account only; no broker orders.`}
          confirmLabel="Turn on"
          busy={busy}
          error={error}
          onConfirm={() => set(true)}
          onClose={() => setConfirm(false)}
        />
      )}
    </>
  )
}

export function AutoTradeStatus() {
  const { auto } = useBudget()
  if (!auto) return null
  return auto.enabled
    ? <span>On. Next run <b className="num">{nextRunLabel(auto)}</b></span>
    : <span>Off. Turn on to place trades once a day.</span>
}

function Field({ id, label, suffix, value, onCommit, ...input }) {
  const [v, setV] = useState(value)
  useEffect(() => setV(value), [value])
  return (
    <div className="field auto-field">
      <label htmlFor={id}>{label}</label>
      <span className="input-suffix">
        <input id={id} value={v} onChange={(e) => setV(e.target.value)} onBlur={() => String(v) !== String(value) && onCommit(v)}
          onKeyDown={(e) => e.key === 'Enter' && e.currentTarget.blur()} {...input} />
        {suffix && <span aria-hidden>{suffix}</span>}
      </span>
    </div>
  )
}

function RunLog({ runs }) {
  if (!runs) return <span className="skeleton" style={{ height: 40 }} />
  if (!runs.length) return <p className="muted small">No runs yet. The first one happens at the next scheduled time, or use Run now.</p>
  return (
    <ul className="run-log">
      {runs.map((r) => (
        <li key={r.id}>
          <details>
            <summary>
              <span className="num">{dateTime(r.ts)}</span>
              <span className={`reason ${r.trigger === 'schedule' ? 'reason-auto' : ''}`}>{r.trigger === 'schedule' ? 'Scheduled' : 'Manual'}</span>
              <span><b className="num">{r.placed}</b> placed, <span className="num">{r.summary.skipped.length}</span> skipped</span>
              <span className="muted num run-free">Free after {rupee(r.summary.free_after)}</span>
            </summary>
            <div className="run-detail">
              {r.summary.placed.map((p) => (
                <p key={p.symbol} className="run-line placed">
                  <CircleCheck size={14} aria-hidden />
                  <b>{p.symbol}</b> <span className="num">{p.legs.join(' / ')}</span>
                  <span className="muted num">{p.lots} lot{p.lots > 1 ? 's' : ''}, POP {pct(p.pop)}, ROI {pct(p.roi_pct, 2)}, margin {rupee(p.margin)}</span>
                </p>
              ))}
              {r.summary.skipped.map((p) => (
                <p key={p.symbol} className="run-line">
                  <CircleMinus size={14} aria-hidden />
                  <b>{p.symbol}</b> <span className="muted">{p.reason}</span>
                </p>
              ))}
            </div>
          </details>
        </li>
      ))}
    </ul>
  )
}

/** Full auto-trade card for the Virtual account page. */
export default function AutoTradePanel({ onRun }) {
  const { auto, updateAuto, capital, maxPct, setMaxPct, refresh } = useBudget()
  const [runs, setRuns] = useState(null)
  const [error, setError] = useState(null)
  const [confirmRun, setConfirmRun] = useState(false)
  const [busy, setBusy] = useState(false)

  const loadRuns = useCallback(() => rpc('va_autotrade_runs').then(setRuns).catch((e) => setError(e.message)), [])
  useEffect(() => { loadRuns() }, [loadRuns, auto?.last_run_date])

  const commit = (key, cast = Number) => async (v) => {
    setError(null)
    try {
      await updateAuto({ [key]: cast(v) })
    } catch (e) {
      setError(e.message)
    }
  }

  async function runNow() {
    setBusy(true)
    setError(null)
    try {
      await rpc('va_autotrade_run_now')
      setConfirmRun(false)
      await Promise.all([loadRuns(), refresh()])
      onRun?.()
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="card auto-card" id="auto">
      <header className="card-head">
        <h2><Bot size={16} aria-hidden />Auto-trade</h2>
        <span className="muted small">Virtual account only, no broker orders</span>
      </header>

      <div className="auto-top">
        <AutoTradeSwitch />
        <p className="auto-status"><AutoTradeStatus /></p>
        <button className="btn small" onClick={() => { setError(null); setConfirmRun(true) }} disabled={!auto || auto.running}>
          <Play size={14} aria-hidden /> Run now
        </button>
      </div>

      {auto ? (
        <div className="auto-fields">
          <Field id="auto-time" label="Run daily at (IST)" type="time" min="09:15" max="15:29" step="60" value={auto.run_at} onCommit={commit('run_at', String)} />
          <Field id="auto-pop" label="Minimum POP" suffix="%" type="number" inputMode="decimal" min="50" max="99" step="1" value={auto.min_pop} onCommit={commit('min_pop')} />
          <Field id="auto-reserve" label="Keep free" suffix="%" type="number" inputMode="decimal" min="0" max="90" step="1" value={auto.reserve_pct} onCommit={commit('reserve_pct')} />
          <Field id="auto-cap" label="Max per trade" suffix="%" type="number" inputMode="decimal" min="1" max="100" step="1" value={maxPct} onCommit={(v) => setMaxPct(Number(v))} />
        </div>
      ) : (
        <span className="skeleton" style={{ height: 64 }} />
      )}
      {error && <p className="form-error" role="alert">{error}</p>}

      {auto && (
        <p className="helper auto-limits">
          At today's account value: up to <strong className="num">{rupee((capital * maxPct) / 100)}</strong> margin per trade,
          and <strong className="num">{rupee((capital * auto.reserve_pct) / 100)}</strong> always kept free. Setups are ranked by
          POP × ROI on margin; one position per stock and expiry, never added to. Max per trade also sets lot suggestions.
        </p>
      )}

      <h3 className="auto-sub">Recent runs</h3>
      <RunLog runs={runs} />

      {confirmRun && (
        <ConfirmDialog
          title="Run auto-trade now?"
          body="Places virtual orders from the current screen with the limits above. Outside market hours, bid and ask are empty, so fills use the last traded price."
          confirmLabel="Run now"
          busy={busy}
          error={error}
          onConfirm={runNow}
          onClose={() => setConfirmRun(false)}
        />
      )}
    </section>
  )
}
