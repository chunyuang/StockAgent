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

app.mount('#app')
