// Same-origin: Vite proxies /rpc to the API in dev, Caddy does it in production. The session
// cookie is HttpOnly, so this code never sees it; the browser sends it on every call.
const RPC_URL = '/rpc'
let nextId = 1

export const NOT_SIGNED_IN = -32001
export const MUST_CHANGE = -32004

export class RpcError extends Error {
  constructor(message, code) {
    super(message)
    this.code = code
  }
}

export async function rpc(method, params = {}) {
  const res = await fetch(RPC_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'same-origin',
    body: JSON.stringify({ jsonrpc: '2.0', id: nextId++, method, params }),
  })
  let body
  try {
    body = await res.json()
  } catch {
    throw new RpcError(`The server answered ${res.status}; try again in a moment`, res.status)
  }
  if (body.error) {
    const { code, message } = body.error
    // Session ended (signed out elsewhere, disabled, expired): the auth layer shows the login page.
    if (code === NOT_SIGNED_IN || code === MUST_CHANGE) window.dispatchEvent(new CustomEvent('auth:changed'))
    throw new RpcError(message, code)
  }
  return body.result
}
