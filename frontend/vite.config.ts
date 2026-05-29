import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [
    vue(),
    // 自动导入 Vue/VueRouter/Pinia API
    AutoImport({
      imports: ['vue', 'vue-router', 'pinia'],
      resolvers: [ElementPlusResolver()],
      dts: 'src/auto-imports.d.ts',
    }),
    // 自动导入 Element Plus 组件
    Components({
      resolvers: [ElementPlusResolver()],
      dts: 'src/components.d.ts',
    }),
  ],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
    },
  },
  css: {
    preprocessorOptions: {
      scss: {
        // 使用新的 Sass API 消除弃用警告
        api: 'modern-compiler',
      },
    },
  },
  server: {
    port: 5174,
    host: true,
    proxy: {
      // API 代理 — 指向Web节点(8000)，开发时Vite(5174)代理API请求
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      // WebSocket 代理
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,
        changeOrigin: true,
      },
    },
    allowedHosts: [
      'localhost',
      'qibalili.cn',
      'og824md55716.vicp.fun',
      '.qibalili.cn'  // 允许所有子域名
    ]
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          'element-plus': ['element-plus'],
          // echarts拆分问题: 把echarts和vue-echarts放在同一个chunk会导致
          // "Ho[o] is not a constructor"错误(渲染器注册时序问题)
          // 修复: 不单独拆分echarts, 让它内联到各组件chunk中
          'vendor': ['vue', 'vue-router', 'pinia', 'axios', 'echarts', 'vue-echarts'],
        },
      },
    },
  },
})
