import { useCallback, useEffect, useState } from 'react'
import { AlertTriangle } from 'lucide-react'
import { rpc } from '../rpc'
import { dateTime, rupee } from '../format'
import Modal from './Modal'

// Owner only (#194): a user's capital grants, and taking one back. The server owns the rules: the
// row stays so the task can't be paid again, and a coin exchange can't be revoked.
export default function GrantsDialog({ user, onClose, onChanged }) {
  const [grants, setGrants] = useState(null)
  const [target, setTarget] = useState(null)
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const load = useCallback(
    () => rpc('admin_user_grants', { target_id: user.id }).then(setGrants).catch((e) => setError(e.message)),
    [user.id],
  )
  useEffect(() => { load() }, [load])

  const revoke = async (e) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await rpc('admin_revoke_grant', { target_id: user.id, grant_id: target.id, reason: reason.trim() })
      setTarget(null)
      setReason('')
      await load()
      onChanged?.()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const valid = reason.trim().length >= 3 && reason.trim().length <= 200
  return (
    <Modal title={`Capital grants: ${user.name}`} onClose={onClose} width={640}>
      {error && <p className="form-error" role="alert">{error}</p>}
      {grants === null && !error && <p className="muted">Loading…</p>}
      {grants?.length === 0 && <p className="muted">No grants yet.</p>}
      {grants?.length > 0 && (
        <table className="admin-table">
          <thead><tr><th>Reward</th><th>Amount</th><th>Paid</th><th>Status</th><th><span className="sr-only">Action</span></th></tr></thead>
          <tbody>
            {grants.map((g) => (
              <tr key={g.id}>
                <td>{g.label}</td>
                <td data-label="Amount" className="num">{rupee(g.amount)}</td>
                <td data-label="Paid" className="mono small">{dateTime(g.at)}</td>
                <td data-label="Status">{g.revoked ? <span className="chip st-rejected">Revoked</span> : 'Active'}</td>
                <td className="admin-act-cell">
                  {g.revocable
                    ? <button className="btn small ghost danger-text" onClick={() => { setTarget(g); setError(null) }}>Revoke</button>
                    : !g.revoked && <span className="muted small">Can't be revoked</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {target && (
        <form onSubmit={revoke} className="grant-revoke">
          <p className="confirm-body">
            Take back <b>{rupee(target.amount)}</b> ({target.label}) from {user.name}? Their capital drops by that amount,
            and they can never earn this reward again.
          </p>
          <p className="muted small"><AlertTriangle size={14} aria-hidden /> If this leaves too little capital for their open
            positions, the margin check may square some off.</p>
          <div className="field">
            <label htmlFor="grant-reason">Reason (kept in the activity log)</label>
            <input id="grant-reason" style={{ width: '100%' }} value={reason} onChange={(e) => setReason(e.target.value)}
              maxLength={200} autoFocus />
          </div>
          <div className="modal-actions">
            <button type="button" className="btn ghost" onClick={() => { setTarget(null); setReason('') }}>Cancel</button>
            <button type="submit" className="btn danger" disabled={busy || !valid}>{busy ? 'Working…' : 'Revoke grant'}</button>
          </div>
        </form>
      )}
      {!target && <div className="modal-actions"><button className="btn primary" onClick={onClose}>Done</button></div>}
    </Modal>
  )
}
