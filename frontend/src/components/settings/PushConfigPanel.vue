<script setup lang="ts">
/**
 * PushConfigPanel - 推送配置面板
 * 配置企业微信Webhook、飞书推送、通知开关等
 */
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { systemApi } from '@/api'
import {
  ElForm,
  ElFormItem,
  ElInput,
  ElSwitch,
  ElButton,
  ElAlert,
  ElDivider,
  ElInputNumber,
} from 'element-plus'

const form = reactive({
  // 通知开关
  notify_enabled: true,
  // 企业微信Webhook
  wecom_webhook: '',
  // 飞书推送
  feishu_enabled: false,
  feishu_webhook: '',
  feishu_app_id: '',
  feishu_app_secret: '',
  feishu_bitable_app_token: '',
  // 最小发送间隔
  min_interval: 10,
  // 最小置信度阈值
  min_confidence: 0,
})

const saving = ref(false)
const testing = ref(false)

/** 加载配置 */
async function loadConfig() {
  try {
    const res = await systemApi.getPushConfig()
    if (res?.success && res?.config) {
      // 后端返回字段是 config 对象
      Object.assign(form, res.config)
      return
    }
  } catch { /* fallback */ }
  try {
    const saved = localStorage.getItem('push_config')
    if (saved) {
      const data = JSON.parse(saved)
      Object.assign(form, data)
    }
  } catch { /* ignore */ }
}

/** 保存配置 */
async function saveConfig() {
  try {
    saving.value = true
    try {
      await systemApi.savePushConfig(form as any)
      ElMessage.success('推送配置已保存到服务器')
    } catch {
      localStorage.setItem('push_config', JSON.stringify(form))
      ElMessage.success('推送配置已保存到本地（服务器暂不可用）')
    }
  } catch (e: any) {
    ElMessage.error(`保存失败: ${e.message || '未知错误'}`)
  } finally {
    saving.value = false
  }
}

/** 测试推送 */
async function testPush() {
  if (!form.wecom_webhook && !form.feishu_enabled) {
    ElMessage.warning('请先配置推送地址')
    return
  }
  try {
    testing.value = true
    const type = form.wecom_webhook ? 'wecom' : 'feishu'
    try {
      await systemApi.sendTestPush(type)
      ElMessage.success('测试消息已发送，请检查接收端')
    } catch {
      ElMessage.warning('测试推送接口暂不可用，请手动验证配置')
    }
  } catch (e: any) {
    ElMessage.error(`测试失败: ${e.message || '未知错误'}`)
  } finally {
    testing.value = false
  }
}

onMounted(() => {
  loadConfig()
})
</script>

<template>
  <div class="push-config-panel">
    <div class="section-title">🔔 推送通知配置</div>

    <ElForm label-width="140px" size="small">
      <!-- 通知总开关 -->
      <ElFormItem label="启用推送通知">
        <ElSwitch v-model="form.notify_enabled" active-text="开" inactive-text="关" />
      </ElFormItem>

      <ElDivider content-position="left">企业微信推送</ElDivider>

      <ElFormItem label="Webhook地址">
        <ElInput
          v-model="form.wecom_webhook"
          placeholder="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=..."
          type="password"
          show-password
        />
      </ElFormItem>
      <ElFormItem>
        <ElAlert
          v-if="form.wecom_webhook"
          title="Webhook已配置"
          type="success"
          :closable="false"
          show-icon
        />
        <ElAlert
          v-else
          title="未配置Webhook，将无法接收企业微信推送"
          type="warning"
          :closable="false"
          show-icon
        />
      </ElFormItem>

      <ElDivider content-position="left">飞书推送</ElDivider>

      <ElFormItem label="启用飞书推送">
        <ElSwitch v-model="form.feishu_enabled" active-text="开" inactive-text="关" />
      </ElFormItem>
      <template v-if="form.feishu_enabled">
        <ElFormItem label="Webhook地址">
          <ElInput v-model="form.feishu_webhook" placeholder="https://open.feishu.cn/open-apis/bot/v2/hook/..." type="password" show-password />
        </ElFormItem>
        <ElFormItem label="App ID">
          <ElInput v-model="form.feishu_app_id" placeholder="飞书应用 App ID" />
        </ElFormItem>
        <ElFormItem label="App Secret">
          <ElInput v-model="form.feishu_app_secret" placeholder="飞书应用 App Secret" type="password" show-password />
        </ElFormItem>
        <ElFormItem label="多维表格Token">
          <ElInput v-model="form.feishu_bitable_app_token" placeholder="多维表格 App Token（可选）" />
        </ElFormItem>
      </template>

      <ElDivider content-position="left">高级设置</ElDivider>

      <ElFormItem label="最小发送间隔(秒)">
        <ElInputNumber v-model="form.min_interval" :min="1" :max="300" :step="5" />
        <span class="form-hint">防止消息刷屏，两次推送的最小间隔</span>
      </ElFormItem>

      <ElFormItem label="最小置信度(%)">
        <ElInputNumber v-model="form.min_confidence" :min="0" :max="100" :step="10" />
        <span class="form-hint">低于此置信度的信号不推送（0=不过滤）</span>
      </ElFormItem>

      <ElFormItem>
        <ElButton type="primary" @click="saveConfig" :loading="saving">保存配置</ElButton>
        <ElButton @click="testPush" :loading="testing">发送测试消息</ElButton>
      </ElFormItem>
    </ElForm>
  </div>
</template>

<script lang="ts">
export default { name: 'PushConfigPanel' }
</script>

<style scoped>
.push-config-panel { padding: 8px 0; }
.section-title {
  font-size: 15px;
  font-weight: 600;
  margin-bottom: 16px;
  color: var(--el-text-color-primary);
}
.form-hint {
  font-size: 11px;
  color: var(--el-text-color-placeholder);
  margin-left: 8px;
}
</style>
