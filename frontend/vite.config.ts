import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'

// https://vitejs.dev/config/
export default defineConfig({
  define: {
    __DEV__: process.env.NODE_ENV !== 'production',
  },
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
    // 【v2.9.90 P0 修复】回退 v2.9.89 element-plus 过度拆分
    // 原因: 把 element-plus 拆成 el-table/el-form/el-overlay/element-plus 多个 chunk 后
    // 子组件之间存在 ESM 循环依赖, 浏览器执行时报错:
    // ReferenceError: Cannot access 'qo' before initialization @ el-overlay.js
    // 导致整个页面白屏 (#app 为空, Vue 无法 mount)。
    // 回归到单 element-plus chunk(857KB), 牺牲单chunk大小换可用性。
    // E2E 是连 dev server 跑的, 没暴露此问题 —— 后续需补强 build 产物冒烟测试。
    chunkSizeWarningLimit: 900,
    rollupOptions: {
      output: {
        manualChunks(id) {
          // element-plus 整体作为一个 chunk(仅把 locale/utils 拆出作为共享)
          if (id.includes('node_modules/element-plus/')) {
            if (id.includes('element-plus/es/locale') || id.includes('element-plus/es/utils')) {
              return 'el-shared';
            }
            return 'element-plus';
          }
          // echarts 单独 chunk
          if (id.includes('node_modules/echarts/') || id.includes('node_modules/vue-echarts/') || id.includes('node_modules/zrender/')) {
            return 'echarts';
          }
          // 核心 vendor
          if (id.includes('node_modules/vue/') || id.includes('node_modules/@vue/')
              || id.includes('node_modules/vue-router/') || id.includes('node_modules/pinia/')
              || id.includes('node_modules/axios/')) {
            return 'vendor';
          }
        },
      },
    },
  },
})
