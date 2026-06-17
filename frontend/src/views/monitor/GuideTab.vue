<script setup lang="ts">
/**
 * GuideTab — 系统引导Tab v2.9.92x
 * 重构布局: 3大板块(概览/策略/风控), 策略表格化, 操作指南更详细
 */
</script>

<template>
  <div class="mm-guide">
    <!-- 第一行: 架构 + 操作指南 + 快捷键 -->
    <div class="guide-row2">
      <!-- 系统架构 -->
      <div class="gg-card">
        <div class="gg-head"><span class="gg-icon">🏗️</span>系统架构</div>
        <div class="gg-body">
          <div class="gf-flow gf-flow-rail">
            <div class="gf-tag gf-input"><span>01</span><b>行情输入</b><small>全市场实时行情</small></div>
            <div class="gf-tag"><span>02</span><b>环境风控</b><small>L1~L3 风险/情绪</small></div>
            <div class="gf-tag"><span>03</span><b>策略过滤</b><small>L4~L6 回测条件</small></div>
            <div class="gf-tag"><span>04</span><b>排序控仓</b><small>L7~L8 去重/仓位</small></div>
            <div class="gf-tag gf-output"><span>05</span><b>执行反馈</b><small>L9 候选/成交</small></div>
          </div>
          <div class="gf-layers gf-layers-live">
            <div class="gf-layer"><span class="gfl-k">L1</span><b>强制空仓</b><em>回测对齐</em><small>跌停≥80 / 涨停≤10且跌停&gt;0 / 大盘跌≥3%</small></div>
            <div class="gf-layer"><span class="gfl-k">L2</span><b>特殊时期</b><em>实盘扩展</em><small>月末/季末/年末/节前降仓</small></div>
            <div class="gf-layer"><span class="gfl-k">L3</span><b>情绪周期</b><em>回测对齐+盘中增强</em><small>高潮100% / 分化70% / 震荡50% / 冰点25%</small></div>
            <div class="gf-layer"><span class="gfl-k">L4</span><b>盘前预选</b><em>回测基础过滤</em><small>ST/退市/次新&lt;60天/低流动&lt;500万</small></div>
            <div class="gf-layer"><span class="gfl-k">L5</span><b>竞价过滤</b><em>实盘优势</em><small>首板2~7%；其他策略仅排除&gt;7%/&lt;-5%</small></div>
            <div class="gf-layer"><span class="gfl-k">L6</span><b>策略量能</b><em>复用回测</em><small>调用回测策略条件：涨幅/量比/换手/封板/翘板等</small></div>
            <div class="gf-layer"><span class="gfl-k">L7</span><b>综合排序</b><em>实盘执行控制</em><small>同股多策略取最高；龙头&gt;翘板&gt;首板&gt;半路；最多10股×策略</small></div>
            <div class="gf-layer"><span class="gfl-k">L8</span><b>仓位控制</b><em>回测风险参数</em><small>情绪×特殊时期×硬上限；单票/总仓位限制</small></div>
            <div class="gf-layer"><span class="gfl-k">L9</span><b>执行确认</b><em>实盘特有</em><small>资金/T+1/集中度/成交概率/订单状态，最终看候选追踪</small></div>
          </div>
          <div class="gf-note">说明：L6核心选股条件复用回测；L1/L3/L8与回测风险框架对齐；L5使用真实竞价是实盘优势，回测只能用开盘价近似；L9是实盘执行层，回测没有真实订单撮合。</div>
        </div>
      </div>

      <!-- 操作指南 -->
      <div class="gg-card">
        <div class="gg-head"><span class="gg-icon">📖</span>操作指南</div>
        <div class="gg-body">
          <div class="go-list go-list-live">
            <div class="go-row"><span class="sn">01</span><b>盘前准备</b><small>确认扫描器、行情源、账户资金和策略开关；9:25 后可看竞价时间线。</small><em>启动/自检</em></div>
            <div class="go-row"><span class="sn">02</span><b>竞价观察</b><small>查看每次竞价快照：候选、过滤、情绪、Top标的，不只看单一当前值。</small><em>9:00~9:30</em></div>
            <div class="go-row"><span class="sn">03</span><b>全量扫描</b><small>盘中按周期扫描全市场；需要立即刷新时用强制扫描，跳过缓存。</small><em>F5/⚡</em></div>
            <div class="go-row"><span class="sn">04</span><b>候选追踪</b><small>从扫描历史展开 L1~L9 详情；成交 scan 黄色高亮，便于和未成交区分。</small><em>追踪归因</em></div>
            <div class="go-row"><span class="sn">05</span><b>买入执行</b><small>候选进入执行层后校验资金、T+1、集中度、成交概率；支持自动/手动确认。</small><em>F9/买入</em></div>
            <div class="go-row"><span class="sn">06</span><b>持仓风控</b><small>账户页核对现金、持仓、市值；系统持续检查止损、近止损、冲高回落和追踪止损。</small><em>风控守护</em></div>
            <div class="go-row"><span class="sn">07</span><b>交易审查</b><small>点击持仓/成交查看个股买入原因、策略、成本、现价、浮盈亏和交易记录。</small><em>逐笔详情</em></div>
            <div class="go-row"><span class="sn">08</span><b>复盘分析</b><small>分析/复盘查看胜率、盈亏比、策略贡献、日周月报告和前瞻建议。</small><em>盘后复盘</em></div>
            <div class="go-row"><span class="sn">09</span><b>参数对齐</b><small>策略参数以回测基准为参照；修改实盘参数后要检查是否与回测预期一致。</small><em>回测一致</em></div>
            <div class="go-hotkeys"><b>快捷键</b><span><kbd>F5</kbd>强扫</span><span><kbd>F9</kbd>买入</span><span><kbd>Ctrl+S</kbd>卖出</span><span><kbd>Ctrl+E</kbd>紧急平仓</span><span><kbd>Enter</kbd>详情</span></div>
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

