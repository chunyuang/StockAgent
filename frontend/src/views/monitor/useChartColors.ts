/**
 * 获取CSS变量的实际颜色值(echarts不解析CSS变量,需要传实际值)
 */
import { ref, onMounted } from 'vue'

const colors = ref({
  stockUp: '#f23645',
  stockDown: '#089981',
  stockUpBg: 'rgba(242, 54, 69, 0.08)',
  stockDownBg: 'rgba(8, 153, 129, 0.08)',
  primary: '#409eff',
  warning: '#e6a23c',
  textTertiary: '#64748b',
})

let initialized = false

function initFromCSS() {
  if (typeof document === 'undefined') return
  const el = document.documentElement
  const s = getComputedStyle(el)
  const get = (v: string, fallback: string) => s.getPropertyValue(v)?.trim() || fallback
  colors.value = {
    stockUp: get('--stock-up', '#f23645'),
    stockDown: get('--stock-down', '#089981'),
    stockUpBg: get('--stock-up-bg', 'rgba(242, 54, 69, 0.08)'),
    stockDownBg: get('--stock-down-bg', 'rgba(8, 153, 129, 0.08)'),
    primary: get('--el-color-primary', '#409eff'),
    warning: get('--warning', '#e6a23c') || get('--el-color-warning', '#e6a23c'),
    textTertiary: get('--text-tertiary', '#64748b'),
  }
  initialized = true
}

export function useChartColors() {
  if (!initialized) initFromCSS()
  onMounted(() => { if (!initialized) initFromCSS() })
  return colors
}
