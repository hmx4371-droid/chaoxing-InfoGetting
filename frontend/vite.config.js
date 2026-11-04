import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 前端 dev server 固定 5273（5173 常被别的项目占用）。
// /api       → Java 后端 8080（业务数据）
// /collector → Python 采集服务 8801（登录/账号；密码只在这条链路上，不经过 Java）
export default defineConfig({
  plugins: [vue()],
  server: {
    host: '127.0.0.1',
    port: 5273,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8080',
        changeOrigin: true,
      },
      '/collector': {
        target: 'http://127.0.0.1:8801',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/collector/, ''),
      },
    },
  },
})
