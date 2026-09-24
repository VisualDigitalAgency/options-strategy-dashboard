const RPC_URL = 'http://localhost:8000/rpc'
let nextId = 1

export async function rpc(method, params = {}) {
  const res = await fetch(RPC_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ jsonrpc: '2.0', id: nextId++, method, params }),
  })
  const body = await res.json()
  if (body.error) throw new Error(body.error.message)
  return body.result
}
