import { useState } from 'react'
import { Copy, Download, Share2, X } from 'lucide-react'
import { rpc } from '../rpc'
import { useBrand } from '../brand'

// Share dialog for an achievement card (issue #126). The card is made on the server when the user
// asks for a link, so its preview never changes afterwards; % return is off unless ticked.

export default function ShareCard({ kind, refNo, label, onClose }) {
  const [showReturn, setShowReturn] = useState(false)
  const [slug, setSlug] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [copied, setCopied] = useState(false)
  const { name: appName } = useBrand()

  const make = async () => {
    setBusy(true); setError(null)
    try { setSlug((await rpc('card_create', { kind, ref: refNo, show_return: showReturn })).slug) }
    catch (e) { setError(e.message) }
    finally { setBusy(false) }
  }
  const url = slug ? `${window.location.origin}/c/${slug}` : ''
  const text = `${label} on ${appName}, learning option selling with paper trading.`
  const enc = encodeURIComponent
  const copy = async () => {
    try { await navigator.clipboard.writeText(url); setCopied(true) } catch { /* clipboard blocked */ }
  }

  return (
    <div className="overlay" role="dialog" aria-modal="true" aria-labelledby="share-h">
      <div className="modal share-modal">
        <div className="modal-head">
          <h2 id="share-h"><Share2 size={18} aria-hidden /> Share: {label}</h2>
          <button className="icon-btn" onClick={onClose} aria-label="Close"><X size={18} /></button>
        </div>
        <label className="share-opt">
          <input type="checkbox" checked={showReturn} onChange={(e) => { setShowReturn(e.target.checked); setSlug(null) }} />
          Show my paper-trading % return
        </label>
        <p className="muted small">The card shows your nickname, never your email or any rupee amount.</p>
        {error && <p className="neg small" role="alert">{error}</p>}
        {!slug ? (
          <div className="modal-actions"><button className="btn primary" onClick={make} disabled={busy}>{busy ? 'Making…' : 'Make share link'}</button></div>
        ) : (
          <>
            <img className="share-preview" src={`/c/${slug}.png`} alt={`${label} card`} width="1200" height="630" />
            <div className="share-links">
              <a className="btn" href={`https://wa.me/?text=${enc(`${text} ${url}`)}`} target="_blank" rel="noreferrer">WhatsApp</a>
              <a className="btn" href={`https://x.com/intent/post?text=${enc(text)}&url=${enc(url)}`} target="_blank" rel="noreferrer">X</a>
              <a className="btn" href={`https://t.me/share/url?url=${enc(url)}&text=${enc(text)}`} target="_blank" rel="noreferrer">Telegram</a>
              <a className="btn" href={`/c/${slug}.png`} download={`${kind}-${refNo}.png`}><Download size={15} aria-hidden /> Image</a>
              <button className="btn" onClick={copy}><Copy size={15} aria-hidden /> {copied ? 'Copied' : 'Copy link'}</button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
