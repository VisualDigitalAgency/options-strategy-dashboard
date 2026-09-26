import { useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { Eye, EyeOff, Hourglass } from 'lucide-react'
import { useAuth } from '../auth'
import { rpc } from '../rpc'
import DialMark from '../components/DialMark'
import { SHOW_KEY as BROKER_POPUP_KEY } from '../components/BrokerOnboarding'

const MIN = 10

function Shell({ title, lede, children, foot }) {
  return (
    <div className="auth-page">
      <div className="auth-card">
        <Link to="/login" className="brand auth-brand" aria-label="Theta Desk">
          <DialMark />
          <span className="wordmark">Theta Desk</span>
        </Link>
        <h1 className="auth-title">{title}</h1>
        {lede && <p className="auth-lede">{lede}</p>}
        {children}
      </div>
      {foot && <p className="auth-foot">{foot}</p>}
    </div>
  )
}

function Field({ label, id, hint, ...input }) {
  return (
    <div className="auth-field">
      <label htmlFor={id}>{label}</label>
      <input id={id} name={id} {...input} aria-describedby={hint ? `${id}-hint` : undefined} />
      {hint && <p id={`${id}-hint`} className="auth-hint">{hint}</p>}
    </div>
  )
}

function PasswordField({ label, id, autoComplete, value, onChange, hint }) {
  const [show, setShow] = useState(false)
  return (
    <div className="auth-field">
      <label htmlFor={id}>{label}</label>
      <div className="auth-pw">
        <input id={id} name={id} type={show ? 'text' : 'password'} autoComplete={autoComplete} required
          value={value} onChange={(e) => onChange(e.target.value)} aria-describedby={hint ? `${id}-hint` : undefined} />
        <button type="button" className="auth-eye" onClick={() => setShow((s) => !s)}
          aria-label={show ? 'Hide password' : 'Show password'} aria-pressed={show}>
          {show ? <EyeOff size={16} aria-hidden /> : <Eye size={16} aria-hidden />}
        </button>
      </div>
      {hint && <p id={`${id}-hint`} className="auth-hint">{hint}</p>}
    </div>
  )
}

function useSubmit(fn) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const submit = async (e) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await fn()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }
  return { busy, error, submit }
}

export function Login() {
  const { login } = useAuth()
  const nav = useNavigate()
  const next = new URLSearchParams(useLocation().search).get('next')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const { busy, error, submit } = useSubmit(async () => {
    await login(email, password)
    try { sessionStorage.setItem(BROKER_POPUP_KEY, '1') } catch { /* storage blocked: popup just won't show */ }
    nav(next && next.startsWith('/') && !next.startsWith('//') ? next : '/', { replace: true })
  })
  return (
    <Shell title="Sign in" lede="Your virtual account, screener and auto-trade settings."
      foot={<>No account yet? <Link to="/register">Request access</Link></>}>
      <form className="auth-form" onSubmit={submit} noValidate>
        <Field label="Email" id="email" type="email" autoComplete="username" inputMode="email" required
          value={email} onChange={(e) => setEmail(e.target.value)} />
        <PasswordField label="Password" id="password" autoComplete="current-password" value={password} onChange={setPassword} />
        {error && <p className="form-error" role="alert">{error}</p>}
        <button className="btn primary lg auth-submit" disabled={busy || !email || !password}>
          {busy ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </Shell>
  )
}

export function Register() {
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [done, setDone] = useState(null)
  const { busy, error, submit } = useSubmit(async () => {
    const r = await rpc('auth_register', { name, email, password })
    setDone(r.message)
  })
  if (done) {
    return (
      <Shell title="Request sent" foot={<Link to="/login">Back to sign in</Link>}>
        <div className="auth-done">
          <Hourglass size={20} aria-hidden />
          <p>{done}</p>
        </div>
      </Shell>
    )
  }
  return (
    <Shell title="Request access" lede="An admin approves each new account. You start with ₹10,00,000 of virtual capital."
      foot={<>Already approved? <Link to="/login">Sign in</Link></>}>
      <form className="auth-form" onSubmit={submit} noValidate>
        <Field label="Name" id="name" autoComplete="name" required value={name} onChange={(e) => setName(e.target.value)} />
        <Field label="Email" id="email" type="email" autoComplete="email" inputMode="email" required
          value={email} onChange={(e) => setEmail(e.target.value)} />
        <PasswordField label="Password" id="new-password" autoComplete="new-password" value={password}
          onChange={setPassword} hint={`At least ${MIN} characters. Leave out your name and email.`} />
        {error && <p className="form-error" role="alert">{error}</p>}
        <button className="btn primary lg auth-submit" disabled={busy || !name || !email || password.length < MIN}>
          {busy ? 'Sending…' : 'Request access'}
        </button>
      </form>
    </Shell>
  )
}

export function ChangePassword() {
  const { user, changePassword, logout } = useAuth()
  const nav = useNavigate()
  const forced = user?.must_change_password
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [again, setAgain] = useState('')
  const [saved, setSaved] = useState(false)
  const mismatch = again && next !== again
  const { busy, error, submit } = useSubmit(async () => {
    if (next !== again) throw new Error('The new passwords differ')
    await changePassword(current, next)
    setSaved(true)
    if (forced) nav('/', { replace: true })
  })
  return (
    <Shell title={forced ? 'Set a new password' : 'Change password'}
      lede={forced ? 'You signed in with a temporary password. Choose your own to continue.'
        : 'Other devices signed in to this account will be signed out.'}
      foot={forced ? <button type="button" className="link-btn" onClick={logout}>Sign out</button>
        : <Link to="/virtual">Back to the app</Link>}>
      <form className="auth-form" onSubmit={submit} noValidate>
        <input type="text" name="username" autoComplete="username" value={user?.email || ''} readOnly hidden />
        <PasswordField label={forced ? 'Temporary password' : 'Current password'} id="current-password"
          autoComplete="current-password" value={current} onChange={setCurrent} />
        <PasswordField label="New password" id="new-password" autoComplete="new-password" value={next}
          onChange={setNext} hint={`At least ${MIN} characters. Leave out your name and email.`} />
        <PasswordField label="New password again" id="confirm-password" autoComplete="new-password" value={again}
          onChange={setAgain} />
        {mismatch && <p className="form-error" role="alert">The new passwords differ</p>}
        {error && <p className="form-error" role="alert">{error}</p>}
        {saved && !forced && <p className="form-ok" role="status">Password changed. Other devices are signed out.</p>}
        <button className="btn primary lg auth-submit" disabled={busy || !current || next.length < MIN || next !== again}>
          {busy ? 'Saving…' : 'Change password'}
        </button>
      </form>
    </Shell>
  )
}
