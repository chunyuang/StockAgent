<script setup lang="ts">
/**
 * LogLevelPanel - 日志级别配置面板
 * 配置系统日志级别、日志输出方式、关键事件过滤
 */
import { ref, reactive, onMounted, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { systemApi } from '@/api'
import {
  ElForm,
  ElFormItem,
  ElSelect,
  ElOption,
  ElSwitch,
  ElButton,
  ElAlert,
  ElDivider,
  ElCheckboxGroup,
  ElCheckbox,
  ElTag,
} from 'element-plus'

const LOG_LEVELS = [
  { value: 'DEBUG', label: 'DEBUG - 调试', desc: '输出所有日志，用于开发调试' },
  { value: 'INFO', label: 'INFO - 信息', desc: '输出常规运行日志（推荐）' },
  { value: 'WARNING', label: 'WARNING - 警告', desc: '仅输出警告和错误' },
  { value: 'ERROR', label: 'ERROR - 错误', desc: '仅输出错误日志' },
]

const form = reactive({
  // 全局日志级别
  log_level: 'INFO',
  // 回测引擎日志级别
  backtest_log_level: 'INFO',
  // 交易信号日志级别
  signal_log_level: 'INFO',
  // 控制台输出
  console_output: true,
  // 文件输出
  file_output: true,
  // 关键事件通知
  notify_events: ['trade_executed', 'signal_generated', 'backtest_completed', 'error_occurred'] as string[],
})

const saving = ref(false)

const eventOptions = [
  { value: 'trade_executed', label: '交易执行' },
  { value: 'signal_generated', label: '信号生成' },
  { value: 'backtest_completed', label: '回测完成' },
  { value: 'position_changed', label: '持仓变动' },
  { value: 'risk_alert', label: '风控预警' },
  { value: 'error_occurred', label: '系统错误' },
]

const currentLevelDesc = computed(() => {
  const level = LOG_LEVELS.find(l => l.value === form.log_level)
  return level?.desc || ''
})

async function loadConfig() {
  try {
    const res = await systemApi.getLogLevelConfig()
    if (res?.success && res?.data) {
      Object.assign(form, res.data)
      return
    }
  } catch { /* fallback */ }
  try {
    const saved = localStorage.getItem('log_config')
    if (saved) {
      const data = JSON.parse(saved)
      Object.assign(form, data)
    }
  } catch { /* ignore */ }
}

async function saveConfig() {
  try {
    saving.value = true
    try {
      await systemApi.saveLogLevelConfig(form as any)
      ElMessage.success('日志配置已保存到服务器')
    } catch {
      localStorage.setItem('log_config', JSON.stringify(form))
      ElMessage.success('日志配置已保存到本地（服务器暂不可用）')
    }
  } catch (e: any) {
    ElMessage.error(`保存失败: ${e.message || '未知错误'}`)
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  loadConfig()
})
</script>

<template>
  <div class="log-level-panel">
    <div class="section-title">📝 日志级别配置</div>

    <ElForm label-width="160px" size="small">
      <!-- 全局日志级别 -->
      <ElFormItem label="全局日志级别">
        <ElSelect v-model="form.log_level" style="width: 260px">
          <ElOption
            v-for="level in LOG_LEVELS"
            :key="level.value"
            :label="level.label"
            :value="level.value"
          />
        </ElSelect>
      </ElFormItem>
      <ElFormItem>
        <ElAlert :title="currentLevelDesc" type="info" :closable="false" show-icon />
      </ElFormItem>

      <ElDivider content-position="left">模块级别配置</ElDivider>

      <ElFormItem label="回测引擎日志级别">
        <ElSelect v-model="form.backtest_log_level" style="width: 200px">
          <ElOption v-for="level in LOG_LEVELS" :key="level.value" :label="level.label" :value="level.value" />
        </ElSelect>
        <ElTag size="small" type="info" style="margin-left: 8px">backtest_engine</ElTag>
      </ElFormItem>

      <ElFormItem label="交易信号日志级别">
        <ElSelect v-model="form.signal_log_level" style="width: 200px">
          <ElOption v-for="level in LOG_LEVELS" :key="level.value" :label="level.label" :value="level.value" />
        </ElSelect>
        <ElTag size="small" type="info" style="margin-left: 8px">signal_generator</ElTag>
      </ElFormItem>

      <ElDivider content-position="left">日志输出</ElDivider>

      <ElFormItem label="控制台输出">
        <ElSwitch v-model="form.console_output" active-text="开" inactive-text="关" />
      </ElFormItem>

      <ElFormItem label="文件输出">
        <ElSwitch v-model="form.file_output" active-text="开" inactive-text="关" />
      </ElFormItem>

      <ElDivider content-position="left">关键事件通知</ElDivider>

      <ElFormItem label="通知事件">
        <ElCheckboxGroup v-model="form.notify_events">
          <ElCheckbox
            v-for="evt in eventOptions"
            :key="evt.value"
            :value="evt.value"
            :label="evt.value"
          >
            {{ evt.label }}
          </ElCheckbox>
        </ElCheckboxGroup>
      </ElFormItem>
      <ElFormItem>
        <ElAlert
          title="选中的事件将触发推送通知（需配合推送配置使用）"
          type="info"
          :closable="false"
          show-icon
        />
      </ElFormItem>

      <ElFormItem>
        <ElButton type="primary" @click="saveConfig" :loading="saving">保存配置</ElButton>
      </ElFormItem>
    </ElForm>
  </div>
</template>

<script lang="ts">
export default { name: 'LogLevelPanel' }
</script>

<style scoped>
.log-level-panel { padding: 8px 0; }
.section-title {
  font-size: 15px;
  font-weight: 600;
  margin-bottom: 16px;
  color: var(--el-text-color-primary);
}
</style>
