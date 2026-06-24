<script setup lang="ts">
/**
 * 系统健康运维面板
 * P2-8: Grafana风格 — 心跳/数据源/MongoDB/Redis/系统资源/告警
 */
import { ref, onMounted, onUnmounted } from 'vue'
import { api } from '@/api/client'

interface HealthDetail {
  scanner: { is_running: boolean; uptime_seconds: number }
  data_sources: { name: string; available: boolean; stocks: number; note?: string }[]
  mongo: { connected: boolean; version?: string; collections?: number }
  redis: { connected: boolean }
  websocket: { connected?: boolean; client_count?: number }
  system: { cpu_pct: number; memory_pct: number; disk_pct: number }
  alerts: any[]
  health_score: number
}

const data = ref<HealthDetail | null>(null)

async function fetchData() {
  try {
    const r: any = await api.get('/scanner/system-health-detail')
    if (r?.success) data.value = r.data
  } catch (e) { console.error('[SystemHealth]', e) }
}

function uptimeFmt(s: number): string {
  if (s == null || isNaN(s)) return '-'
  if (s < 60) return `${Math.round(s)}s`
  if (s < 3600) return `${Math.round(s / 60)}m`
  return `${(s / 3600).toFixed(1)}h`
}

function cpuColor(v: number): string {
  if (v == null || isNaN(v)) return '#67c23a'
  return v > 80 ? '#f56c6c' : v > 50 ? '#e6a23c' : '#67c23a'
}

let timer: number
onMounted(() => { fetchData(); timer = window.setInterval(fetchData, 10000) })
onUnmounted(() => clearInterval(timer))
</script>

<template>
  <div class="sys-health">
    <div class="sh-header">
      <span class="sh-title">🔧 系统健康</span>
      <span class="sh-refresh cp" @click="fetchData">🔄</span>
    </div>

    <div v-if="data" class="sh-content">
      <!-- 扫描器 -->
      <div class="sh-row">
        <span class="sh-label">扫描器</span>
        <span :class="data.scanner?.is_running ? 'sh-ok' : 'sh-err'">{{ data.scanner?.is_running ? '🟢 运行中' : '🔴 已停止' }}</span>
        <span class="sh-sub" v-if="data.scanner?.is_running">{{ uptimeFmt(data.scanner?.uptime_seconds) }}</span>
      </div>

      <!-- 数据源 -->
      <div class="sh-row">
        <span class="sh-label">数据源</span>
        <span v-for="ds in data.data_sources" :key="ds.name" class="sh-ds" :class="ds.available ? 'ok' : 'err'">
          {{ ds.name === 'eastmoney' ? '东财' : ds.name }} {{ ds.available ? '✓' : '✗' }}
          <span v-if="ds.stocks" class="sh-ds-sub">{{ ds.stocks }}只</span>
        </span>
      </div>

      <!-- 存储 -->
      <div class="sh-row">
        <span class="sh-label">MongoDB</span>
        <span :class="data.mongo?.connected ? 'sh-ok' : 'sh-err'">{{ data.mongo?.connected ? '🟢' : '🔴' }}</span>
        <span v-if="data.mongo?.collections" class="sh-sub">{{ data.mongo.collections }}集合</span>
        <span class="sh-label" style="margin-left:12px">Redis</span>
        <span :class="data.redis?.connected ? 'sh-ok' : 'sh-err'">{{ data.redis?.connected ? '🟢' : '🔴' }}</span>
        <template v-if="data.websocket && data.websocket.connected !== undefined">
          <span class="sh-label" style="margin-left:12px">WS</span>
          <span :class="data.websocket.connected !== false ? 'sh-ok' : 'sh-warn'">{{ data.websocket.connected !== false ? '🟢' : '🟡' }}</span>
          <span v-if="data.websocket.client_count" class="sh-sub">{{ data.websocket.client_count }}连接</span>
        </template>
      </div>

      <!-- 系统资源 -->
      <div class="sh-row">
        <span class="sh-label">CPU</span>
        <div class="sh-bar-wrap"><div class="sh-bar" :style="{ width: (data.system?.cpu_pct ?? 0) + '%', background: cpuColor(data.system?.cpu_pct ?? 0) }"></div></div>
        <span class="sh-bar-val">{{ data.system?.cpu_pct ?? 0 }}%</span>
        <span class="sh-label" style="margin-left:8px">MEM</span>
        <div class="sh-bar-wrap"><div class="sh-bar" :style="{ width: (data.system?.memory_pct ?? 0) + '%', background: cpuColor(data.system?.memory_pct ?? 0) }"></div></div>
        <span class="sh-bar-val">{{ data.system?.memory_pct ?? 0 }}%</span>
        <span class="sh-label" style="margin-left:8px">DISK</span>
        <span class="sh-bar-val">{{ data.system?.disk_pct ?? 0 }}%</span>
      </div>

      <!-- 告警 -->
      <div v-if="data.alerts?.length" class="sh-alerts">
        <div v-for="(a, i) in data.alerts.slice(0, 3)" :key="i" class="sh-alert" :class="a.level">
          {{ a.message || a.action }}
        </div>
      </div>
    </div>
    <div v-else class="sh-empty">加载中...</div>
  </div>
</template>

<style scoped>
.sys-health { background: var(--el-bg-color); border-radius: 8px; padding: 12px; font-size: 12px; }
.sh-header { display: flex; justify-content: space-between; margin-bottom: 8px; }
.sh-title { font-weight: 600; font-size: 13px; }
.sh-refresh { font-size: 12px; }
.sh-content { display: flex; flex-direction: column; gap: 6px; }
.sh-row { display: flex; align-items: center; gap: 6px; }
.sh-label { color: var(--el-text-color-secondary); font-size: 11px; min-width: 40px; }
.sh-ok { color: #67c23a; } .sh-err { color: #f56c6c; } .sh-warn { color: #e6a23c; }
.sh-sub { font-size: 10px; color: var(--el-text-color-secondary); }
.sh-ds { font-size: 11px; padding: 1px 4px; border-radius: 2px; }
.sh-ds.ok { background: #67c23a15; color: #67c23a; } .sh-ds.err { background: #f56c6c15; color: #f56c6c; }
.sh-ds-sub { font-size: 9px; color: var(--el-text-color-secondary); margin-left: 2px; }
.sh-bar-wrap { display: inline-block; width: 40px; height: 6px; background: var(--el-fill-color); border-radius: 3px; }
.sh-bar { height: 100%; border-radius: 3px; transition: width 0.5s; }
.sh-bar-val { font-size: 10px; min-width: 30px; }
.sh-alerts { margin-top: 4px; }
.sh-alert { padding: 3px 6px; border-radius: 3px; font-size: 10px; margin-bottom: 2px; }
.sh-alert.warning { background: #e6a23c15; color: #e6a23c; }
.sh-alert.critical { background: #f56c6c15; color: #f56c6c; }
.sh-empty { text-align: center; padding: 16px; color: var(--el-text-color-secondary); font-size: 12px; }
</style>
