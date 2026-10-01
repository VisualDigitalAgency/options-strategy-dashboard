import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The API is proxied so the page and /rpc share one origin: the session cookie stays
// same-site and no CORS is needed. Caddy does the same in production.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/rpc': 'http://127.0.0.1:8000',
      '/healthz': 'http://127.0.0.1:8000',
      '^/c/': 'http://127.0.0.1:8000',
    },
  },
})
