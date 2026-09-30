import { useEffect, useState } from 'react'
import { Globe } from 'lucide-react'

// TradingView's free economic-calendar widget, embedded as a sandboxed iframe (no third-party
// script runs on our origin; the CSP allows only this frame host). Display only: the events never
// reach the backend or the screener.
const HOST = 'https://www.tradingview-widget.com'

const src = (theme) => `${HOST}/embed-widget/events/?locale=en#${encodeURIComponent(JSON.stringify({
  colorTheme: theme,
  isTransparent: true,
  width: '100%',
  height: '100%',
  locale: 'en',
  importanceFilter: '0,1',
  countryFilter: 'in,us',
}))}`

const currentTheme = () => (document.documentElement.dataset.theme === 'light' ? 'light' : 'dark')

export default function EconomicCalendar() {
  const [theme, setTheme] = useState(currentTheme)

  // Follow the theme toggle, which only flips data-theme on <html>.
  useEffect(() => {
    const obs = new MutationObserver(() => setTheme(currentTheme()))
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    return () => obs.disconnect()
  }, [])

  return (
    <section className="card econ-cal" aria-labelledby="econ-cal">
      <header className="card-head">
        <h2 id="econ-cal"><Globe size={16} aria-hidden />Economic calendar</h2>
        <span className="muted small">India &amp; US, medium and high importance · TradingView</span>
      </header>
      <iframe
        key={theme}
        src={src(theme)}
        title="Economic calendar (TradingView)"
        loading="lazy"
        referrerPolicy="no-referrer"
        sandbox="allow-scripts allow-same-origin allow-popups"
      />
    </section>
  )
}
