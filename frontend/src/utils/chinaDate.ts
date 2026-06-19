/**
 * 时区安全的日期工具
 * 
 * 所有日期初始化应使用这些函数, 避免UTC时区问题:
 * - toISOString() 返回UTC时间, 凌晨0-8点(北京)会返回前一天的日期
 * - 使用 Asia/Shanghai 时区保证日期正确
 */

/** 获取中国时区的日期字符串 YYYY-MM-DD */
export function getChinaDate(): string {
  const now = new Date()
  const china = new Date(now.toLocaleString('en-US', { timeZone: 'Asia/Shanghai' }))
  return china.toISOString().slice(0, 10)
}

/** 获取中国时区的日期字符串 YYYYMMDD (API参数格式) */
export function getChinaDateInt(): string {
  return getChinaDate().replace(/-/g, '')
}
