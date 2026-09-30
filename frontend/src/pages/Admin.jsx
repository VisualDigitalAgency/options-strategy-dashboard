import { useCallback, useEffect, useState } from 'react'
import { AlertTriangle, Check, Copy, KeyRound, UserCheck, UserX } from 'lucide-react'
import { rpc } from '../rpc'
import { useAuth } from '../auth'
import { dateTime } from '../format'
import Modal, { ConfirmDialog } from '../components/Modal'

const STATUS = { pending: 'Waiting', active: 'Active', rejected: 'Rejected', disabled: 'Disabled' }

const ACTION = {
  register: 'Requested access', register_duplicate: 'Sign-up refused: email already registered', register_same_device: 'Sign-up refused: browser already has an account', login: 'Signed in',
  login_failed: 'Wrong password', login_blocked: 'Sign-in blocked (not active)', logout: 'Signed out',
  user_active: 'Approved or re-enabled', user_rejected: 'Rejected', user_disabled: 'Disabled',
  password_changed: 'Changed password', password_change_failed: 'Wrong current password',
  email_code_sent: 'Sign-up code emailed', email_verified: 'Confirmed email', email_verify_failed: 'Wrong sign-up code',
  mail_failed: 'Email failed to send', signup_unblocked: 'Unblocked sign-up',
  password_reset: 'Temporary password issued', admin_password_set: 'Admin password set', sqlite_import: 'Data imported',
  password_reset_requested: 'Password reset requested', password_reset_self: 'Reset own password',
  broker_connected: 'Broker connected', broker_disconnected: 'Broker disconnected',
  broker_order_placed: 'Real order placed', broker_order_failed: 'Real order failed',
  broker_order_unknown: 'Real order: outcome unknown',
  broker_sl_alert_installed: 'Stop-loss alert set', broker_sl_alert_cancelled: 'Stop-loss alert removed',
  broker_sl_alert_failed: 'Stop-loss alert failed',
}
// An event added later without a label reads as words, not as its raw key.
const actionLabel = (a) => ACTION[a] ?? a.charAt(0).toUpperCase() + a.slice(1).replaceAll('_', ' ')

// What each button does, in the words the confirm dialog uses.
const CONFIRM = {
  rejected: { title: 'Reject this request?', label: 'Reject', danger: true,
    body: (u) => `${u.name} can't sign in. You can approve the request later.` },
  disabled: { title: 'Disable this account?', label: 'Disable', danger: true,
    body: (u) => `${u.name} is signed out everywhere at once, and auto-trade stops for them. Their positions stay as they are.` },
  reset: { title: 'Issue a temporary password?', label: 'Issue password', danger: false,
    body: (u) => `${u.name} is signed out everywhere and must set a new password after signing in with the temporary one.` },
}

function UserRow({ u, me, onAct }) {
  const self = u.id === me.id
  return (
    <tr>
      <td>
        <b>{u.name}</b>{u.role === 'admin' && <span className="chip admin-chip">Admin</span>}
        <span className="muted small block">{u.email}</span>
      </td>
      <td data-label="Status"><span className={`chip st-${u.status}`}>{STATUS[u.status]}</span>
        {u.must_change_password && <span className="muted small block">Temporary password</span>}
        {u.links.map((l) => (
          <span key={l.kind + l.user_id} className={`dup-flag ${l.kind}`}
            title={l.kind === 'browser' ? 'Signed up or signed in from the same browser' : `Same network (${l.ip})`}>
            <AlertTriangle size={13} aria-hidden /> Same {l.kind} as {l.name}
          </span>
        ))}</td>
      <td className="mono small" data-label="Signed up">{dateTime(u.created_at)}</td>
      <td className="mono small" data-label="Last sign-in">{u.last_login_at ? dateTime(u.last_login_at) : '—'}</td>
      <td className="admin-act-cell">
        <div className="admin-actions">
          {self ? <span className="muted small">You</span> : (
            <>
              {u.status === 'pending' && (
                <>
                  <button className="btn small primary" onClick={() => onAct(u, 'active')}><UserCheck size={15} aria-hidden /> Approve</button>
                  <button className="btn small ghost" onClick={() => onAct(u, 'rejected')}><UserX size={15} aria-hidden /> Reject</button>
                </>
              )}
              {u.status === 'active' && (
                <>
                  <button className="btn small ghost" onClick={() => onAct(u, 'reset')}><KeyRound size={15} aria-hidden /> Reset password</button>
                  <button className="btn small ghost danger-text" onClick={() => onAct(u, 'disabled')}>Disable</button>
                </>
              )}
              {(u.status === 'disabled' || u.status === 'rejected') && (
                <button className="btn small ghost" onClick={() => onAct(u, 'active')}>
                  <UserCheck size={15} aria-hidden /> {u.status === 'rejected' ? 'Approve' : 'Re-enable'}
                </button>
              )}
            </>
          )}
        </div>
      </td>
    </tr>
  )
}

function TempPassword({ user, password, onClose }) {
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(password)
      setCopied(true)
    } catch { /* clipboard blocked: the password is on screen to copy by hand */ }
  }
  return (
    <Modal title="Temporary password" onClose={onClose} width={440}>
      <p className="confirm-body">Give this to {user.name} yourself. It is shown once and can't be looked up again.</p>
      <div className="temp-pw">
        <code>{password}</code>
        <button className="btn small ghost" onClick={copy}>{copied ? <Check size={15} aria-hidden /> : <Copy size={15} aria-hidden />} {copied ? 'Copied' : 'Copy'}</button>
      </div>
      <div className="modal-actions"><button className="btn primary" onClick={onClose}>Done</button></div>
    </Modal>
  )
}

