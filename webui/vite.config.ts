import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

const API_PORT = process.env.VITE_API_PORT || '37241'
const API_TARGET = `http://localhost:${API_PORT}`

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
        target: API_TARGET,
        ws: true,
      },
    },
  },
})
