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
    chunkSizeWarningLimit: 800,
    rollupOptions: {
      output: {
        manualChunks(id) {
          // element-plus子模块拆分：按功能组拆分避免单chunk过大(v2.9.89)
          if (id.includes('node_modules/element-plus/')) {
            if (id.includes('element-plus/es/locale') || id.includes('element-plus/es/utils')) {
              return 'el-shared';
            }
            // 表格组件(通常较大)
            if (id.includes('element-plus/es/components/table') || id.includes('element-plus/es/components/virtual-table')) {
              return 'el-table';
            }
            // 表单组件
            if (id.includes('element-plus/es/components/form') || id.includes('element-plus/es/components/input')
                || id.includes('element-plus/es/components/select') || id.includes('element-plus/es/components/checkbox')
                || id.includes('element-plus/es/components/radio') || id.includes('element-plus/es/components/switch')
                || id.includes('element-plus/es/components/slider') || id.includes('element-plus/es/components/time-picker')
                || id.includes('element-plus/es/components/date-picker') || id.includes('element-plus/es/components/cascader')) {
              return 'el-form';
            }
            // 弹出层/对话框
            if (id.includes('element-plus/es/components/dialog') || id.includes('element-plus/es/components/drawer')
                || id.includes('element-plus/es/components/popover') || id.includes('element-plus/es/components/tooltip')
                || id.includes('element-plus/es/components/message-box') || id.includes('element-plus/es/components/notification')) {
              return 'el-overlay';
            }
            return 'element-plus';
          }
          // echarts单独chunk
          if (id.includes('node_modules/echarts/') || id.includes('node_modules/vue-echarts/') || id.includes('node_modules/zrender/')) {
            return 'echarts';
          }
          // 核心vendor
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