export default function Admin() {
  const { user: me } = useAuth()
  const [users, setUsers] = useState(null)
  const [log, setLog] = useState(null)
  const [tab, setTab] = useState('users')
  const [pending, setPending] = useState(null) // {u, action}
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [temp, setTemp] = useState(null)
  const [blocked, setBlocked] = useState(null)
  const [note, setNote] = useState(null)

  const load = useCallback(async () => {
    try {
      const [u, l, b] = await Promise.all([rpc('admin_list_users'), rpc('admin_audit_log', { limit: 100 }),
        rpc('admin_list_blocked')])
      setUsers(u)
      setLog(l)
      setBlocked(b)
    } catch (e) {
      setError(e.message)
    }
  }, [])
  useEffect(() => { load() }, [load])

  const act = async (u, action) => {
    setError(null)
    if (action === 'active') return run(u, action) // approving needs no confirm step
    setPending({ u, action })
  }
  const run = async (u, action) => {
    setBusy(true)
    try {
      if (action === 'reset') {
        const r = await rpc('admin_reset_password', { target_id: u.id })
        setTemp({ user: u, password: r.temporary_password })
      } else {
        await rpc('admin_set_status', { target_id: u.id, status: action })
      }
      setPending(null)
      await load()
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  const unblock = async (b) => {
    setBusy(true)
    setError(null)
    setNote(null)
    try {
      const r = await rpc('admin_unblock_signup', { target_id: b.id })
      setNote(r.sent ? `Unblocked ${b.email}. A new code is on its way; they have 14 days to confirm.`
        : `Unblocked ${b.email}, but the code email failed. They can use "Send a new code" once mail works.`)
      await load()
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  const waiting = users?.filter((u) => u.status === 'pending').length ?? 0
  return (
    <div className="detail">
      <header className="page-head">
        <div>
          <h1 className="display">Admin</h1>
          <p className="lede">{users ? (waiting ? `${waiting} request${waiting > 1 ? 's' : ''} waiting for approval.` : 'No requests waiting.') : 'Loading users…'}</p>
        </div>
      </header>
      {error && !pending && <div className="alert" role="alert"><AlertTriangle size={18} aria-hidden /> {error}</div>}

      <div className="tab-line admin-tabs" role="tablist">
        <button role="tab" aria-selected={tab === 'users'} className={tab === 'users' ? 'active' : ''} onClick={() => setTab('users')}>
          Users {users && <span className="muted">{users.length}</span>}
        </button>
        <button role="tab" aria-selected={tab === 'blocked'} className={tab === 'blocked' ? 'active' : ''} onClick={() => setTab('blocked')}>
          Blocked sign-ups {blocked?.length > 0 && <span className="muted">{blocked.length}</span>}
        </button>
        <button role="tab" aria-selected={tab === 'log'} className={tab === 'log' ? 'active' : ''} onClick={() => setTab('log')}>Activity</button>
      </div>

      {tab === 'users' && (
        <div className="card table-scroll">
          <table className="admin-table">
            <thead><tr><th>User</th><th>Status</th><th>Signed up</th><th>Last sign-in</th><th /></tr></thead>
            <tbody>{users?.map((u) => <UserRow key={u.id} u={u} me={me} onAct={act} />)}</tbody>
          </table>
        </div>
      )}
      {tab === 'blocked' && (
        <>
          <p className="muted small">Sign-ups that didn&apos;t confirm their email within 14 days. Unblock someone support has
            checked: they get a new code and 14 more days, then confirm and wait for approval as usual.</p>
          {note && <p className="form-ok" role="status">{note}</p>}
          <div className="card table-scroll">
            <table className="admin-table">
              <thead><tr><th>User</th><th>Signed up</th><th /></tr></thead>
              <tbody>
                {blocked?.length === 0 && <tr><td colSpan={3} className="muted small">No blocked sign-ups.</td></tr>}
                {blocked?.map((b) => (
                  <tr key={b.id}>
                    <td><b>{b.name}</b><span className="muted small block">{b.email}</span></td>
                    <td className="mono small" data-label="Signed up">{dateTime(b.created_at)}</td>
                    <td className="admin-act-cell"><div className="admin-actions">
                      <button className="btn small ghost" disabled={busy} onClick={() => unblock(b)}>
                        <UserCheck size={15} aria-hidden /> Unblock and resend code
                      </button>
                    </div></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      {tab === 'log' && (
        <div className="card table-scroll">
          <table className="admin-table admin-log">
            <thead><tr><th>When</th><th>What</th><th>Who</th><th>Account</th><th>IP</th></tr></thead>
            <tbody>
              {log?.map((e) => (
                <tr key={e.id} className={e.action.endsWith('failed') || e.action === 'login_blocked' ? 'warn-row' : ''}>
                  <td className="mono small">{dateTime(e.ts)}</td>
                  <td>{actionLabel(e.action)}</td>
                  <td className="small" data-label="Who">{e.actor || '—'}</td>
                  <td className="small" data-label="Account">{e.target || '—'}</td>
                  <td className="mono small" data-label="IP">{e.ip || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {pending && (
        <ConfirmDialog title={CONFIRM[pending.action].title} body={CONFIRM[pending.action].body(pending.u)}
          confirmLabel={CONFIRM[pending.action].label} danger={CONFIRM[pending.action].danger} busy={busy} error={error}
          onConfirm={() => run(pending.u, pending.action)} onClose={() => { setPending(null); setError(null) }} />
      )}
      {temp && <TempPassword {...temp} onClose={() => setTemp(null)} />}
    </div>
  )
}
