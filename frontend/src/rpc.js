// Same-origin: Vite proxies /rpc to the API in dev, Caddy does it in production. The session
// cookie is HttpOnly, so this code never sees it; the browser sends it on every call.
const RPC_URL = '/rpc'
let nextId = 1

export const NOT_SIGNED_IN = -32001
export const MUST_CHANGE = -32004
export const UNVERIFIED = -32005 // right password, email not confirmed yet: show the code form

export class RpcError extends Error {
  constructor(message, code) {
    super(message)
    this.code = code
  }
}

// A 503 never comes from the API itself: it is the proxy saying no backend is up (a redeploy or
// restart in progress), so the call never ran and resending it is safe, even for orders.
const RETRY_DELAYS_MS = [1000, 2000, 4000]

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

export async function rpc(method, params = {}) {
  const payload = JSON.stringify({ jsonrpc: '2.0', id: nextId++, method, params })
  let res
  for (let attempt = 0; ; attempt++) {
    res = await fetch(RPC_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: payload,
    })
    if (res.status !== 503 || attempt >= RETRY_DELAYS_MS.length) break
    await sleep(RETRY_DELAYS_MS[attempt])
  }
  let body
  try {
    body = await res.json()
  } catch {
    const why = res.status === 503 || res.status === 502
      ? 'The server is restarting or not running'
      : `The server answered ${res.status}`
    throw new RpcError(`${why}; try again in a moment`, res.status)
  }
  if (body.error) {
    const { code, message } = body.error
    // Session ended (signed out elsewhere, disabled, expired): the auth layer shows the login page.
    if (code === NOT_SIGNED_IN || code === MUST_CHANGE) window.dispatchEvent(new CustomEvent('auth:changed'))
    throw new RpcError(message, code)
  }
  return body.result
}
