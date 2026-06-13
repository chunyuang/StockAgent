<script setup lang="ts">
/**
 * GuideTab — 系统引导Tab v2.9.92x
 * 重构布局: 3大板块(概览/策略/风控), 策略表格化, 操作指南更详细
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
          <div class="gb-sub">9层漏斗筛选 · 5策略联合选股 · 实时风控守护 · 参数对齐回测</div>
        </div>
      </div>
      <ElButton v-if="!isRunning" type="success" size="large" @click="startScanner" style="padding:10px 32px;font-size:15px">▶ 启动扫描器</ElButton>
      <ElButton v-else type="danger" size="large" @click="stopScanner" style="padding:10px 32px;font-size:15px">⏹ 停止扫描器</ElButton>
    </div>

    <!-- 第一行: 架构 + 操作指南 + 快捷键 -->
    <div class="guide-row2">
      <!-- 系统架构 -->
      <div class="gg-card">
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
          <div class="gf-layers">
            <div class="gf-layer"><span class="gfl-k">L1</span>流动性/市值过滤</div>
            <div class="gf-layer"><span class="gfl-k">L2</span>量能放大筛选</div>
            <div class="gf-layer"><span class="gfl-k">L3</span>MA60趋势过滤</div>
            <div class="gf-layer"><span class="gfl-k">L4</span>策略选股匹配</div>
            <div class="gf-layer"><span class="gfl-k">L5</span>成交概率估算</div>
            <div class="gf-layer"><span class="gfl-k">L6</span>情绪/板块过滤</div>
            <div class="gf-layer"><span class="gfl-k">L7</span>因子综合排序</div>
            <div class="gf-layer"><span class="gfl-k">L8</span>仓位/集中度控制</div>
            <div class="gf-layer"><span class="gfl-k">L9</span>信号生成+过期</div>
          </div>
        </div>
      </div>

      <!-- 操作指南 -->
      <div class="gg-card">
        <div class="gg-head"><span class="gg-icon">📖</span>操作指南</div>
        <div class="gg-body">
          <div class="go-list">
            <div class="go-row"><span class="sn">1</span><div><b>启动扫描器</b> → 每5分钟全量扫描 + 30秒持仓风控检查</div></div>
            <div class="go-row"><span class="sn">2</span><div><b>信号买入</b> → 信号区出现候选，点击"买"或按F9一键下单</div></div>
            <div class="go-row"><span class="sn">3</span><div><b>策略调参</b> → 左侧面板开关策略、编辑参数（与回测对齐）</div></div>
            <div class="go-row"><span class="sn">4</span><div><b>持仓管理</b> → 自动止盈止损 / 手动卖出 / 盘中冲高锁定</div></div>
            <div class="go-row"><span class="sn">5</span><div><b>强制扫描</b> → F5或⚡按钮立即扫描，跳过5分钟缓存</div></div>
            <div class="go-row"><span class="sn">6</span><div><b>交易详情</b> → 点击持仓/信号的🔍查看买卖因子和决策链路</div></div>
            <div class="go-row"><span class="sn">7</span><div><b>结果分析</b> → 分析Tab查看胜率/盈亏比/策略贡献/日收益</div></div>
            <div class="go-row"><span class="sn">8</span><div><b>复盘归因</b> → 复盘Tab查看日/周/月报告+前瞻建议</div></div>
            <div class="go-row"><span class="sn">9</span><div><b>风控状态</b> → 账户Tab查看止损风险+风控参数+情绪仓位</div></div>
            <div class="go-row"><span class="sn">⌨</span><div>快捷键: <kbd>F5</kbd>强扫 <kbd>F9</kbd>买入 <kbd>Ctrl+S</kbd>卖出 <kbd>Ctrl+E</kbd>紧急平仓 <kbd>↑↓</kbd>切换 <kbd>Enter</kbd>详情 <kbd>1-5</kbd>策略开关</div></div>
          </div>
        </div>
      </div>
    </div>

    <!-- 第二行: 策略一览 (表格形式，紧凑) -->
    <div class="gg-card" style="margin-top:10px">
      <div class="gg-head"><span class="gg-icon">🎯</span>5大策略一览</div>
      <div class="gg-body" style="padding:0">
        <table class="st-table">
          <thead><tr><th>策略</th><th>选股逻辑</th><th>关键参数</th><th>SL</th><th>TP</th><th>持仓</th><th>状态</th></tr></thead>
          <tbody>
            <tr>
              <td><span class="st-ico">🏃</span><b>半路追涨</b></td>
              <td>盘中涨幅3-7% + 量能1.5-3倍 + 收盘≥5%</td>
              <td>开盘≤3% · 冲高触发5% · 回落1.5% · 利润锁8%</td>
              <td class="sl">3%</td><td class="tp">12%</td><td>3天</td><td class="on">✅ 启用</td>
            </tr>
            <tr>
              <td><span class="st-ico">🥇</span><b>首板打板</b></td>
              <td>首次涨停封板 + 4级成交概率(秒20%/快45%/盘中55%)</td>
              <td>竞价-1%~5% · 换手8-15% · 流通市值50-500亿</td>
              <td class="sl">3.5%</td><td class="tp">10%</td><td>2天</td><td class="on">✅ 启用</td>
            </tr>
            <tr class="off-row">
              <td><span class="st-ico">🔓</span><b>涨停开板</b></td>
              <td>2-4连板开板回封 + 封单≥3000万</td>
              <td>开板≤5分钟 · 换手≥15%</td>
              <td class="sl">5%</td><td class="tp">6%</td><td>2天</td><td class="off">⏸ 暂停</td>
            </tr>
            <tr>
              <td><span class="st-ico">🐲</span><b>龙头低吸</b></td>
              <td>连板龙头回调5-22% + MA5支撑</td>
              <td>回调1-7天 · 量比0.5-2 · 利润锁6%</td>
              <td class="sl">3%</td><td class="tp">30%</td><td>7天</td><td class="on">✅ 启用</td>
            </tr>
            <tr>
              <td><span class="st-ico">💥</span><b>跌停翘板</b></td>
              <td>连续跌停≥2翘板反转 + 翘板涨幅≥3%</td>
              <td>换手≥10% · 流通市值≥20亿 · 利润锁10%</td>
              <td class="sl">5%</td><td class="tp">20%</td><td>3天</td><td class="on">✅ 启用</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 第三行: 风控体系 -->
    <div class="gg-card" style="margin-top:10px">
      <div class="gg-head"><span class="gg-icon">🛡️</span>风控体系</div>
      <div class="gg-body" style="padding:8px 12px">
        <div class="rk-grid">
          <!-- 第一组: 全局风控 -->
          <div class="rk-group">
            <div class="rk-gtitle">🔴 紧急风控</div>
            <div class="rk-row"><span class="rk-k">强制空仓</span><span class="rk-v">跌停≥80只 / 大盘跌≥3%</span></div>
            <div class="rk-row"><span class="rk-k">情绪仓位</span><span class="rk-v">高潮100% / 分化70% / 震荡50% / 冰点30%</span></div>
            <div class="rk-row"><span class="rk-k">冷却期</span><span class="rk-v">2天空仓期 · 仓位≤60%</span></div>
          </div>
          <!-- 第二组: 持仓保护 -->
          <div class="rk-group">
            <div class="rk-gtitle">🟡 持仓保护</div>
            <div class="rk-row"><span class="rk-k">单票/总仓位</span><span class="rk-v">35% / 75%</span></div>
            <div class="rk-row"><span class="rk-k">盘中锁定</span><span class="rk-v">冲高≥6% + 回撤≥2.5% → 利润保护</span></div>
            <div class="rk-row"><span class="rk-k">持仓保护</span><span class="rk-v">利润≥6%启用冲高回落 / 次日高开≥2%</span></div>
            <div class="rk-row"><span class="rk-k">追踪止损</span><span class="rk-v">默认2% / 龙头3% / 翘板4%</span></div>
          </div>
          <!-- 第三组: 买入过滤 -->
          <div class="rk-group">
            <div class="rk-gtitle">🔵 买入过滤</div>
            <div class="rk-row"><span class="rk-k">MA60过滤</span><span class="rk-v">股价在MA60上方才买入</span></div>
            <div class="rk-row"><span class="rk-k">板块集中</span><span class="rk-v">同行业≤3只</span></div>
            <div class="rk-row"><span class="rk-k">流动性</span><span class="rk-v">日均成交≥500万</span></div>
            <div class="rk-row"><span class="rk-k">信号过期</span><span class="rk-v">5分钟未执行自动取消</span></div>
          </div>
          <!-- 第四组: 检查机制 -->
          <div class="rk-group">
            <div class="rk-gtitle">🟢 运行保障</div>
            <div class="rk-row"><span class="rk-k">智能检查</span><span class="rk-v">盈利5s / 亏损3s / 接近止损1s</span></div>
            <div class="rk-row"><span class="rk-k">参数对齐</span><span class="rk-v">每晚22:00自动检查实盘vs回测</span></div>
            <div class="rk-row"><span class="rk-k">盘前自愈</span><span class="rk-v">9:25自动启动扫描器</span></div>
            <div class="rk-row"><span class="rk-k">崩溃恢复</span><span class="rk-v">持仓丢失检测+从订单重建</span></div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped lang="scss">
.mm-guide { flex: 1; overflow-y: auto; padding: 12px 16px; }

/* 横幅 */
.guide-banner { display: flex; align-items: center; justify-content: space-between; padding: 14px 20px; background: var(--bg-elevated); border-radius: 10px; margin-bottom: 10px; }
.gb-left { display: flex; align-items: center; gap: 14px; }
.gb-logo { font-size: 32px; }
.gb-title { font-size: 17px; font-weight: 700; }
.gb-sub { font-size: 12px; color: var(--text-secondary); margin-top: 2px; }

