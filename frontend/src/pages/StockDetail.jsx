import EventBadge from '../components/EventBadge'
import EventTable from '../components/EventTable'
import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import {
  AlertCircle, ArrowLeft, Calculator, CalendarClock, ChartCandlestick, ChartNoAxesColumn, ChartSpline, ClipboardCheck, Minus, Plus,
  ShieldAlert, ShieldCheck, Sigma, SlidersHorizontal,
} from 'lucide-react'
import { rpc } from '../rpc'
import { useScreen } from '../screen'
import { useBudget } from '../settings'
import { ActionBadge, LegTag, SentimentBadge } from '../components/Badges'
import { OIChart, PayoffChart, PriceChart } from '../components/Charts'
import Checklist from '../components/Checklist'
import SLTimeline from '../components/SLTimeline'
import OrderModal from '../components/OrderModal'
import DetailSkeleton from '../components/DetailSkeleton'
import StrategyLab from '../components/StrategyLab'
import UpdatedTag from '../components/UpdatedTag'
import { int, num, pct, rupee, rupee2, shortDate, signed, signedPct, suggestLots, todayIso } from '../format'

function Stat({ label, value, sub, tone }) {
  return (
    <div className={`stat ${tone ? `tone-${tone}` : ''}`}>
      <span className="stat-label">{label}</span>
      <span className="stat-value mono">{value}</span>
      {sub && <span className="stat-sub">{sub}</span>}
    </div>
  )
}

const CARD_ICON = {
  'Strategy builder': SlidersHorizontal,
  'Payoff at expiry': ChartSpline,
  'Position size': Calculator,
  'Legs & Greeks': Sigma,
  'Price & support/resistance': ChartCandlestick,
  'Screening log': ClipboardCheck,
  'Open interest by strike': ChartNoAxesColumn,
  'Stop-loss plan': ShieldAlert,
  'Events before expiry': CalendarClock,
}

function Card({ title, sub, children, className = '' }) {
  const Icon = CARD_ICON[title]
  return (
    <section className={`card ${className}`}>
      <header className="card-head">
        <h2>{Icon && <Icon size={16} aria-hidden />}{title}</h2>
        {sub && <span className="muted small">{sub}</span>}
      </header>
      {children}
    </section>
  )
}

/** Where the full credit is kept and where the trade turns, in one short line. */
function keepLine(d, s) {
  const ce = d.legs.find((l) => l.side === 'CE')
  const pe = d.legs.find((l) => l.side === 'PE')
  if (ce && pe) return `Full credit between ${pe.strike} and ${ce.strike} at expiry. Breakevens ${num(s.breakeven_lower, 0)} and ${num(s.breakeven_upper, 0)}.`
  if (ce) return `Full credit below ${ce.strike} at expiry. Breakeven ${num(s.breakeven_upper, 0)}.`
  return `Full credit above ${pe.strike} at expiry. Breakeven ${num(s.breakeven_lower, 0)}.`
}

function prevClose(d) {
  const h = d.history ?? []
  if (!h.length) return null
  return h.length > 1 && h[h.length - 1].date === todayIso() ? h[h.length - 2].close : h[h.length - 1].close
}

function atmIv(d) {
  if (!d.chain?.length) return null
  const r = d.chain.reduce((a, b) => (Math.abs(b.strikePrice - d.spot) < Math.abs(a.strikePrice - d.spot) ? b : a))
  const ivs = [r.CE_IV, r.PE_IV].filter(Boolean)
  return ivs.length ? ivs.reduce((a, b) => a + b, 0) / ivs.length : null
}

