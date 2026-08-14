import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// dev server 端口 3000；/api（含 WS 升级）代理到后端（13 蓝图：同源，无需 CORS）
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 3000,
    proxy: {
      '/api': { target: 'http://localhost:8000', changeOrigin: true, ws: true },
    },
  },
})
