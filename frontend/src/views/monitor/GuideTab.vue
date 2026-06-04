<script setup lang="ts">
/**
 * GuideTab — 系统引导Tab
 * 从 MarketMonitorView provide/inject 获取composable数据
 * 【v2.9.74: 从MarketMonitorView提取(132行)】
 */
import { useScannerMonitorInject } from './scannerMonitorInject'
import { ElButton } from 'element-plus'

const { startScanner, stopScanner, isRunning } = useScannerMonitorInject()
</script>

<template>
  <div class="mm-guide">
    <!-- 顶部横幅 -->
    <div class="guide-banner">
      <div class="gb-left">
        <div class="gb-logo">📡</div>
        <div>
          <div class="gb-title">超短量化实盘监控系统</div>
          <div class="gb-sub">9层漏斗筛选 · 4策略联合选股 · 实时风控守护</div>
        </div>
      </div>
      <ElButton v-if="!isRunning" type="success" size="large" @click="startScanner" style="padding:10px 32px;font-size:15px">▶ 启动扫描器</ElButton>
      <ElButton v-else type="danger" size="large" @click="stopScanner" style="padding:10px 32px;font-size:15px">⏹ 停止扫描器</ElButton>
    </div>

    <!-- 4列卡片网格 -->
    <div class="guide-grid">
      <!-- 系统架构 -->
      <div class="gg-card gg-span2">
        <div class="gg-head"><span class="gg-icon">🏗️</span>系统架构</div>
        <div class="gg-body">
          <div class="gf-flow">
            <span class="gf-tag gf-input">5000+股票</span>
            <span class="gf-arrow">→</span>
            <span class="gf-tag">L1~L3 基础过滤</span>
            <span class="gf-arrow">→</span>
            <span class="gf-tag">L4~L6 策略筛选</span>
            <span class="gf-arrow">→</span>
            <span class="gf-tag">L7~L9 排序仓位</span>
            <span class="gf-arrow">→</span>
            <span class="gf-tag gf-output">买入信号</span>
          </div>
        </div>
      </div>

      <!-- 操作指南 -->
      <div class="gg-card gg-span2">
        <div class="gg-head"><span class="gg-icon">📖</span>操作指南</div>
        <div class="gg-body">
          <div class="go-list">
            <div class="go-row"><span class="sn">1</span>▶ 启动 → 每5分钟自动扫描，30秒检查持仓</div>
            <div class="go-row"><span class="sn">2</span>📡 扫描 → 立即触发选股，⚡ 强扫跳缓存</div>
            <div class="go-row"><span class="sn">3</span>🎛️ 策略 → 左侧面板开关策略、调参数</div>
            <div class="go-row"><span class="sn">4</span>🟢 买入 → 信号区候选一键下单</div>
            <div class="go-row"><span class="sn">5</span>🔴 卖出 → 持仓卡片快捷平仓或自动止盈止损</div>
            <div class="go-row"><span class="sn">6</span>📋 复盘 / ⚙️ 运维 → 归因分析+系统健康</div>
          </div>
        </div>
      </div>

      <!-- 半路追涨 -->
      <div class="gg-card">
        <div class="gg-head"><span class="gg-icon">🏃</span>半路追涨</div>
        <div class="gg-body gg-compact">
          <div class="gg-line">盘中涨幅3-5% + 量能放大</div>
          <div class="gg-params">
            <span class="gg-p"><span class="gg-pl">SL</span>3%</span>
            <span class="gg-p"><span class="gg-pl">TP</span>12%</span>
            <span class="gg-p"><span class="gg-pl">持仓</span>3天</span>
          </div>
        </div>
      </div>

      <!-- 首板打板 -->
      <div class="gg-card">
        <div class="gg-head"><span class="gg-icon">🥇</span>首板打板</div>
        <div class="gg-body gg-compact">
          <div class="gg-line">首次涨停封板 + 成交概率</div>
          <div class="gg-params">
            <span class="gg-p"><span class="gg-pl">SL</span>3%</span>
            <span class="gg-p"><span class="gg-pl">TP</span>10%</span>
            <span class="gg-p"><span class="gg-pl">持仓</span>2天</span>
          </div>
        </div>
      </div>

      <!-- 龙头低吸 -->
      <div class="gg-card">
        <div class="gg-head"><span class="gg-icon">🐲</span>龙头低吸</div>
        <div class="gg-body gg-compact">
          <div class="gg-line">连板龙头回调 + MA支撑</div>
          <div class="gg-params">
            <span class="gg-p"><span class="gg-pl">SL</span>3.5%</span>
            <span class="gg-p"><span class="gg-pl">TP</span>30%</span>
            <span class="gg-p"><span class="gg-pl">持仓</span>7天</span>
          </div>
        </div>
      </div>

      <!-- 跌停翘板 -->
      <div class="gg-card">
        <div class="gg-head"><span class="gg-icon">💥</span>跌停翘板</div>
        <div class="gg-body gg-compact">
          <div class="gg-line">连续跌停翘板反转</div>
          <div class="gg-params">
            <span class="gg-p"><span class="gg-pl">SL</span>5%</span>
            <span class="gg-p"><span class="gg-pl">TP</span>20%</span>
            <span class="gg-p"><span class="gg-pl">持仓</span>3天</span>
          </div>
        </div>
      </div>

      <!-- 风控体系 -->
      <div class="gg-card gg-span2">
        <div class="gg-head"><span class="gg-icon">🛡️</span>风控体系</div>
        <div class="gg-body">
          <div class="gr-grid">
            <div class="gr-row"><span class="gr-k">强制空仓</span><span class="gr-v">跌停≥80只 / 大盘跌≥3%</span></div>
            <div class="gr-row"><span class="gr-k">情绪仓位</span><span class="gr-v">高潮100% / 分化70% / 震荡50% / 冰点30%</span></div>
            <div class="gr-row"><span class="gr-k">单票上限</span><span class="gr-v">35% · 总仓位上限75%</span></div>
            <div class="gr-row"><span class="gr-k">盘中锁定</span><span class="gr-v">冲高≥6% 回撤≥2.5% → 利润保护</span></div>
            <div class="gr-row"><span class="gr-k">智能检查</span><span class="gr-v">盈利5s / 亏损3s / 接近止损1s</span></div>
            <div class="gr-row"><span class="gr-k">信号过期</span><span class="gr-v">5分钟未执行自动取消</span></div>
          </div>
        </div>
      </div>

      <!-- 快捷键 -->
      <div class="gg-card gg-span2">
        <div class="gg-head"><span class="gg-icon">⌨️</span>快捷键</div>
        <div class="gg-body">
          <div class="gk-row">
            <span class="gk-g"><kbd>F5</kbd>强扫</span>
            <span class="gk-g"><kbd>F9</kbd>买入</span>
            <span class="gk-g"><kbd>Ctrl+S</kbd>卖出</span>
            <span class="gk-g"><kbd>Ctrl+E</kbd>紧急平仓</span>
            <span class="gk-g"><kbd>↑↓</kbd>切换持仓</span>
            <span class="gk-g"><kbd>Enter</kbd>详情</span>
            <span class="gk-g"><kbd>1-4</kbd>策略开关</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped lang="scss">
