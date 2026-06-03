<script setup lang="ts">
/**
 * GuideTab — 系统引导Tab
 * 从 MarketMonitorView provide/inject 获取composable数据
 * 【v2.9.74: 从MarketMonitorView提取(132行)】
 */
import { useScannerMonitorInject } from './scannerMonitorInject'
import { ElButton } from 'element-plus'

const { startScanner } = useScannerMonitorInject()
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
      <ElButton type="success" size="large" @click="startScanner" style="padding:10px 32px;font-size:15px">▶ 启动扫描器</ElButton>
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
