import { ref, computed, onMounted } from 'vue'
import { api } from '@/api/client'

/**
 * 统一日期选择 Composable
 * 
 * 所有市场监听Tab共用, 保证:
 * 1. 单日选择(非范围)
 * 2. 默认今天
 * 3. 交易日染色(调 /unified/date-availability)
 * 4. 前/后一天导航
 */

/** 获取中国时区的日期字符串 YYYY-MM-DD */
function getChinaDate(): string {
  const now = new Date()
  const china = new Date(now.toLocaleString('en-US', { timeZone: 'Asia/Shanghai' }))
  const y = china.getFullYear()
  const m = String(china.getMonth() + 1).padStart(2, '0')
  const d = String(china.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
}

export function useUnifiedDateBar() {
  // 当前选中日期 (YYYY-MM-DD 格式, 与ElDatePicker一致)
  // 使用中国时区初始化, 避免UTC时区问题(凌晨0-8点toISOString返回前一天)
  const selectedDate = ref(getChinaDate())
  
  // 交易日数据 { '20260616': { status: 'trades'|'no-trades'|'weekend', count: 5, ... } }
  const dateAvailability = ref<Record<string, any>>({})
  const availabilityLoading = ref(false)
  
  // 今天(中国时区)
  const today = computed(() => getChinaDate())
  const isToday = computed(() => selectedDate.value === today.value)
  
  // 日期转API格式 (YYYYMMDD)
  const dateForApi = computed(() => selectedDate.value.replace(/-/g, ''))
  
  // 前一天
  function prevDay() {
    // 【v2.9.98修复】用T12:00:00解析避免时区偏移导致日期跳变
    // 本地日期组件设计 // 时区安全(为 Element Plus 控件服务)
    const d = new Date(selectedDate.value + 'T12:00:00')
    d.setDate(d.getDate() - 1) // 时区安全
    selectedDate.value = `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}` // 时区安全
  }
  
  // 后一天
  function nextDay() {
    // 时区安全(同上)
    const d = new Date(selectedDate.value + 'T12:00:00')
    d.setDate(d.getDate() + 1) // 时区安全
    const chinaToday = getChinaDate()
    const nextDate = `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}` // 时区安全
    if (nextDate <= chinaToday) {
      selectedDate.value = `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}` // 时区安全
    }
  }
  
  // 回到今天
  function goToday() {
    selectedDate.value = today.value
  }
  
  // 设置日期(外部调用)
  function setDate(date: string) {
    if (date === 'today' || !date) {
      goToday()
    } else {
      // 兼容 YYYYMMDD 和 YYYY-MM-DD
      if (date.length === 8 && /^\d{8}$/.test(date)) {
        selectedDate.value = `${date.slice(0,4)}-${date.slice(4,6)}-${date.slice(6,8)}`
      } else {
        selectedDate.value = date
      }
    }
  }
  
  // 加载日期可用性(交易日染色)
  async function fetchAvailability() {
    if (availabilityLoading.value) return
    availabilityLoading.value = true
    try {
      const r: any = await api.get('/unified/date-availability?days=60')
      const p = r?.data ? r : (r?.success !== false ? r : null)
      if (p?.data) {
        dateAvailability.value = p.data
      }
    } catch (e) {
      // 非关键, 忽略
    } finally {
      availabilityLoading.value = false
    }
  }
  
  // 日期选择器单元格染色(给ElDatePicker用, date 是 Element Plus 传入的本地 Date)
  function dateCellClass(date: Date): string {
    // 【v2.9.98修复】用本地日期组件避免UTC时区偏移 // 时区安全
    const y = date.getFullYear(), m = String(date.getMonth() + 1).padStart(2, '0'), d = String(date.getDate()).padStart(2, '0') // 时区安全
    const key = `${y}${m}${d}`
    const info = dateAvailability.value[key]
    if (!info) return ''
    if (info.status === 'weekend') return 'date-weekend'
    if (info.status === 'trades') return 'date-has-trades'
    return 'date-no-trades'
  }
  
  // 禁用未来日期(中国时区, date 是 Element Plus 传入的本地 Date)
  function disabledDate(date: Date): boolean {
    const chinaToday = getChinaDate()
    // 时区安全(本地 Date 控件)
    const y = date.getFullYear(), m = String(date.getMonth() + 1).padStart(2, '0'), d = String(date.getDate()).padStart(2, '0') // 时区安全
    return `${y}-${m}-${d}` > chinaToday
  }
  
  onMounted(() => {
    fetchAvailability()
  })
  
  return {
    selectedDate,
    dateForApi,
    today,
    isToday,
    dateAvailability,
    availabilityLoading,
    prevDay,
    nextDay,
    goToday,
    setDate,
    dateCellClass,
    disabledDate,
    fetchAvailability,
  }
}
