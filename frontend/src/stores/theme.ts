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
      root.style.setProperty('--el-bg-color', '#1a2332')
      root.style.setProperty('--el-bg-color-page', '#232b3b')
      root.style.setProperty('--el-bg-color-overlay', '#2a3447')
      root.style.setProperty('--el-text-color-primary', '#e2e8f0')
      root.style.setProperty('--el-text-color-regular', '#b0b8c4')
      root.style.setProperty('--el-text-color-secondary', '#8492a6')
      root.style.setProperty('--el-text-color-placeholder', '#4e5969')
      root.style.setProperty('--el-text-color-disabled', '#4e5969')
      root.style.setProperty('--el-border-color', 'rgba(255, 255, 255, 0.10)')
      root.style.setProperty('--el-border-color-light', 'rgba(255, 255, 255, 0.06)')
      root.style.setProperty('--el-border-color-lighter', 'rgba(255, 255, 255, 0.04)')
      root.style.setProperty('--el-border-color-dark', 'rgba(255, 255, 255, 0.14)')
      root.style.setProperty('--el-fill-color', '#263040')
      root.style.setProperty('--el-fill-color-light', '#232b3b')
      root.style.setProperty('--el-fill-color-lighter', '#1f2738')
      root.style.setProperty('--el-fill-color-blank', '#1a2332')
      root.style.setProperty('--el-fill-color-dark', '#303d52')
      root.style.setProperty('--el-mask-color', 'rgba(0, 0, 0, 0.7)')
      root.style.setProperty('--el-color-primary', '#5b9cf5')
      root.style.setProperty('--el-color-primary-light-3', '#7db4f7')
      root.style.setProperty('--el-color-primary-light-5', '#9ec8f9')
      root.style.setProperty('--el-color-primary-light-7', '#c0dcfb')
      root.style.setProperty('--el-color-primary-light-9', '#e8f2fe')
      root.style.setProperty('--el-color-primary-dark-2', '#4a8ce4')
      root.style.setProperty('--el-collapse-header-bg-color', '#232b3b')
      root.style.setProperty('--el-collapse-content-bg-color', '#2a3447')
      root.style.setProperty('--el-collapse-header-text-color', '#e2e8f0')
      root.style.setProperty('--el-disabled-bg-color', '#1f2738')
      root.style.setProperty('--el-disabled-text-color', '#4e5969')
      root.style.setProperty('--el-disabled-border-color', 'rgba(255, 255, 255, 0.06)')
    } else {
      // 浅色模式 Element Plus 变量
      root.style.setProperty('--el-bg-color', '#ffffff')
      root.style.setProperty('--el-bg-color-page', '#f8f9fa')
      root.style.setProperty('--el-bg-color-overlay', '#ffffff')
      root.style.setProperty('--el-text-color-primary', '#0f172a')
      root.style.setProperty('--el-text-color-regular', '#475569')
      root.style.setProperty('--el-text-color-secondary', '#64748b')
      root.style.setProperty('--el-text-color-placeholder', '#94a3b8')
      root.style.setProperty('--el-text-color-disabled', '#c0c4cc')
      root.style.setProperty('--el-border-color', '#e2e8f0')
      root.style.setProperty('--el-border-color-light', '#f1f5f9')
      root.style.setProperty('--el-border-color-lighter', '#f8fafc')
      root.style.setProperty('--el-border-color-dark', '#cbd5e1')
      root.style.setProperty('--el-fill-color', '#f1f5f9')
      root.style.setProperty('--el-fill-color-light', '#f8fafc')
      root.style.setProperty('--el-fill-color-lighter', '#ffffff')
      root.style.setProperty('--el-fill-color-blank', '#ffffff')
      root.style.setProperty('--el-fill-color-dark', '#e2e8f0')
      root.style.setProperty('--el-mask-color', 'rgba(0, 0, 0, 0.5)')
      root.style.setProperty('--el-color-primary', '#3b82f6')
      root.style.setProperty('--el-color-primary-light-3', '#60a5fa')
      root.style.setProperty('--el-color-primary-light-5', '#93c5fd')
      root.style.setProperty('--el-color-primary-light-7', '#bfdbfe')
      root.style.setProperty('--el-color-primary-light-9', '#eff6ff')
      root.style.setProperty('--el-color-primary-dark-2', '#2563eb')
      root.style.setProperty('--el-collapse-header-bg-color', '#f8fafc')
      root.style.setProperty('--el-collapse-content-bg-color', '#ffffff')
      root.style.setProperty('--el-collapse-header-text-color', '#0f172a')
      root.style.setProperty('--el-disabled-bg-color', '#f5f7fa')
      root.style.setProperty('--el-disabled-text-color', '#c0c4cc')
      root.style.setProperty('--el-disabled-border-color', '#e4e7ed')
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
    return 'light' // 默认亮色模式(用户要求)
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
