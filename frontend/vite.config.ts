import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// BACKEND_URL is set by docker-compose (http://backend:8000); defaults to
// localhost for native dev.
export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    proxy: {
      '/api': {
        target: process.env.BACKEND_URL ?? 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
