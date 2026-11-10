import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Outside Docker the nginx /api proxy does not exist, so proxy /api to the backend here for `npm run dev` / `npm run preview`.
const apiProxy = {
  '/api': {
    target: process.env.VITE_API_TARGET || 'http://localhost:8000',
    changeOrigin: true,
    rewrite: (path: string) => path.replace(/^\/api/, ''),
  },
}

export default defineConfig({
  plugins: [react()],
  server: { proxy: apiProxy },
  preview: { proxy: apiProxy },
})
