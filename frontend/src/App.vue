<script setup lang="ts">
/**
 * 根组件
 */
import { onMounted } from 'vue'
import { ElConfigProvider } from 'element-plus'
import zhCn from 'element-plus/dist/locale/zh-cn.mjs'
import { useAuth } from '@/hooks'

const { checkAuth } = useAuth()

onMounted(async () => {
  // 检查登录状态
  await checkAuth()
})
</script>

<template>
  <ElConfigProvider :locale="zhCn">
    <RouterView />
  </ElConfigProvider>
</template>

<style>
#app {
  min-height: 100vh;
}
</style>
