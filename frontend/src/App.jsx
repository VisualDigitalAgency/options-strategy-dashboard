import { Suspense, lazy, useEffect, useRef, useState } from 'react'
import { Link, Navigate, NavLink, Route, Routes, useLocation } from 'react-router-dom'
import { ArrowDownRight, ArrowUpRight, Bot, Briefcase, CalendarDays, GraduationCap, KeyRound, LayoutGrid, LogOut, Minus, PiggyBank, Plug, ShieldCheck, Trophy, Wallet } from 'lucide-react'
import { SettingsProvider, useBudget } from './settings'
import { num, pct, rupeeShort, signedPct, signedRupee } from './format'
import { ScreenProvider, useScreen } from './screen'
import { useMarketClock } from './market'
import SettingsPanel from './components/SettingsPanel'
import ThemeToggle from './components/ThemeToggle'
import DetailSkeleton from './components/DetailSkeleton'
import Overview from './pages/Overview'
import { AuthProvider, can, useAuth } from './auth'
import { markSeen, seenLevel } from './levelSeen'
import { ChangePassword, ForgotPassword, Login, Register, ResetPassword } from './pages/AuthPages'
import BrokerOnboarding from './components/BrokerOnboarding'
import { Logo, useBrand } from './brand'

const StockDetail = lazy(() => import('./pages/StockDetail'))
const Portfolio = lazy(() => import('./pages/Portfolio'))
const VirtualAccount = lazy(() => import('./pages/VirtualAccount'))
const MarketCalendar = lazy(() => import('./pages/MarketCalendar'))
const Admin = lazy(() => import('./pages/Admin'))
const Broker = lazy(() => import('./pages/Broker'))
const BrokerAccount = lazy(() => import('./pages/BrokerAccount'))
const BrokerCallback = lazy(() => import('./pages/BrokerCallback'))
const Learn = lazy(() => import('./pages/Learn').then((m) => ({ default: m.Learn })))
const Progress = lazy(() => import('./pages/Progress'))
const Welcome = lazy(() => import('./pages/Welcome'))
const Lesson = lazy(() => import('./pages/Learn').then((m) => ({ default: m.Lesson })))

const NAV = [
  { to: '/', label: 'Screener', icon: LayoutGrid, end: true },
  { to: '/portfolio', label: 'Portfolio', icon: Briefcase },
  { to: '/calendar', label: 'Calendar', icon: CalendarDays, feature: 'market_calendar' },
  { to: '/virtual', label: 'Virtual account', short: 'Account', icon: PiggyBank },
  { to: '/broker', label: 'Broker', icon: Plug },
  { to: '/learn', label: 'Learn', icon: GraduationCap },
  { to: '/progress', label: 'Progress', icon: Trophy, badge: true },
]



function TickerItem({ c, hidden }) {
  // Direction comes from the day's move, not sentiment; POP stays neutral so a high POP never reads red.
  const chg = c.prev_close ? ((c.spot - c.prev_close) / c.prev_close) * 100 : null
  const Icon = chg > 0 ? ArrowUpRight : chg < 0 ? ArrowDownRight : Minus
  const tone = chg > 0 ? 'pos' : chg < 0 ? 'neg' : 'muted'
  return (
    <li aria-hidden={hidden || undefined}>
      <Link to={`/stock/${encodeURIComponent(c.symbol)}?expiry=${c.expiry}`} className="ticker-item" tabIndex={hidden ? -1 : undefined}>
        <span className="ticker-sym">{c.symbol}</span>
        <span className="num ticker-spot">{num(c.spot)}</span>
        <span className={`ticker-chg num ${tone}`}>
          <Icon size={12} aria-hidden /> {signedPct(chg)}
        </span>
        <span className="ticker-pop num">POP {pct(c.strategy.pop, 0)}</span>
      </Link>
    </li>
  )
}

