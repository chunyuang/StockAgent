/**
 * 安全的 toFixed — 处理 null/undefined/NaN/Infinity
 * 替代原生 Number.prototype.toFixed，避免 null.toFixed() 崩溃
 *
 * 用法: safeFixed(val, 2)  →  "3.14" / "-" / "0.00"
 */
export function safeFixed(val: unknown, digits: number = 0, fallback: string = '-'): string {
  if (val == null) return fallback
  const n = Number(val)
  if (!Number.isFinite(n)) return fallback
  return n.toFixed(digits)
}

/**
 * 安全的 toFixed 返回 number (用于图表数据)
 * null/undefined/NaN → 0
 */
export function safeNum(val: unknown, digits: number = 0): number {
  if (val == null) return 0
  const n = Number(val)
  if (!Number.isFinite(n)) return 0
  return +n.toFixed(digits)
}
