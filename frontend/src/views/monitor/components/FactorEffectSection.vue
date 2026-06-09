<script setup lang="ts">
/**
 * FactorEffectSection — 📊 因子效果跟踪子组件
 * 
 * 从ReviewTab.vue提取【v2.9.86】
 * 展示因子效果统计、市场漂移告警和因子衰减告警
 */
defineProps<{
  factorEffectData: any
}>()
</script>

<template>
  <div class="st" style="margin-top:8px">📊 因子效果跟踪 <span style="font-weight:normal;font-size:11px;color:var(--text-tertiary)">(市场漂移检测)</span></div>
  <div v-if="factorEffectData" class="factor-effect-section">
    <!-- 因子衰减告警(v2.9.86新增) -->
    <div v-if="factorEffectData.decay_alerts?.length" class="violations-list" style="margin-bottom:6px">
      <div v-for="(d, i) in factorEffectData.decay_alerts" :key="'decay-'+i" class="violation-item sev-high">
        <span class="v-icon">📉</span><span class="v-type">{{ d.factor }}</span><span class="v-detail">{{ d.alert }}</span><span class="v-detail" style="color:var(--text-tertiary)">👉 {{ d.action }}</span>
      </div>
    </div>
    <!-- 市场漂移告警 -->
    <div v-if="factorEffectData.drift_alerts?.length" class="violations-list" style="margin-bottom:8px">
      <div v-for="(a, i) in factorEffectData.drift_alerts" :key="i" class="violation-item sev-medium">
        <span class="v-icon">⚠️</span><span class="v-type">{{ a.factor }}/{{ a.bucket }}</span><span class="v-detail">{{ a.alert }}</span>
      </div>
    </div>
    <!-- 因子统计 -->
    <div v-for="(periods, fname) in factorEffectData.factor_stats || {}" :key="fname" class="factor-group">
      <div class="factor-name">{{ fname }}</div>
      <div v-for="(items, period) in periods" :key="period" class="factor-period">
        <div class="factor-period-label">{{ period }}</div>
        <div class="factor-bars">
          <div v-for="it in items?.slice(0, 5)" :key="it.name" class="factor-bar-row">
            <span class="fb-name">{{ it.name }}</span>
            <div class="fb-bar-bg"><div class="fb-bar-fill" :style="{width: it.total > 0 ? Math.min(it.win_rate, 100) + '%' : '0%'}" :class="it.win_rate >= 60 ? 'fb-up' : it.win_rate >= 40 ? 'fb-mid' : 'fb-down'"></div></div>
            <span class="fb-wr" :class="it.win_rate >= 60 ? 'up' : 'down'">{{ it.win_rate }}%</span>
            <span class="fb-cnt">({{ it.total }})</span>
          </div>
        </div>
      </div>
    </div>
  </div>
  <div v-else class="empty">无因子数据</div>
</template>

<style scoped>
.factor-effect-section { display: flex; flex-direction: column; gap: 8px; }
.factor-group { background: var(--bg-elevated); border-radius: 8px; padding: 8px; }
.factor-name { font-size: 11px; font-weight: 600; margin-bottom: 4px; }
.factor-period { margin-bottom: 6px; }
.factor-period-label { font-size: 10px; color: var(--text-tertiary); margin-bottom: 2px; }
.factor-bars { display: flex; flex-direction: column; gap: 2px; }
.factor-bar-row { display: flex; align-items: center; gap: 6px; }
.fb-name { width: 60px; font-size: 10px; text-align: right; color: var(--text-secondary); }
.fb-bar-bg { flex: 1; height: 14px; background: var(--bg-elevated); border-radius: 3px; overflow: hidden; }
.fb-bar-fill { height: 100%; border-radius: 3px; transition: width 0.3s; }
.fb-up { background: var(--color-up, #f56c6c); }
.fb-mid { background: var(--color-warn, #e6a23c); }
.fb-down { background: var(--color-down, #67c23a); }
.fb-wr { width: 36px; font-size: 10px; font-weight: 600; text-align: right; }
.fb-cnt { width: 28px; font-size: 9px; color: var(--text-tertiary); }
.violations-list { display: flex; flex-direction: column; gap: 3px; }
.violation-item { display: flex; align-items: center; gap: 4px; padding: 3px 6px; border-radius: 4px; font-size: 11px; }
.violation-item.sev-high { background: rgba(245,108,108,0.1); }
.violation-item.sev-medium { background: rgba(230,162,60,0.1); }
.v-icon { font-size: 12px; }
.v-type { font-weight: 600; min-width: 50px; }
.v-detail { color: var(--text-secondary); }
.empty { color: var(--text-tertiary); font-size: 12px; padding: 8px 0; }
</style>
