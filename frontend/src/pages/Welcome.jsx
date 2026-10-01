import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { GraduationCap } from 'lucide-react'
import { rpc } from '../rpc'
import { useAuth } from '../auth'
import { Logo } from '../brand'

// First-login onboarding (#121): a public nickname and the leaderboard choice, then Level 1.
// Shown once, until the account has a nickname. #167: a suggested nickname and a live format check,
// and a trade built before joining (Builder draft) is where they land next.
const NICK = /^[A-Za-z0-9_]{3,20}$/
const suggest = (name, n) => {
  const base = (name || '').split(' ')[0].replace(/[^A-Za-z0-9_]/g, '').slice(0, 14)
  return base.length >= 2 ? `${base}${n}` : ''
}
const hasDraft = () => { try { return !!localStorage.getItem('builder:draft') } catch { return false } }

export default function Welcome() {
  const { user, refresh } = useAuth()
  const nav = useNavigate()
  const [seed] = useState(() => Math.floor(10 + Math.random() * 90))
  const [typed, setNickname] = useState(null) // null until they edit: the suggestion shows meanwhile
  const nickname = typed ?? suggest(user?.name, seed)
  const [optIn, setOptIn] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await rpc('profile_set', { nickname: nickname.trim(), leaderboard_opt_in: optIn })
      nav(hasDraft() ? '/builder' : '/learn', { replace: true })
      await refresh()
    } catch (err) {
      setError(err.message)
      setBusy(false)
    }
  }

  return (
    <div className="auth-page">
      <div className="auth-card">
        <div className="auth-brand"><Logo /></div>
        <h1 className="auth-title">Welcome{user?.name ? `, ${user.name.split(' ')[0]}` : ''}</h1>
        <p className="auth-lede">You start at <b>Level 1 · Learner</b> with a ₹10 lakh paper-trading account. Pick a
          nickname: it's the only name other people ever see.</p>
        <form className="auth-form" onSubmit={submit} noValidate>
          <label>
            Nickname
            <input value={nickname} onChange={(e) => setNickname(e.target.value)} autoFocus required
              minLength={3} maxLength={20} pattern="[A-Za-z0-9_]{3,20}" placeholder="e.g. ThetaSeller" autoComplete="nickname" />
            <span className={`small ${nickname && !NICK.test(nickname.trim()) ? 'neg' : 'muted'}`} role="status">
              {nickname && !NICK.test(nickname.trim())
                ? (nickname.trim().length < 3 ? 'At least 3 characters' : 'Only letters, digits and _, up to 20')
                : '3 to 20 letters, digits or _. Change the suggestion if you like.'}
            </span>
          </label>
          <label className="check-row">
            <input type="checkbox" checked={optIn} onChange={(e) => setOptIn(e.target.checked)} />
            Show me on the monthly paper-trading leaderboard (nickname only)
          </label>
          {error && <p className="form-error" role="alert">{error}</p>}
          <button className="btn primary" disabled={busy || !NICK.test(nickname.trim())}>
            <GraduationCap size={16} aria-hidden /> {busy ? 'Saving…' : hasDraft() ? 'Start, and place my trade' : 'Start Level 1'}
          </button>
        </form>
      </div>
      <p className="auth-foot muted small">Educational, paper trading only. You can change both later.</p>
    </div>
  )
}
