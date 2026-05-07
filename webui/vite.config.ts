import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

const API_URL = process.env.VITE_API_BASE || `http://localhost:${process.env.VITE_API_PORT || '37241'}`

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/ws': {
        target: API_URL,
        ws: true,
        changeOrigin: true,
      },
    },
  },
})
