import { Suspense, lazy, useState } from 'react'
import { Link, NavLink, Route, Routes, useLocation } from 'react-router-dom'
import { Briefcase, LayoutGrid, PiggyBank, RefreshCw, Wallet } from 'lucide-react'
import { SettingsProvider, useBudget } from './settings'
import { rupeeShort } from './format'
import { ScreenProvider, useScreen } from './screen'
import SettingsPanel from './components/SettingsPanel'
import ThemeToggle from './components/ThemeToggle'
import DetailSkeleton from './components/DetailSkeleton'
import Overview from './pages/Overview'

const StockDetail = lazy(() => import('./pages/StockDetail'))
const Portfolio = lazy(() => import('./pages/Portfolio'))
const VirtualAccount = lazy(() => import('./pages/VirtualAccount'))

const NAV = [
  { to: '/', label: 'Screener', icon: LayoutGrid, end: true },
  { to: '/portfolio', label: 'Portfolio', icon: Briefcase },
  { to: '/virtual', label: 'Virtual account', icon: PiggyBank },
]

function DialMark() {
  return (
    <svg className="dial-mark" viewBox="0 0 32 32" aria-hidden>
      <circle cx="16" cy="16" r="14.5" className="dm-ring" />
      <path d="M5 11 C 12 11.5, 20 14, 26.5 25" className="dm-curve" />
      <line x1="16" y1="16" x2="16" y2="5.5" className="dm-hand" />
      <circle cx="16" cy="16" r="2" className="dm-pin" />
    </svg>
  )
}

function TopBar() {
  const { data, loading, load } = useScreen()
  const { account } = useBudget()
  const [open, setOpen] = useState(false)
  const { pathname } = useLocation()
  const onScreener = pathname === '/' || pathname.startsWith('/stock/')

  return (
    <header className="topbar">
      <div className="topbar-inner">
        <Link to="/" className="brand" aria-label="Theta Desk home">
          <DialMark />
          <span className="wordmark">Theta Desk</span>
        </Link>
        <nav className="main-nav" aria-label="Main">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) => (isActive || (to === '/' && pathname.startsWith('/stock/')) ? 'active' : '')}
            >
              <Icon size={16} aria-hidden /> {label}
            </NavLink>
          ))}
        </nav>
        <div className="topbar-actions">
          {onScreener && data?.generated_at && (
            <span className="status" title={`SPAN file: ${data.span_source}`}>
              <span className="dot" aria-hidden /> Updated{' '}
              {new Date(data.generated_at * 1000).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })}
            </span>
          )}
          <ThemeToggle />
          <button className="wallet-btn" onClick={() => setOpen((o) => !o)} aria-expanded={open} aria-label="Wallet: virtual account funds">
            <Wallet size={16} aria-hidden />
            <span className="wallet-amt num">{account ? rupeeShort(account.available_margin) : '—'}</span>
            <span className="wallet-sub">free</span>
          </button>
          {onScreener && (
            <button className="btn" onClick={() => load(true)} disabled={loading}>
              <RefreshCw size={16} className={loading ? 'spin' : ''} aria-hidden />
              <span className="btn-label">{loading ? 'Screening…' : 'Refresh'}</span>
            </button>
          )}
        </div>
      </div>
      {open && <SettingsPanel onClose={() => setOpen(false)} />}
    </header>
  )
}

const lazyPage = (Page) => (
  <Suspense fallback={<DetailSkeleton />}>
    <Page />
  </Suspense>
)

export default function App() {
  return (
    <SettingsProvider>
      <ScreenProvider>
        <TopBar />
        <main className="page">
          <Routes>
            <Route path="/" element={<Overview />} />
            <Route path="/stock/:symbol" element={lazyPage(StockDetail)} />
            <Route path="/portfolio" element={lazyPage(Portfolio)} />
            <Route path="/virtual" element={lazyPage(VirtualAccount)} />
          </Routes>
        </main>
      </ScreenProvider>
    </SettingsProvider>
  )
}
