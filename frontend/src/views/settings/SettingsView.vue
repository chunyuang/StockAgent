<script setup lang="ts">
import { ref } from 'vue'
import { useUserStore } from '@/stores/user'
import { ElMessage } from 'element-plus'

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
    
    <el-tabs v-model="activeTab" class="settings-tabs">
      <!-- 偏好设置 -->
      <el-tab-pane label="偏好设置" name="preferences">
        <div class="settings-section card">
          <el-form label-width="100px" size="large">
            <el-form-item label="主题">
              <el-radio-group v-model="preferences.theme">
                <el-radio value="light">浅色</el-radio>
                <el-radio value="dark">深色</el-radio>
              </el-radio-group>
            </el-form-item>
            
            <el-form-item label="消息通知">
              <el-switch v-model="preferences.notification_enabled" />
            </el-form-item>
            
            <el-form-item>
              <el-button type="primary" :loading="prefSaving" @click="savePreferences">
                保存设置
              </el-button>
            </el-form-item>
          </el-form>
        </div>
      </el-tab-pane>

      <!-- 推送配置 -->
      <el-tab-pane label="推送配置" name="push">
        <div class="settings-section card">
          <PushConfigPanel />
        </div>
      </el-tab-pane>

      <!-- 日志级别 -->
      <el-tab-pane label="日志级别" name="logging">
        <div class="settings-section card">
          <LogLevelPanel />
        </div>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<style lang="scss" scoped>
.settings-view {
  max-width: 800px;
  margin: 0 auto;
  
  h1 {
    font-size: 24px;
    font-weight: 600;
    margin-bottom: 24px;
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
