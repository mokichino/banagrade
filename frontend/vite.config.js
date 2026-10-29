import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  // Shift labels and chart ticks follow the viewer's clock and locale; pin both so tests do not depend on the machine.
  test: { env: { TZ: 'Asia/Manila', LC_ALL: 'en_US.UTF-8' } },
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