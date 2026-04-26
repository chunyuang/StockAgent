/**
 * ANSI 颜色代码转 HTML 颜色工具
 *
 * 将终端日志中的 ANSI escape 序列（如 \x1b[31m）转换为 HTML <span> 标签，
 * 使回测日志在前端页面中保留原始颜色渲染。
 *
 * 支持的标准：
 * - 3/4 bit 标准 ANSI 颜色（30-37, 90-97 前景；40-47, 100-107 背景）
 * - 粗体(1)、斜体(3)、下划线(4)、闪烁(5)、反色(7)、隐藏(8)
 * - 256 色模式（38;5;n / 48;5;n）
 * - 24 位真彩色（38;2;r;g;b / 48;2;r;g;b）
 * - 重置代码（0, 39, 49）
 */

// ==================== 颜色映射表 ====================

/** 标准 ANSI 前景色 → CSS 颜色 */
const ANSI_FG: Record<number, string> = {
  30: '#000000',   // 黑
  31: '#e06c75',   // 红（One Dark 风格）
  32: '#98c379',   // 绿
  33: '#e5c07b',   // 黄
  34: '#61afef',   // 蓝
  35: '#c678dd',   // 品红
  36: '#56b6c2',   // 青
  37: '#abb2bf',   // 白（浅灰）
  // 高亮色
  90: '#5c6370',   // 亮黑（暗灰）
  91: '#e06c75',   // 亮红
  92: '#98c379',   // 亮绿
  93: '#e5c07b',   // 亮黄
  94: '#61afef',   // 亮蓝
  95: '#c678dd',   // 亮品红
  96: '#56b6c2',   // 亮青
  97: '#ffffff',   // 亮白
}

/** 标准 ANSI 背景色 → CSS 颜色 */
const ANSI_BG: Record<number, string> = {
  40: '#000000',
  41: '#e06c75',
  42: '#98c379',
  43: '#e5c07b',
  44: '#61afef',
  45: '#c678dd',
  46: '#56b6c2',
  47: '#abb2bf',
  100: '#5c6370',
  101: '#e06c75',
  102: '#98c379',
  103: '#e5c07b',
  104: '#61afef',
  105: '#c678dd',
  106: '#56b6c2',
  107: '#ffffff',
}

// ==================== 样式栈 ====================

interface AnsiStyle {
  fg: string | null
  bg: string | null
  bold: boolean
  italic: boolean
  underline: boolean
  blink: boolean
  inverse: boolean
  hidden: boolean
}

function defaultStyle(): AnsiStyle {
  return {
    fg: null,
    bg: null,
    bold: false,
    italic: false,
    underline: false,
    blink: false,
    inverse: false,
    hidden: false,
  }
}

/** 将当前样式状态渲染为 CSS 样式字符串 */
function styleToCss(s: AnsiStyle): string {
  const parts: string[] = []

  let fg = s.fg
  let bg = s.bg
  // 反色：前景/背景互换
  if (s.inverse) {
    fg = s.bg
    bg = s.fg
  }

  if (fg) parts.push(`color:${fg}`)
  if (bg) parts.push(`background-color:${bg}`)
  if (s.bold) parts.push('font-weight:700')
  if (s.italic) parts.push('font-style:italic')
  if (s.underline) parts.push('text-decoration:underline')
  if (s.hidden) parts.push('visibility:hidden')

  return parts.join(';')
}

// ==================== 核心转换函数 ====================

/**
 * 解析单个 SGR（Select Graphic Rendition）参数序列，更新样式状态
 */
function applySgr(codes: number[], style: AnsiStyle): void {
  let i = 0
  while (i < codes.length) {
    const code = codes[i]

    if (code === 0) {
      // 重置所有属性
      Object.assign(style, defaultStyle())
    } else if (code === 1) {
      style.bold = true
    } else if (code === 3) {
      style.italic = true
    } else if (code === 4) {
      style.underline = true
    } else if (code === 5 || code === 6) {
      style.blink = true
    } else if (code === 7) {
      style.inverse = true
    } else if (code === 8) {
      style.hidden = true
    } else if (code === 22) {
      style.bold = false
    } else if (code === 23) {
      style.italic = false
    } else if (code === 24) {
      style.underline = false
    } else if (code === 25) {
      style.blink = false
    } else if (code === 27) {
      style.inverse = false
    } else if (code === 28) {
      style.hidden = false
    } else if (code === 39) {
      style.fg = null
    } else if (code === 49) {
      style.bg = null
    } else if ((code >= 30 && code <= 37) || (code >= 90 && code <= 97)) {
      style.fg = ANSI_FG[code] || null
    } else if ((code >= 40 && code <= 47) || (code >= 100 && code <= 107)) {
      style.bg = ANSI_BG[code] || null
    } else if (code === 38) {
      // 扩展前景色
      if (i + 1 < codes.length && codes[i + 1] === 5 && i + 2 < codes.length) {
        // 256 色: 38;5;n
        style.fg = color256ToCss(codes[i + 2])
        i += 2
      } else if (i + 1 < codes.length && codes[i + 1] === 2 && i + 4 < codes.length) {
        // 24 位真彩色: 38;2;r;g;b
        style.fg = `rgb(${codes[i + 2]},${codes[i + 3]},${codes[i + 4]})`
        i += 4
      }
    } else if (code === 48) {
      // 扩展背景色
      if (i + 1 < codes.length && codes[i + 1] === 5 && i + 2 < codes.length) {
        style.bg = color256ToCss(codes[i + 2])
        i += 2
      } else if (i + 1 < codes.length && codes[i + 1] === 2 && i + 4 < codes.length) {
        style.bg = `rgb(${codes[i + 2]},${codes[i + 3]},${codes[i + 4]})`
        i += 4
      }
    }

    i++
  }
}

