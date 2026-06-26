/**
 * 时区安全的日期工具
 * 
 * 所有日期初始化应使用这些函数, 避免UTC时区问题:
 * - toISOString() 返回UTC时间, 凌晨0-8点(北京)会返回前一天的日期
 * - 使用 Asia/Shanghai 时区保证日期正确
 */

const TZ = 'Asia/Shanghai'

/** 获取中国时区的日期字符串 YYYY-MM-DD */
export function getChinaDate(d?: Date): string {
  const fmt = new Intl.DateTimeFormat('en-CA', { timeZone: TZ, year: 'numeric', month: '2-digit', day: '2-digit' })
  return fmt.format(d || new Date())
}

/** 获取中国时区的日期字符串 YYYYMMDD (API参数格式) */
export function getChinaDateInt(d?: Date): string {
  return getChinaDate(d).replace(/-/g, '')
}

/** 获取中国时区的年/月/日/周/时/分 各字段 */
export function getChinaParts(d?: Date): { year: number; month: number; day: number; weekday: number; hour: number; minute: number } {
  const date = d || new Date()
  const fmt = new Intl.DateTimeFormat('en-CA', {
    timeZone: TZ,
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
    hour12: false, weekday: 'short',
  })
  const parts = fmt.formatToParts(date)
  const get = (k: string) => parts.find(p => p.type === k)?.value || ''
  const wmap: Record<string, number> = { Sun: 0, Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6 }
  return {
    year: Number(get('year')),
    month: Number(get('month')),
    day: Number(get('day')),
    weekday: wmap[get('weekday')] ?? 0,
    hour: Number(get('hour')),
    minute: Number(get('minute')),
  }
}

/** 获取中国时区的星期几 (0=周日, 6=周六) */
export function getChinaWeekday(d?: Date): number { return getChinaParts(d).weekday }

/** 获取中国时区的小时 (0-23) */
export function getChinaHour(d?: Date): number { return getChinaParts(d).hour }

/** 获取中国时区的分钟 (0-59) */
export function getChinaMinute(d?: Date): number { return getChinaParts(d).minute }

/** 获取中国时区的 HHMM 整数 (例 0935 = 935, 1430 = 1430), 便于区间判定 */
export function getChinaHHMM(d?: Date): number {
  const p = getChinaParts(d)
  return p.hour * 100 + p.minute
}

/** 从任意 Date 对象按中国时区输出 YYYY-MM-DD */
export function formatChinaDate(d: Date): string { return getChinaDate(d) }

/** 从任意 Date 对象按中国时区输出 YYYYMMDD */
export function formatChinaDateInt(d: Date): string { return getChinaDateInt(d) }
