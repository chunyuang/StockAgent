/**
 * 应用入口
 */

import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import zhCn from 'element-plus/dist/locale/zh-cn.mjs'

import App from './App.vue'
import router from './router'
import { pinia } from './stores'

// 样式
import './styles/main.scss'

// ==================== 创建应用 ====================

const app = createApp(App)

// ==================== 注册插件 ====================

app.use(pinia)
app.use(router)
app.use(ElementPlus, { locale: zhCn })

// ==================== 挂载 ====================

// 全局错误处理器 - 捕获组件渲染错误
app.config.errorHandler = (err, _instance, info) => {
  console.error('[Vue Error]', info, err)
  // 写到全局变量方便调试
  const w = window as any
  w.__vueErrors = w.__vueErrors || []
  w.__vueErrors.push({ info: String(info), error: String(err), stack: (err as any)?.stack?.substring(0, 200) })
}

app.mount('#app')
