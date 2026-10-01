import { useRef, useState } from 'react'
import { ImageUp, RotateCcw } from 'lucide-react'
import { rpc } from '../rpc'
import { Logo, setBrand, useBrand } from '../brand'

// Owner only (issue #133): the app's name and logo. The server re-encodes the upload to PNG and
// makes the favicon from it; only PNG and WebP are accepted.

const TYPES = ['image/png', 'image/webp']
const MAX = 1024 * 1024

export default function BrandSettings() {
  const brand = useBrand()
  const [name, setName] = useState(brand.name)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [saved, setSaved] = useState(null)
  const file = useRef(null)

  const run = async (fn, msg) => {
    setBusy(true); setError(null); setSaved(null)
    try { setBrand(await fn()); setSaved(msg) } catch (e) { setError(e.message) } finally { setBusy(false) }
  }
  const saveName = () => run(() => rpc('admin_set_brand_name', { name }), 'Name saved')
  const upload = (f) => {
    if (file.current) file.current.value = ''
    if (!f) return
    if (!TYPES.includes(f.type)) return setError('Upload a PNG or WebP image')
    if (f.size > MAX) return setError('The image must be 1 MB or smaller')
    run(async () => {
      const res = await fetch('/brand/logo', { method: 'POST', headers: { 'Content-Type': f.type }, credentials: 'same-origin', body: f })
      let body = null
      try { body = await res.json() } catch { /* not JSON */ }
      if (!body?.result) throw new Error(body?.error?.message || 'Upload failed, try again')
      return body.result
    }, 'Logo uploaded')
  }
  const reset = () => run(() => rpc('admin_reset_logo'), 'Back to the built-in logo')

  return (
    <div className="card brand-settings">
      <h3>Branding</h3>
      <p className="muted small">Only you (the owner) can change these. They show on every page, in emails and on share cards.</p>
      <div className="brand-preview" aria-label="Preview">
        <span className="brand"><Logo /><span className="wordmark">{name || brand.name}</span></span>
        {brand.logo && <img className="favicon-preview" src={`/brand/favicon.png?v=${brand.logo}`} alt="Favicon" width="32" height="32" />}
      </div>
      <div className="field">
        <label htmlFor="brand-name">App name</label>
        <input id="brand-name" value={name} maxLength={40} onChange={(e) => setName(e.target.value)} />
      </div>
      <div className="modal-actions">
        <button className="btn primary" onClick={saveName} disabled={busy || !name.trim() || name.trim() === brand.name}>Save name</button>
      </div>
      <input ref={file} type="file" accept="image/png,image/webp" hidden onChange={(e) => upload(e.target.files[0])} aria-label="Logo file" />
      <p className="muted small">Logo: PNG or WebP, square works best, up to 1 MB. The favicon is made from it.</p>
      <div className="modal-actions">
        <button className="btn" onClick={() => file.current?.click()} disabled={busy}><ImageUp size={15} aria-hidden /> Upload logo</button>
        {brand.logo && <button className="btn" onClick={reset} disabled={busy}><RotateCcw size={15} aria-hidden /> Use built-in logo</button>}
      </div>
      {error && <p className="neg small" role="alert">{error}</p>}
      {saved && <p className="pos small" role="status">{saved}</p>}
    </div>
  )
}
