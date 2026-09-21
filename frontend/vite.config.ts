/// <reference types="vitest" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// BACKEND_URL is set by docker-compose (http://backend:8000); defaults to
// localhost for native dev.
export default defineConfig({
  plugins: [react()],
  // Node environment only: the units under test are pure functions over plain objects
  // (lib/), so no DOM and no component-testing library is needed. Rendering stays
  // untested — see docs/specs/2026-09-20-graph-progress-coloring-design.md §9.
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts'],
  },
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