function TickerBar() {
  const { data } = useScreen()
  const { account } = useBudget()
  const sorted = (data?.candidates ?? [])
    .filter((c) => c.legs?.length && c.strategy)
    .sort((a, b) => (b.strategy.pop ?? 0) - (a.strategy.pop ?? 0))
  // Several expiry cycles per stock: show each stock once, at its highest-POP cycle.
  const items = sorted.filter((c, i) => sorted.findIndex((o) => o.symbol === c.symbol) === i)
  const pnl = account?.unrealized_pnl ?? 0
  const booked = account?.realized_pnl ?? 0
  // Roughly constant speed whatever the item count: ~3.5s per item.
  const duration = `${Math.max(items.length, 4) * 3.5}s`
  return (
    <div className="ticker-bar">
      <div className="ticker-inner">
        <div className="ticker-viewport" aria-label="Setups by POP, scrolling">
          {items.length === 0 ? (
            <span className="ticker-empty muted">Scanning setups…</span>
          ) : (
            <ul className="ticker-track" style={{ '--ticker-duration': duration }}>
              {items.map((c) => <TickerItem key={c.symbol} c={c} />)}
              {/* Second copy makes the loop seamless; hidden from screen readers and tab order */}
              {items.map((c) => <TickerItem key={`dup-${c.symbol}`} c={c} hidden />)}
            </ul>
          )}
        </div>
        <div className="ticker-right">
          <span title="P&L locked in from closed trades">Booked <b className={`num ${booked > 0 ? 'pos' : booked < 0 ? 'neg' : ''}`}>{account ? signedRupee(booked) : '—'}</b></span>
          <span className="ticker-sep" aria-hidden>|</span>
          <span title="P&L on open positions at the last price; changes until you exit">Unbooked <b className={`num ${pnl > 0 ? 'pos' : pnl < 0 ? 'neg' : ''}`}>{account ? signedRupee(pnl) : '—'}</b></span>
          <span className="ticker-sep" aria-hidden>|</span>
          <span>Margin used: <b className="num">{account ? rupeeShort(account.used_margin) : '—'}</b></span>
        </div>
      </div>
    </div>
  )
}

function UserMenu() {
  const { user, logout } = useAuth()
  const [open, setOpen] = useState(false)
  const ref = useRef(null)
  useEffect(() => {
    if (!open) return
    const close = (e) => (e.key === 'Escape' || (e.type === 'mousedown' && !ref.current?.contains(e.target))) && setOpen(false)
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', close)
    return () => {
      document.removeEventListener('mousedown', close)
      document.removeEventListener('keydown', close)
    }
  }, [open])
  const initials = user.name.split(' ').map((w) => w[0]).slice(0, 2).join('').toUpperCase()
  return (
    <div className="user-menu" ref={ref}>
      <button className="user-btn" onClick={() => setOpen((o) => !o)} aria-expanded={open} aria-haspopup="menu"
        aria-label={`Account menu for ${user.name}`}>
        {initials}
      </button>
      {open && (
        <div className="user-pop" role="menu">
          <div className="user-pop-head">
            <b>{user.name}</b>
            <span className="muted small">{user.email}</span>
          </div>
          {can(user, 'manage_users') && (
            <Link role="menuitem" to="/admin" onClick={() => setOpen(false)}><ShieldCheck size={16} aria-hidden /> Admin</Link>
          )}
          <Link role="menuitem" to="/account/password" onClick={() => setOpen(false)}><KeyRound size={16} aria-hidden /> Change password</Link>
          <button role="menuitem" onClick={logout}><LogOut size={16} aria-hidden /> Sign out</button>
        </div>
      )}
    </div>
  )
}

function TopBar() {
  const { account, auto } = useBudget()
  const { user } = useAuth()
  const clock = useMarketClock()
  const [open, setOpen] = useState(false)
  const { pathname } = useLocation()
  const { name } = useBrand()
  // A level reached since this browser last celebrated one lights a dot on Progress (issue #126).
  const seen = seenLevel()
  if (seen === null && user?.level) markSeen(user.level)
  const levelUp = seen !== null && user?.level > seen

  return (
    <header className="topbar">
      <div className="topbar-inner">
        <Link to="/" className="brand" aria-label={`${name} home`}>
          <Logo />
          <span className="wordmark">{name}</span>
        </Link>
        <nav className="main-nav" aria-label="Main">
          {NAV.filter((n) => !n.feature || can(user, n.feature)).map(({ to, label, short, icon: Icon, end, badge }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) => (isActive || (to === '/' && pathname.startsWith('/stock/')) ? 'active' : '')}
            >
              <Icon size={16} aria-hidden />{' '}
              {short ? <><span className="nav-full">{label}</span><span className="nav-short" aria-hidden>{short}</span></> : label}
              {badge && levelUp && <span className="nav-dot" role="status" aria-label="New level reached" />}
            </NavLink>
          ))}
        </nav>
        <div className="topbar-actions">
          <span className={`status mkt-${clock.key}`} title={clock.note}>
            <span className={`mkt-dot ${clock.key}`} aria-hidden />
            NSE {clock.label.toLowerCase()} <span className="num">{clock.time}</span> IST
          </span>
          {auto?.enabled && can(user, 'autotrade') && (
            <Link to="/virtual#auto" className="auto-chip" title={`Auto-trade on, runs daily at ${auto.run_at} IST`}>
              <Bot size={15} aria-hidden /> <span className="auto-chip-label">Auto</span> <span className="num">{auto.run_at}</span>
            </Link>
          )}
          <ThemeToggle />
          <button className="wallet-btn" onClick={() => setOpen((o) => !o)} aria-expanded={open} aria-label="Wallet: virtual account funds">
            <Wallet size={16} aria-hidden />
            <span className="wallet-amt num">{account ? rupeeShort(account.available_margin) : '—'}</span>
            <span className="wallet-sub">free</span>
          </button>
          <UserMenu />
        </div>
      </div>
      <TickerBar />
      {open && <SettingsPanel onClose={() => setOpen(false)} />}
    </header>
  )
}

