/**
 * 主题状态管理
 * 
 * 支持 Light/Dark 模式切换，自动保存用户偏好
 */

import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'

export type ThemeMode = 'light' | 'dark' | 'system'

const THEME_STORAGE_KEY = 'stock-agent-theme'

export const useThemeStore = defineStore('theme', () => {
  // ==================== 状态 ====================
  
  // 用户选择的主题模式
  const mode = ref<ThemeMode>(getStoredTheme())
  
  // 系统是否偏好暗色模式
  const systemPrefersDark = ref(getSystemPreference())
  
  // ==================== 计算属性 ====================
  
  // 实际应用的主题（考虑系统偏好）
  const isDark = computed(() => {
    if (mode.value === 'system') {
      return systemPrefersDark.value
    }
    return mode.value === 'dark'
  })
  
  // 当前主题名称
  const themeName = computed(() => isDark.value ? 'dark' : 'light')
  
  // ==================== 方法 ====================
  
  /**
   * 设置主题模式
   */
  function setTheme(newMode: ThemeMode): void {
    mode.value = newMode
    localStorage.setItem(THEME_STORAGE_KEY, newMode)
    applyTheme()
  }
  
  /**
   * 切换主题（Light <-> Dark）
   */
  function toggleTheme(): void {
    if (isDark.value) {
      setTheme('light')
    } else {
      setTheme('dark')
    }
  }
  
  /**
   * 应用主题到 DOM
   */
  function applyTheme(): void {
    const html = document.documentElement
    
    if (isDark.value) {
      html.classList.add('dark')
      html.style.colorScheme = 'dark'
    } else {
      html.classList.remove('dark')
      html.style.colorScheme = 'light'
    }
    
    // 更新 Element Plus 主题
    updateElementPlusTheme()
  }
  
  /**
   * 更新 Element Plus 主题变量
   */
  function updateElementPlusTheme(): void {
    const root = document.documentElement
    
    if (isDark.value) {
      // 暗色模式 Element Plus 变量
      root.style.setProperty('--el-bg-color', '#1e293b')
      root.style.setProperty('--el-bg-color-page', '#0f172a')
      root.style.setProperty('--el-bg-color-overlay', '#1e293b')
      root.style.setProperty('--el-text-color-primary', '#f1f5f9')
      root.style.setProperty('--el-text-color-regular', '#cbd5e1')
      root.style.setProperty('--el-text-color-secondary', '#94a3b8')
      root.style.setProperty('--el-text-color-placeholder', '#64748b')
      root.style.setProperty('--el-border-color', '#334155')
      root.style.setProperty('--el-border-color-light', '#1e293b')
      root.style.setProperty('--el-border-color-lighter', '#1e293b')
      root.style.setProperty('--el-fill-color', '#334155')
      root.style.setProperty('--el-fill-color-light', '#1e293b')
      root.style.setProperty('--el-fill-color-lighter', '#0f172a')
      root.style.setProperty('--el-fill-color-blank', '#1e293b')
      root.style.setProperty('--el-mask-color', 'rgba(0, 0, 0, 0.6)')
    } else {
      // 浅色模式 Element Plus 变量
      root.style.setProperty('--el-bg-color', '#ffffff')
      root.style.setProperty('--el-bg-color-page', '#f8f9fa')
      root.style.setProperty('--el-bg-color-overlay', '#ffffff')
      root.style.setProperty('--el-text-color-primary', '#0f172a')
      root.style.setProperty('--el-text-color-regular', '#475569')
      root.style.setProperty('--el-text-color-secondary', '#64748b')
      root.style.setProperty('--el-text-color-placeholder', '#94a3b8')
      root.style.setProperty('--el-border-color', '#e2e8f0')
      root.style.setProperty('--el-border-color-light', '#f1f5f9')
      root.style.setProperty('--el-border-color-lighter', '#f8fafc')
      root.style.setProperty('--el-fill-color', '#f1f5f9')
      root.style.setProperty('--el-fill-color-light', '#f8fafc')
      root.style.setProperty('--el-fill-color-lighter', '#fafafa')
      root.style.setProperty('--el-fill-color-blank', '#ffffff')
      root.style.setProperty('--el-mask-color', 'rgba(0, 0, 0, 0.5)')
    }
  }
  
  /**
   * 初始化主题（在应用启动时调用）
   */
  function initTheme(): void {
    // 监听系统主题变化
    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)')
    mediaQuery.addEventListener('change', (e) => {
      systemPrefersDark.value = e.matches
      if (mode.value === 'system') {
        applyTheme()
      }
    })
    
    // 应用初始主题
    applyTheme()
  }
  
  // ==================== 辅助函数 ====================
  
  function getStoredTheme(): ThemeMode {
    const stored = localStorage.getItem(THEME_STORAGE_KEY)
    if (stored === 'light' || stored === 'dark' || stored === 'system') {
      return stored
    }
    return 'light' // 默认浅色模式
  }
  
  function getSystemPreference(): boolean {
    if (typeof window !== 'undefined') {
      return window.matchMedia('(prefers-color-scheme: dark)').matches
    }
    return false
  }
  
  // ==================== 监听变化 ====================
  
  watch(isDark, () => {
    applyTheme()
  })
  
  return {
    mode,
    isDark,
    themeName,
    setTheme,
    toggleTheme,
    initTheme,
  }
})