.mm-guide { flex: 1; overflow-y: auto; padding: 12px 16px; }

.guide-banner { display: flex; align-items: center; justify-content: space-between; padding: 16px 20px; background: var(--bg-elevated); border-radius: 10px; margin-bottom: 12px; }

.gb-left { display: flex; align-items: center; gap: 14px; }

.gb-logo { font-size: 36px; }

.gb-title { font-size: 18px; font-weight: 700; }

.gb-sub { font-size: 12px; color: var(--text-secondary); margin-top: 2px; }

.guide-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; }

.gg-card { background: var(--bg-elevated); border-radius: 10px; overflow: hidden; }

.gg-span2 { grid-column: span 2; }

.gg-head { padding: 8px 14px; font-size: 13px; font-weight: 600; background: var(--bg-normal); border-bottom: 1px solid var(--border-light); }

.gg-icon { margin-right: 6px; }

.gg-body { padding: 10px 14px; }

.gg-compact { display: flex; flex-direction: column; gap: 6px; }

.gg-line { font-size: 12px; color: var(--text-secondary); }

.gg-params { display: flex; gap: 10px; }

.gg-p { font-size: 12px; font-weight: 500; }

.gg-pl { color: var(--text-tertiary); font-weight: 400; margin-right: 3px; }

.gf-flow { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }

.gf-tag { padding: 4px 10px; border-radius: 5px; font-size: 12px; font-weight: 500; background: var(--bg-normal); border: 1px solid var(--border-default); }

.gf-tag.gf-input { background: var(--el-color-primary-light-5); border-color: var(--el-color-primary-light-3); color: var(--el-color-primary-dark-2); }

.gf-tag.gf-output { background: rgba(0,180,42,0.1); border-color: rgba(0,180,42,0.3); color: #00b42a; }

.gf-arrow { color: var(--text-tertiary); font-size: 11px; }

.go-list { display: flex; flex-direction: column; gap: 6px; }

.go-row { display: flex; align-items: center; gap: 8px; font-size: 12px; line-height: 1.5; }

.gr-grid { display: flex; flex-direction: column; gap: 5px; }

.gr-row { display: flex; align-items: center; gap: 8px; font-size: 12px; }

.gr-k { color: var(--text-tertiary); min-width: 56px; flex-shrink: 0; }

.gr-v { font-weight: 500; font-family: 'JetBrains Mono', monospace; font-size: 11px; }

.gk-row { display: flex; flex-wrap: wrap; gap: 12px; }

.gk-g { font-size: 12px; display: flex; align-items: center; gap: 4px; }

.gk-g kbd { background: var(--bg-normal); border: 1px solid var(--border-default); border-radius: 4px; padding: 1px 6px; font-size: 11px; font-family: 'JetBrains Mono', monospace; }
</style>
