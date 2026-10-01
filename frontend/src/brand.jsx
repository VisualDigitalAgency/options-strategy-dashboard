import { useEffect, useSyncExternalStore } from 'react'
import { rpc } from './rpc'
import DialMark from './components/DialMark'

// The app's name and logo (issue #133). The owner changes them under Admin, so nothing else in the
// frontend spells the name out: read it from useBrand(). Loaded once per page from app_info; a
// null logo means the built-in dial mark and /favicon.svg.

const FALLBACK = 'Theta Desk' // only until app_info answers
let state = { name: FALLBACK, logo: null, reader: null, autoApprove: true } // reader: pages a signed-out visitor may open (#163)
let loading = null
const subs = new Set()

function applyIcons() {
  const icon = document.querySelector('link[rel="icon"]')
  if (icon) {
    icon.href = state.logo ? `/brand/favicon.png?v=${state.logo}` : '/favicon.svg'
    icon.type = state.logo ? 'image/png' : 'image/svg+xml'
  }
  let touch = document.querySelector('link[rel="apple-touch-icon"]')
  if (state.logo && !touch) {
    touch = Object.assign(document.createElement('link'), { rel: 'apple-touch-icon' })
    document.head.appendChild(touch)
  }
  if (touch) {
    if (state.logo) touch.href = `/brand/touch.png?v=${state.logo}`
    else touch.remove()
  }
}

export function setBrand(next) {
  state = { name: next.name || FALLBACK, logo: next.logo || null, reader: next.reader_pages ?? state.reader, autoApprove: next.auto_approve ?? state.autoApprove }
  applyIcons()
  subs.forEach((f) => f())
}

const subscribe = (f) => { subs.add(f); return () => subs.delete(f) }

function load() {
  if (!loading) loading = rpc('app_info').then(setBrand).catch(() => {})
}

export function useBrand() {
  useEffect(load, [])
  return useSyncExternalStore(subscribe, () => state)
}

// Sets the tab title to "<page> · <app name>", or just the name.
export function useTitle(page) {
  const { name } = useBrand()
  useEffect(() => { document.title = page ? `${page} · ${name}` : name }, [page, name])
}

export function Logo() {
  const { logo } = useBrand()
  return logo ? <img className="dial-mark brand-logo" src={`/brand/logo.png?v=${logo}`} alt="" /> : <DialMark />
}
