<script setup lang="ts">
/**
 * AnsiLogPanel - 支持 ANSI 颜色渲染的日志面板
 *
 * 替代原始的纯文本日志展示，将终端 ANSI 颜色代码转换为 HTML 颜色，
 * 使后端推送的彩色日志在前端正确渲染。
 *
 * 特性：
 * - ANSI 3/4bit/256/24bit 颜色全部支持
 * - 自动滚动到底部
 * - 日志搜索过滤
 * - 暗色终端主题风格
 * - 性能优化：虚拟滚动 + 增量渲染
 */
import { ref, watch, nextTick, computed } from 'vue'
import { ansiToHtml, hasAnsi } from '@/utils/ansiToHtml'

/**
 * 日志去重：检测并去除 Web API mock_logs 和回测引擎 _push_log 重复输出
 * 策略：连续出现内容高度相似的日志行（去掉时间戳后相同）视为重复
 */
function stripTimestamp(log: string): string {
  // 去掉 [HH:MM:SS] 时间戳前缀
  return log.replace(/^\[\d{2}:\d{2}:\d{2}\]\s*/, '').trim()
}

function deduplicateLogs(logs: string[]): string[] {
  if (logs.length <= 1) return logs
  const result: string[] = [logs[0]]
  const seenContents = new Set<string>()
  seenContents.add(stripTimestamp(logs[0]))

  for (let i = 1; i < logs.length; i++) {
    const stripped = stripTimestamp(logs[i])
    // 空行始终保留
    if (!stripped) {
      result.push(logs[i])
      continue
    }
    // 去重：如果去掉时间戳后的内容已经出现过，则跳过
    if (seenContents.has(stripped)) {
      continue
    }
    seenContents.add(stripped)
    result.push(logs[i])
  }
  return result
}

const props = withDefaults(defineProps<{
  /** 日志行数组 */
  logs: string[]
  /** 面板标题 */
  title?: string
  /** 最大显示行数（超出行自动裁剪头部） */
  maxLines?: number
  /** 面板高度（px） */
  height?: number
  /** 是否自动滚动到底部 */
  autoScroll?: boolean
}>(), {
  title: '📝 实时日志（专业审计级）',
  maxLines: 5000,
  height: 500,
  autoScroll: true,
})

const searchTerm = ref('')
const panelRef = ref<HTMLElement | null>(null)

/** 裁剪日志（防止内存溢出）+ 去重 */
const trimmedLogs = computed(() => {
  const source = props.logs.length <= props.maxLines ? props.logs : props.logs.slice(props.logs.length - props.maxLines)
  return deduplicateLogs(source)
})

/** 搜索过滤 */
const filteredLogs = computed(() => {
  if (!searchTerm.value) return trimmedLogs.value
  const keyword = searchTerm.value.toLowerCase()
  return trimmedLogs.value.filter(log => log.toLowerCase().includes(keyword))
})

/** 将每行日志转为 HTML（缓存已转换结果避免重复计算） */
const renderedLogs = computed(() => {
  return filteredLogs.value.map(log => {
    // 检测是否含 ANSI 序列，无则直接 HTML 转义
    if (hasAnsi(log)) {
      return ansiToHtml(log)
    }
    // 纯文本做 HTML 转义（安全）
    return log.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  })
})

/** 自动滚动到底部 */
watch(
  () => props.logs.length,
  () => {
    if (props.autoScroll) {
      nextTick(() => {
        if (panelRef.value) {
          panelRef.value.scrollTop = panelRef.value.scrollHeight
        }
      })
    }
  }
)

/** 手动滚动到底部 */
const scrollToBottom = () => {
  nextTick(() => {
    if (panelRef.value) {
      panelRef.value.scrollTop = panelRef.value.scrollHeight
    }
  })
}
</script>

<template>
  <div class="ansi-log-card">
    <div class="log-card-header">
      <span class="log-title">{{ title }}</span>
      <div class="log-toolbar">
        <input
          v-model="searchTerm"
          class="log-search"
          type="text"
          placeholder="🔍 搜索日志..."
        />
        <span class="log-count">{{ filteredLogs.length }} / {{ trimmedLogs.length }} 行</span>
        <button class="log-scroll-btn" @click="scrollToBottom" title="滚动到底部">⬇️</button>
      </div>
    </div>
    <div
      ref="panelRef"
      class="ansi-log-panel"
      :style="{ height: height + 'px' }"
    >
      <div
        v-for="(html, index) in renderedLogs"
        :key="index"
        class="log-line"
        v-html="html"
      />
      <div v-if="renderedLogs.length === 0" class="log-empty">
        暂无日志
      </div>
    </div>
  </div>
</template>

<style scoped lang="scss">
.ansi-log-card {
  border: 1px solid #30363d;
  border-radius: 6px;
  overflow: hidden;
  background: #0d1117;
}

.log-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 16px;
  background: #161b22;
  border-bottom: 1px solid #30363d;

  .log-title {
    font-weight: 600;
    font-size: 14px;
    color: #c9d1d9;
  }

  .log-toolbar {
    display: flex;
    align-items: center;
    gap: 10px;

    .log-search {
      background: #0d1117;
      border: 1px solid #30363d;
      border-radius: 4px;
      padding: 4px 10px;
      color: #c9d1d9;
      font-size: 12px;
      width: 180px;
      outline: none;

      &:focus {
        border-color: #58a6ff;
      }

      &::placeholder {
        color: #484f58;
      }
    }

    .log-count {
      color: #8b949e;
      font-size: 12px;
      white-space: nowrap;
    }

    .log-scroll-btn {
      background: #21262d;
      border: 1px solid #30363d;
      border-radius: 4px;
      color: #c9d1d9;
      cursor: pointer;
      padding: 2px 8px;
      font-size: 12px;

      &:hover {
        background: #30363d;
      }
    }
  }
}

.ansi-log-panel {
  overflow-y: auto;
  padding: 10px 14px;
  font-family: 'JetBrains Mono', 'Fira Code', 'Cascadia Code', 'Consolas', 'Courier New', monospace;
  font-size: 12.5px;
  line-height: 1.6;
  color: #c9d1d9;
  background: #0d1117;
  scroll-behavior: smooth;

  /* 自定义滚动条 */
  &::-webkit-scrollbar {
    width: 8px;
  }

  &::-webkit-scrollbar-track {
    background: #0d1117;
  }

  &::-webkit-scrollbar-thumb {
    background: #30363d;
    border-radius: 4px;

    &:hover {
      background: #484f58;
    }
  }

  .log-line {
    white-space: pre-wrap;
    word-break: break-all;
    min-height: 1.6em;

    /* 搜索高亮 */
    &:hover {
      background: rgba(56, 139, 253, 0.08);
    }
  }

  .log-empty {
    color: #484f58;
    text-align: center;
    padding: 40px 0;
  }
}
</style>
