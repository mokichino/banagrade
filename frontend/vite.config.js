import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': process.env.BANAGRADE_API_TARGET || 'http://127.0.0.1:8000',
      '/ws': {
        target: (process.env.BANAGRADE_API_TARGET || 'http://127.0.0.1:8000').replace(/^http/, 'ws'),
        ws: true
      }
    }
  }
})