/* 双列行 */
.guide-row2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }

/* 通用卡片 */
.gg-card { background: var(--bg-elevated); border-radius: 10px; overflow: hidden; }
.gg-head { padding: 7px 14px; font-size: 13px; font-weight: 600; background: var(--bg-normal); border-bottom: 1px solid var(--border-light); }
.gg-icon { margin-right: 6px; }
.gg-body { padding: 10px 14px; }

/* 系统架构 */
.gf-flow { display: flex; align-items: center; gap: 5px; flex-wrap: wrap; margin-bottom: 8px; }
.gf-tag { padding: 3px 9px; border-radius: 5px; font-size: 11px; font-weight: 500; background: var(--bg-normal); border: 1px solid var(--border-default); }
.gf-tag.gf-input { background: var(--el-color-primary-light-5); border-color: var(--el-color-primary-light-3); color: var(--el-color-primary-dark-2); }
.gf-tag.gf-output { background: rgba(0,180,42,0.1); border-color: rgba(0,180,42,0.3); color: #00b42a; }
.gf-arrow { color: var(--text-tertiary); font-size: 10px; }
.gf-layers { display: grid; grid-template-columns: repeat(3, 1fr); gap: 3px; }
.gf-layer { font-size: 10px; color: var(--text-secondary); display: flex; align-items: center; gap: 4px; padding: 2px 0; }
.gfl-k { background: var(--bg-normal); border: 1px solid var(--border-light); border-radius: 3px; padding: 0 5px; font-size: 9px; font-weight: 600; color: var(--text-tertiary); min-width: 22px; text-align: center; }

/* 操作指南 */
.go-list { display: flex; flex-direction: column; gap: 4px; }
.go-row { display: flex; align-items: flex-start; gap: 8px; font-size: 12px; line-height: 1.6; }
.sn { background: var(--el-color-primary); color: #fff; border-radius: 4px; min-width: 20px; height: 20px; display: flex; align-items: center; justify-content: center; font-size: 10px; font-weight: 600; flex-shrink: 0; margin-top: 1px; }
.go-row b { font-weight: 600; }
.go-row kbd { background: var(--bg-normal); border: 1px solid var(--border-default); border-radius: 3px; padding: 0 5px; font-size: 10px; font-family: 'JetBrains Mono', monospace; }

/* 策略表格 */
.st-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.st-table th { background: var(--bg-normal); padding: 6px 10px; text-align: left; font-size: 11px; font-weight: 600; color: var(--text-secondary); border-bottom: 1px solid var(--border-light); white-space: nowrap; }
.st-table td { padding: 7px 10px; border-bottom: 1px solid var(--border-light); vertical-align: middle; }
.st-table tr:last-child td { border-bottom: none; }
.st-table tr:hover td { background: var(--bg-normal); }
.st-ico { margin-right: 4px; }
.st-table .sl { color: var(--stock-up); font-weight: 600; }
.st-table .tp { color: var(--stock-down); font-weight: 600; }
.st-table .on { color: #00b42a; font-size: 11px; }
.st-table .off { color: var(--text-tertiary); font-size: 11px; }
.off-row { opacity: 0.65; }
.off-row:hover { opacity: 1; }

/* 风控网格 */
.rk-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }
.rk-group { }
.rk-gtitle { font-size: 12px; font-weight: 600; margin-bottom: 6px; padding-bottom: 4px; border-bottom: 1px solid var(--border-light); }
.rk-row { display: flex; align-items: baseline; gap: 6px; font-size: 11px; line-height: 1.8; }
.rk-k { color: var(--text-tertiary); min-width: 60px; flex-shrink: 0; }
.rk-v { font-weight: 500; font-family: 'JetBrains Mono', monospace; font-size: 10.5px; }

/* 响应式 */
@media (max-width: 1100px) {
  .guide-row2 { grid-template-columns: 1fr; }
  .rk-grid { grid-template-columns: repeat(2, 1fr); }
}
</style>
