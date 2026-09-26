import { useEffect, useState } from 'react'
import { Moon, Sun } from 'lucide-react'
import { savePref } from '../auth'

const KEY = 'options-screener-theme'
const media = window.matchMedia('(prefers-color-scheme: light)')

function saved() {
  try {
    const t = localStorage.getItem(KEY)
    return t === 'light' || t === 'dark' ? t : null
  } catch {
    return null
  }
}

export default function ThemeToggle() {
  const [theme, setTheme] = useState(() => document.documentElement.dataset.theme || 'dark')

  useEffect(() => {
    document.documentElement.dataset.theme = theme
  }, [theme])

  useEffect(() => {
    // Follow the OS setting until the user picks a theme explicitly.
    const onChange = (e) => !saved() && setTheme(e.matches ? 'light' : 'dark')
    media.addEventListener('change', onChange)
    return () => media.removeEventListener('change', onChange)
  }, [])

  const dark = theme === 'dark'
  const toggle = () => {
    const next = dark ? 'light' : 'dark'
    setTheme(next)
    savePref({ theme: next })
    try {
      localStorage.setItem(KEY, next)
    } catch {
      /* storage blocked: choice lasts for this page only */
    }
  }

  return (
    <button
      type="button"
      role="switch"
      aria-checked={dark}
      aria-label="Dark mode"
      title={dark ? 'Switch to light mode' : 'Switch to dark mode'}
      className="theme-switch"
      onClick={toggle}
    >
      <Sun size={14} aria-hidden className="ts-sun" />
      <Moon size={14} aria-hidden className="ts-moon" />
      <span className="ts-thumb" aria-hidden />
    </button>
  )
}