const lazyPage = (Page) => (
  <Suspense fallback={<DetailSkeleton />}>
    <Page />
  </Suspense>
)

function Splash() {
  return (
    <div className="auth-page" aria-busy="true">
      <Logo />
    </div>
  )
}

function SignedIn() {
  const { user } = useAuth()
  if (user.must_change_password) {
    return (
      <Routes>
        <Route path="*" element={<ChangePassword />} />
      </Routes>
    )
  }
  if (!user.nickname) return lazyPage(Welcome) // first login (#121): nickname + leaderboard choice
  return (
    <SettingsProvider>
      <ScreenProvider>
        <TopBar />
        <BrokerOnboarding />
        <main className="page">
          <Routes>
            <Route path="/" element={<Overview />} />
            <Route path="/stock/:symbol" element={lazyPage(StockDetail)} />
            <Route path="/portfolio" element={lazyPage(Portfolio)} />
            {can(user, 'market_calendar') && <Route path="/calendar" element={lazyPage(MarketCalendar)} />}
            <Route path="/virtual" element={lazyPage(VirtualAccount)} />
            <Route path="/broker" element={lazyPage(Broker)} />
            <Route path="/broker/account" element={lazyPage(BrokerAccount)} />
            <Route path="/broker/zerodha/callback" element={lazyPage(BrokerCallback)} />
            <Route path="/learn" element={lazyPage(Learn)} />
            <Route path="/learn/:slug" element={lazyPage(Lesson)} />
            <Route path="/progress" element={lazyPage(Progress)} />
            <Route path="/account/password" element={<ChangePassword />} />
            {can(user, 'manage_users') && <Route path="/admin" element={lazyPage(Admin)} />}
            <Route path="/login" element={<Navigate to="/" replace />} />
            <Route path="/register" element={<Navigate to="/" replace />} />
            <Route path="/forgot-password" element={<Navigate to="/" replace />} />
            <Route path="/reset-password" element={<Navigate to="/" replace />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </main>
      </ScreenProvider>
    </SettingsProvider>
  )
}

// Lessons are public, so search and shared links land on real content with a way in.
function PublicShell({ children }) {
  const { name } = useBrand()
  return (
    <>
      <header className="topbar">
        <div className="topbar-inner">
          <Link to="/learn" className="brand" aria-label={`${name} lessons`}>
            <Logo />
            <span className="wordmark">{name}</span>
          </Link>
          <div className="public-bar-actions">
            <ThemeToggle />
            <Link to="/login" className="btn ghost small">Sign in</Link>
            <Link to="/register" className="btn primary small">Join free</Link>
          </div>
        </div>
      </header>
      <main className="page">{children}</main>
    </>
  )
}

function SignedOut() {
  const { pathname, search } = useLocation()
  const here = pathname + search
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/register" element={<Register />} />
      <Route path="/forgot-password" element={<ForgotPassword />} />
      <Route path="/reset-password" element={<ResetPassword />} />
      <Route path="/learn" element={<PublicShell>{lazyPage(Learn)}</PublicShell>} />
      <Route path="/learn/:slug" element={<PublicShell>{lazyPage(Lesson)}</PublicShell>} />
      <Route path="*" element={<Navigate to={here === '/' ? '/login' : `/login?next=${encodeURIComponent(here)}`} replace />} />
    </Routes>
  )
}

function Gate() {
  const { user } = useAuth()
  if (user === undefined) return <Splash />
  return user ? <SignedIn /> : <SignedOut />
}

export default function App() {
  return (
    <AuthProvider>
      <Gate />
    </AuthProvider>
  )
}
