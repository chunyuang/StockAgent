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
    chunkSizeWarningLimit: 600,
    rollupOptions: {
      output: {
        manualChunks(id) {
          // element-plus组件按需已由auto-import处理，这里拆分大依赖
          if (id.includes('node_modules/element-plus/')) {
            // element-plus子模块拆分：es/locale和es/utils较小，保持主chunk
            if (id.includes('element-plus/es/locale') || id.includes('element-plus/es/utils')) {
              return 'el-shared';
            }
            return 'element-plus';
          }
          // echarts单独chunk(不再与vendor捆绑，避免单个chunk过大)
          if (id.includes('node_modules/echarts/')) {
            return 'echarts';
          }
          if (id.includes('node_modules/vue-echarts/')) {
            return 'echarts';
          }
          // 核心vendor
          if (id.includes('node_modules/vue/') || id.includes('node_modules/@vue/')) {
            return 'vendor';
          }
          if (id.includes('node_modules/vue-router/')) {
            return 'vendor';
          }
          if (id.includes('node_modules/pinia/')) {
            return 'vendor';
          }
          if (id.includes('node_modules/axios/')) {
            return 'vendor';
          }
          // zrender是echarts的渲染引擎，跟echarts走
          if (id.includes('node_modules/zrender/')) {
            return 'echarts';
          }
        },
      },
    },
  },
})