export default function StockDetail() {
  const { symbol } = useParams()
  // Several expiry cycles are screened per stock; without ?expiry= the server picks the default one.
  const [params] = useSearchParams()
  const expiry = params.get('expiry') || undefined
  const navigate = useNavigate()
  const { data: screen } = useScreen()
  const { perTrade, capital, maxPct } = useBudget()
  const [d, setD] = useState(null)
  const [error, setError] = useState(null)
  const [lots, setLots] = useState(null)
  const [ticket, setTicket] = useState(false)

  // New symbol or expiry: clear and load. Newer screen for the same one: swap the data in silently.
  useEffect(() => {
    setD(null)
    setError(null)
  }, [symbol, expiry])
  useEffect(() => {
    let live = true
    rpc('get_trade_detail', expiry ? { symbol, expiry } : { symbol })
      .then((r) => live && (setD(r), setError(null)))
      .catch((e) => live && setError((prev) => prev ?? e.message))
    return () => { live = false }
  }, [symbol, expiry, screen?.generated_at])

  useEffect(() => {
    document.title = `${symbol} · Theta Desk`
    window.scrollTo(0, 0)
  }, [symbol])

  const s = d?.strategy
  const suggested = suggestLots(s?.margin, perTrade)
  const chosen = lots ?? Math.max(suggested, 1)
  useEffect(() => setLots(null), [symbol, expiry, perTrade])
  const cycles = (screen?.candidates ?? []).filter((c) => c.symbol === symbol && c.expiry)

  if (error)
    return (
      <div className="alert" role="alert">
        <AlertCircle size={18} aria-hidden /> Couldn't load {symbol}: {error}
        <Link className="btn" to="/">Back to setups</Link>
      </div>
    )
  if (!d) return <DetailSkeleton />

  const actionable = d.legs.length > 0
  const qty = (d.lot_size || 0) * chosen
  const used = s?.margin ? s.margin * chosen : 0
  const failed = d.checks.find((c) => c.status === 'fail')
  const pc = prevClose(d)
  const chg = pc ? ((d.spot - pc) / pc) * 100 : null

  return (
    <div className="detail">
      <div className="detail-top">
        <Link to="/" className="back">
          <ArrowLeft size={16} aria-hidden /> All setups
        </Link>
        <UpdatedTag ts={screen?.generated_at} refreshing={screen?.refreshing} />
      </div>

      <section className="hero">
        <div className="hero-main">
          <div className="hero-title">
            <h1 className="display">{d.symbol}</h1>
            <span className="quote-px num">{num(d.spot)}</span>
            {chg != null && (
              <span className={`quote-chg num ${chg > 0 ? 'pos' : chg < 0 ? 'neg' : 'muted'}`}>
                {signed(d.spot - pc, 2)} ({signedPct(chg)})
              </span>
            )}
            <div className="hero-tags">
              <ActionBadge action={d.action} />
              <SentimentBadge sentiment={d.sentiment} />
              <EventBadge events={d.events} expiry={d.expiry} />
            </div>
          </div>
          <dl className="facts-inline">
            <div>
              <dt>Expiry</dt>
              <dd>
                {cycles.length > 1 ? (
                  <span className="segmented small" role="group" aria-label="Expiry cycle">
                    {cycles.map((c) => (
                      <button
                        key={c.expiry}
                        className={c.expiry === d.expiry ? 'active' : ''}
                        aria-pressed={c.expiry === d.expiry}
                        onClick={() => navigate(`/stock/${encodeURIComponent(symbol)}?expiry=${c.expiry}`, { replace: true })}
                      >
                        {shortDate(c.expiry)} <span className="count num">{c.dte}d</span>
                      </button>
                    ))}
                  </span>
                ) : (
                  <>{shortDate(d.expiry)} <span className="muted num">({d.dte}d)</span></>
                )}
              </dd>
            </div>
            <div><dt>Lot</dt><dd className="num">{int(d.lot_size)}</dd></div>
            <div><dt>ATM IV</dt><dd className="num">{pct(atmIv(d))}</dd></div>
            <div><dt>PCR</dt><dd className="num">{num(d.pcr, 2)}</dd></div>
            <div><dt>Max pain</dt><dd className="num">{num(d.max_pain, 0)}</dd></div>
            <div><dt>Prev close</dt><dd className="num">{num(pc)}</dd></div>
          </dl>
          {actionable && s && (
            <>
              <ul className="order-lines" aria-label="Suggested orders">
                {d.legs.map((l) => (
                  <li key={l.side}>
                    <LegTag action="SELL" side={l.side} />
                    <b className="num">{d.symbol} {shortDate(d.expiry).toUpperCase()} {l.strike} {l.side}</b>
                    <span className="num">@ {rupee2(l.premium)}</span>
                    <span className="muted num">bid {num(l.bid)} / ask {num(l.ask)}</span>
                    <span className="muted num">Δ {num(Math.abs(l.delta), 3)}</span>
                    <span className="muted num">OI {int(l.oi)}</span>
                  </li>
                ))}
              </ul>
              <p className="keep-line">{keepLine(d, s)}</p>
            </>
          )}
        </div>
        {actionable && (
          <button className="btn primary lg" onClick={() => setTicket(true)} disabled={!s?.margin}>
            <ShieldCheck size={18} aria-hidden /> Review order
          </button>
        )}
      </section>

      {d.events?.length > 0 && (
        <Card title="Events before expiry" sub={`Corporate events up to the ${shortDate(d.expiry)} expiry`} className="ev-card">
          <EventTable events={d.events} showStock={false} label="Corporate events before expiry" />
        </Card>
      )}

      {!actionable && (
        <div className="alert neutral" role="status">
          <AlertCircle size={18} aria-hidden />
          <span>No trade this cycle. {failed ? `${failed.rule}: ${failed.detail}.` : ''}</span>
        </div>
      )}

      {actionable && s && (
        <>
          <section className="ledger" aria-label="Strategy metrics">
            <Stat label="POP" value={pct(s.pop)} sub="Profit at expiry (between breakevens)" tone={s.pop >= 75 ? 'good' : 'ok'} />
            <Stat label="Max profit probability" value={pct(s.max_profit_prob)} sub="Full premium kept (between strikes)" />
            <Stat label="Max profit" value={rupee(s.credit_per_share * qty)} sub={`${rupee2(s.credit_per_share)} × ${int(qty)} qty`} tone="good" />
            <Stat label="Margin required" value={s.margin ? rupee(s.margin * chosen) : '—'} sub={s.margin ? `${rupee(s.margin)} per lot` : 'SPAN data unavailable'} />
            <Stat label="ROI on margin" value={pct(s.roi_pct, 2)} sub={s.roi_annual_pct ? `${pct(s.roi_annual_pct)} annualised` : ''} />
            <Stat
              label="Breakeven"
              value={[s.breakeven_lower, s.breakeven_upper].filter(Boolean).map((v) => num(v, 0)).join(' – ')}
              sub={[s.breakeven_lower && `${pct(((s.breakeven_lower - d.spot) / d.spot) * 100)}`, s.breakeven_upper && `+${pct(((s.breakeven_upper - d.spot) / d.spot) * 100)}`].filter(Boolean).join(' / ') + ' from spot'}
            />
          </section>

          <Card title="Strategy builder" sub="Strikes, lots, target price and date recalculate live">
            <StrategyLab d={d} lots={chosen} />
          </Card>

          <div className="two-col wide-left">
            <Card title="Payoff at expiry" sub="Per lot at expiry">
              <PayoffChart d={d} lots={chosen} />
            </Card>

            <Card title="Position size" sub={`Up to ${rupee(perTrade)} per trade from your virtual account (${maxPct}% of ${rupee(capital)})`}>
              <div className="sizer">
                <div className="stepper" role="group" aria-label="Lots">
                  <button className="icon-btn" onClick={() => setLots(Math.max(1, chosen - 1))} aria-label="One lot fewer" disabled={chosen <= 1}>
                    <Minus size={18} />
                  </button>
                  <output className="mono" aria-live="polite">{chosen}</output>
                  <button className="icon-btn" onClick={() => setLots(chosen + 1)} aria-label="One lot more">
                    <Plus size={18} />
                  </button>
                </div>
                <p className="sizer-hint">
                  {suggested > 0
                    ? <>Suggested: <b className="mono">{suggested} lot{suggested > 1 ? 's' : ''}</b> fit your limit.</>
                    : <>One lot needs {rupee(s.margin)}, above your {rupee(perTrade)} limit. Raise the % in your wallet or free up funds.</>}
                </p>
                <div className="usage" aria-label={`Margin use ${pct((used / perTrade) * 100, 0)} of per-trade limit`}>
                  <div className="usage-track"><div className={`usage-fill ${used > perTrade ? 'over' : ''}`} style={{ transform: `scaleX(${Math.min(1, used / perTrade || 0)})` }} /></div>
                  <span className="mono small">{rupee(used)} of {rupee(perTrade)}</span>
                </div>
                <dl className="breakdown">
                  <div><dt>SPAN</dt><dd className="mono">{rupee((s.span ?? 0) * chosen)}</dd></div>
                  <div><dt>Exposure ({pct(s.exposure_pct)} per leg)</dt><dd className="mono">{rupee((s.exposure ?? 0) * chosen)}</dd></div>
                  <div className="total"><dt>Total margin</dt><dd className="mono">{rupee(used)}</dd></div>
                  <div><dt>Premium received</dt><dd className="mono up">+{rupee(s.credit_per_share * qty)}</dd></div>
                  <div><dt>Capital used</dt><dd className="mono">{capital ? pct((used / capital) * 100) : '—'}</dd></div>
                </dl>
                <p className="muted small">SPAN from NSE file {screen?.span_source ?? ''}. Your broker's figure may differ slightly.</p>
              </div>
            </Card>
          </div>

          <Card title="Legs & Greeks" sub="Greeks per share for the short position; probabilities at expiry from NSE IV">
            <div className="table-scroll">
              <table className="legs">
                <thead>
                  <tr>
                    <th>Leg</th><th className="num">Premium</th><th className="num">Bid / Ask</th><th className="num">IV</th>
                    <th className="num">Delta</th><th className="num">Gamma</th><th className="num">Theta / day</th><th className="num">Vega</th>
                    <th className="num">OI</th><th className="num">From spot</th><th className="num">Expires ITM</th><th className="num">Touch prob.</th>
                  </tr>
                </thead>
                <tbody>
                  {d.legs.map((l) => (
                    <tr key={l.side}>
                      <td data-label="Leg"><LegTag action="SELL" side={l.side} /> <b className="mono">{l.strike}</b></td>
                      <td data-label="Premium" className="num mono">{rupee2(l.premium)}</td>
                      <td data-label="Bid / Ask" className="num mono">{num(l.bid)} / {num(l.ask)}</td>
                      <td data-label="IV" className="num mono">{pct(l.iv)}</td>
                      <td data-label="Delta" className="num mono">{signed(-l.delta, 3)}</td>
                      <td data-label="Gamma" className="num mono">{signed(-l.gamma, 4)}</td>
                      <td data-label="Theta / day" className="num mono up">{signed(-l.theta, 2)}</td>
                      <td data-label="Vega" className="num mono">{signed(-l.vega, 2)}</td>
                      <td data-label="OI" className="num mono">{int(l.oi)} <span className="muted">({signed(l.oi_change, 0)})</span></td>
                      <td data-label="From spot" className="num mono">{signed(l.distance_pct)}%</td>
                      <td data-label="Expires ITM" className="num mono">{pct(l.prob_itm)}</td>
                      <td data-label="Touch prob." className={`num mono ${l.prob_touch >= 30 ? 'warn' : ''}`}>{pct(l.prob_touch)}</td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr>
                    <td>Net for {chosen} lot{chosen > 1 ? 's' : ''}</td>
                    <td data-label="Premium" className="num mono">{rupee(s.credit_per_share * qty)}</td>
                    <td /><td />
                    <td data-label="Net delta" className="num mono">{signed(s.net_delta * qty, 1)}</td>
                    <td data-label="Net gamma" className="num mono">{signed(s.net_gamma * qty, 2)}</td>
                    <td data-label="Theta / day" className="num mono up">{rupee(s.net_theta * qty)}</td>
                    <td data-label="Vega" className="num mono">{rupee(s.net_vega * qty)}</td>
                    <td colSpan={4} className="muted small">Theta: ₹ earned per day · Vega: ₹ lost per +1 IV point</td>
                  </tr>
                </tfoot>
              </table>
            </div>
          </Card>
        </>
      )}

      <div className="two-col">
        <Card title="Price & support/resistance" sub="6 months daily · zones need 2+ swing touches">
          <PriceChart d={d} />
        </Card>
        <Card title="Screening log" sub="Rule checks">
          <Checklist checks={d.checks} sentiment={d.sentiment} />
        </Card>
      </div>

      <Card title="Open interest by strike" sub={`${shortDate(d.expiry)} expiry. Calls red, puts green`}>
        <OIChart d={d} />
      </Card>

      {actionable && d.sl && (
        <Card title="Stop-loss plan">
          <SLTimeline sl={d.sl} />
        </Card>
      )}

      {ticket && <OrderModal d={d} lots={chosen} onClose={() => setTicket(false)} />}
    </div>
  )
}