/* 双列行 */
.guide-row2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }

/* 通用卡片 */
.gg-card { background: var(--bg-elevated); border-radius: 10px; overflow: hidden; }
.gg-head { padding: 7px 14px; font-size: 13px; font-weight: 600; background: var(--bg-normal); border-bottom: 1px solid var(--border-light); }
.gg-icon { margin-right: 6px; }
.gg-body { padding: 10px 14px; }

/* 系统架构 */
.gf-flow { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 6px; margin-bottom: 10px; }
.gf-tag { position: relative; padding: 7px 8px; border-radius: 8px; font-size: 11px; font-weight: 600; text-align: center; background: var(--bg-normal); border: 1px solid var(--border-default); line-height: 1.25; }
.gf-flow-rail .gf-tag { display: flex; flex-direction: column; gap: 3px; min-height: 54px; justify-content: center; }
.gf-flow-rail .gf-tag span { font-family: 'JetBrains Mono', monospace; font-size: 9px; color: var(--text-tertiary); }
.gf-flow-rail .gf-tag b { color: var(--text-primary); font-size: 12px; }
.gf-flow-rail .gf-tag small { color: var(--text-secondary); font-size: 10px; font-weight: 500; }
.gf-tag.gf-input { background: var(--el-color-primary-light-5); border-color: var(--el-color-primary-light-3); color: var(--el-color-primary-dark-2); }
.gf-tag.gf-output { background: rgba(0,180,42,0.1); border-color: rgba(0,180,42,0.3); color: #00b42a; }
.gf-tag.gf-input b, .gf-tag.gf-input small { color: var(--el-color-primary-dark-2); }
.gf-tag.gf-output b, .gf-tag.gf-output small { color: #00b42a; }
.gf-arrow { display: none; }
.gf-layers { display: grid; grid-template-columns: repeat(3, 1fr); gap: 3px; }
.gf-layer { font-size: 10px; color: var(--text-secondary); display: flex; align-items: center; gap: 4px; padding: 2px 0; }
.gfl-k { background: var(--bg-normal); border: 1px solid var(--border-light); border-radius: 3px; padding: 0 5px; font-size: 9px; font-weight: 600; color: var(--text-tertiary); min-width: 22px; text-align: center; }
.gf-layers-live { grid-template-columns: 1fr; gap: 5px; }
.gf-layers-live .gf-layer { display: grid; grid-template-columns: 34px 72px 1fr auto; align-items: center; gap: 8px; background: var(--bg-normal); border: 1px solid var(--border-light); border-radius: 7px; padding: 7px 9px; line-height: 1.35; }
.gf-layers-live .gfl-k { background: var(--el-color-primary-light-9); border-color: var(--el-color-primary-light-5); color: var(--el-color-primary); font-size: 10px; }
.gf-layers-live .gf-layer b { color: var(--text-primary); font-size: 12px; white-space: nowrap; }
.gf-layers-live .gf-layer em { justify-self: end; font-style: normal; color: var(--el-color-primary); background: rgba(64,158,255,0.1); border: 1px solid rgba(64,158,255,0.18); border-radius: 999px; padding: 1px 7px; font-size: 10px; white-space: nowrap; }
.gf-layers-live .gf-layer small { color: var(--text-secondary); font-size: 11px; line-height: 1.35; }
.gf-note { margin-top: 10px; padding: 9px 10px; border-radius: 7px; border-left: 3px solid var(--el-color-primary); background: rgba(64,158,255,0.08); color: var(--text-secondary); font-size: 11px; line-height: 1.55; }

/* 操作指南 */
.go-list { display: flex; flex-direction: column; gap: 4px; }
.go-list-live { gap: 5px; }
.go-row { display: flex; align-items: flex-start; gap: 8px; font-size: 12px; line-height: 1.6; }
.go-list-live .go-row { display: grid; grid-template-columns: 34px 72px 1fr auto; align-items: center; gap: 8px; background: var(--bg-normal); border: 1px solid var(--border-light); border-radius: 7px; padding: 7px 9px; min-height: 42px; }
.sn { background: var(--el-color-primary); color: #fff; border-radius: 4px; min-width: 20px; height: 20px; display: flex; align-items: center; justify-content: center; font-size: 10px; font-weight: 600; flex-shrink: 0; margin-top: 1px; }
.go-list-live .sn { min-width: 30px; height: 22px; margin-top: 0; font-family: 'JetBrains Mono', monospace; background: rgba(0,180,42,0.12); color: #00a870; border: 1px solid rgba(0,180,42,0.22); }
.go-row b { font-weight: 600; }
.go-list-live .go-row b { color: var(--text-primary); font-size: 12px; white-space: nowrap; }
.go-list-live .go-row small { color: var(--text-secondary); font-size: 11px; line-height: 1.35; }
.go-list-live .go-row em { justify-self: end; font-style: normal; color: #00a870; background: rgba(0,180,42,0.1); border: 1px solid rgba(0,180,42,0.18); border-radius: 999px; padding: 1px 7px; font-size: 10px; white-space: nowrap; }
.go-row kbd, .go-hotkeys kbd { background: var(--bg-elevated); border: 1px solid var(--border-default); border-radius: 3px; padding: 0 5px; font-size: 10px; font-family: 'JetBrains Mono', monospace; }
.go-hotkeys { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; margin-top: 2px; padding: 8px 10px; border-radius: 7px; background: rgba(0,180,42,0.06); color: var(--text-secondary); font-size: 11px; }
.go-hotkeys b { color: var(--text-primary); margin-right: 2px; }
.go-hotkeys span { display: inline-flex; align-items: center; gap: 3px; }

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
