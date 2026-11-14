import { defineConfig } from 'vite'

// Forward /api calls to the FastAPI server on port 8000.
export default defineConfig({
  server: { port: 5173, proxy: { '/api': 'http://127.0.0.1:8003' } },
})