/**
 * 256 色索引 → CSS 颜色值
 */
function color256ToCss(n: number): string {
  // 0-15: 标准色 + 高亮色
  const standard = [
    '#000000', '#e06c75', '#98c379', '#e5c07b',
    '#61afef', '#c678dd', '#56b6c2', '#abb2bf',
    '#5c6370', '#e06c75', '#98c379', '#e5c07b',
    '#61afef', '#c678dd', '#56b6c2', '#ffffff',
  ]
  if (n < 16) return standard[n]

  // 16-231: 6×6×6 色彩立方体
  if (n < 232) {
    const v = n - 16
    const b = [0, 95, 135, 175, 215, 255]
    const r = b[Math.floor(v / 36)]
    const g = b[Math.floor((v % 36) / 6)]
    const blue = b[v % 6]
    return `rgb(${r},${g},${blue})`
  }

  // 232-255: 24 阶灰度
  const gray = 8 + (n - 232) * 10
  return `rgb(${gray},${gray},${gray})`
}

// ==================== 公共 API ====================

/**
 * 将含 ANSI 转义序列的文本转为带 <span> 标签的 HTML
 *
 * @param text 原始文本（可能含 \x1b[ 或 \u001b[ 转义序列）
 * @returns 安全的 HTML 字符串，可直接用 v-html 渲染
 */
export function ansiToHtml(text: string): string {
  if (!text) return ''

  // 正则匹配 ANSI CSI 序列: ESC [ ... m
  // 支持两种写法: \x1b[ 或 \u001b[
  const ansiRegex = /\x1b\[([\d;]*)m/g
  const style = defaultStyle()

  let result = ''
  let lastIndex = 0
  let match: RegExpExecArray | null
  let currentSpanOpen = false

  // 先对纯文本做 HTML 转义
  const escapeHtml = (s: string) =>
    s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')

  while ((match = ansiRegex.exec(text)) !== null) {
    // match 之前的文本
    const plainText = text.slice(lastIndex, match.index)
    if (plainText) {
      const css = styleToCss(style)
      if (css) {
        if (!currentSpanOpen) {
          result += `<span style="${css}">`
          currentSpanOpen = true
        }
        result += escapeHtml(plainText)
      } else {
        if (currentSpanOpen) {
          result += '</span>'
          currentSpanOpen = false
        }
        result += escapeHtml(plainText)
      }
    }

    // 解析 SGR 参数
    const paramStr = match[1]
    const codes = paramStr
      ? paramStr.split(';').map(Number).filter((n) => !isNaN(n))
      : [0] // ESC[m 等同于 ESC[0m

    applySgr(codes, style)

    // 样式变化时关闭旧 span，准备新 span
    if (currentSpanOpen) {
      result += '</span>'
      currentSpanOpen = false
    }

    lastIndex = ansiRegex.lastIndex
  }

  // 处理剩余文本
  const remaining = text.slice(lastIndex)
  if (remaining) {
    const css = styleToCss(style)
    if (css) {
      result += `<span style="${css}">${escapeHtml(remaining)}</span>`
    } else {
      result += escapeHtml(remaining)
    }
  }

  // 关闭未闭合的 span
  if (currentSpanOpen) {
    result += '</span>'
  }

  return result
}

/**
 * 批量转换日志数组
 */
export function ansiLogsToHtml(logs: string[]): string[] {
  return logs.map(ansiToHtml)
}

/**
 * 检测文本是否包含 ANSI 转义序列
 */
export function hasAnsi(text: string): boolean {
  return /\x1b\[[\d;]*m/.test(text)
}

export default ansiToHtml
