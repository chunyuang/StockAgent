<script setup lang="ts">
import { ref } from 'vue'
import { useUserStore } from '@/stores/user'
import { ElMessage, ElTabs, ElTabPane, ElForm, ElFormItem, ElRadioGroup, ElRadio, ElSwitch, ElButton } from 'element-plus'

// 子组件
import PushConfigPanel from '@/components/settings/PushConfigPanel.vue'
import LogLevelPanel from '@/components/settings/LogLevelPanel.vue'

const userStore = useUserStore()

// 活跃标签页
const activeTab = ref('preferences')

// 偏好设置
const preferences = ref({
  theme: (userStore.preferences as any)?.theme || 'light',
  notification_enabled: (userStore.preferences as any)?.notification_enabled ?? true,
})
const prefSaving = ref(false)

// 保存偏好设置
async function savePreferences() {
  prefSaving.value = true
  try {
    await userStore.updatePreferences(preferences.value)
    ElMessage.success('设置已保存')
  } finally {
    prefSaving.value = false
  }
}
</script>

<template>
  <div class="settings-view">
    <h1>设置</h1>
    
    <ElTabs v-model="activeTab" class="settings-tabs">
      <!-- 偏好设置 -->
      <ElTabPane label="偏好设置" name="preferences">
        <div class="settings-section card">
          <ElForm label-width="100px" size="large">
            <ElFormItem label="主题">
              <ElRadioGroup v-model="preferences.theme">
                <ElRadio value="light">浅色</ElRadio>
                <ElRadio value="dark">深色</ElRadio>
              </ElRadioGroup>
            </ElFormItem>
            
            <ElFormItem label="消息通知">
              <ElSwitch v-model="preferences.notification_enabled" />
            </ElFormItem>
            
            <ElFormItem>
              <ElButton type="primary" :loading="prefSaving" @click="savePreferences">
                保存设置
              </ElButton>
            </ElFormItem>
          </ElForm>
        </div>
      </ElTabPane>

      <!-- 推送配置 -->
      <ElTabPane label="推送配置" name="push">
        <div class="settings-section card">
          <PushConfigPanel />
        </div>
      </ElTabPane>

      <!-- 日志级别 -->
      <ElTabPane label="日志级别" name="logging">
        <div class="settings-section card">
          <LogLevelPanel />
        </div>
      </ElTabPane>
    </ElTabs>
  </div>
</template>

<style lang="scss" scoped>
.settings-view {
  max-width: 900px;
  margin: 0 auto;
  padding: 16px;
  min-width: 0;
  
  h1 {
    font-size: 20px;
    font-weight: 600;
    margin-bottom: 20px;
  }
}

.settings-tabs {
  :deep(.el-tabs__content) {
    padding-top: 20px;
  }
}

.settings-section {
  padding: 24px;
  
  h3 {
    margin-bottom: 20px;
  }
}
</style>
