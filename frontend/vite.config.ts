import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/v1': {
        // Override per worktree, e.g. BIKER_API_URL=http://localhost:8001 npm run dev -- --port 5174
        target: process.env.BIKER_API_URL ?? 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
