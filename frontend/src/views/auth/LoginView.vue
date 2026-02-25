<script setup lang="ts">
/**
 * 登录页面
 */

import { ref, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { 
  ElForm, 
  ElFormItem, 
  ElInput, 
  ElButton,
  ElCheckbox,
  ElDivider,
  type FormInstance,
  type FormRules,
} from 'element-plus'
import { User, Lock } from '@element-plus/icons-vue'
import { useAuth } from '@/hooks'

const router = useRouter()
const { login, isLoading } = useAuth()

// ==================== 表单 ====================

const formRef = ref<FormInstance>()
const rememberMe = ref(false)

interface LoginFormData {
  username: string
  password: string
}

const formData = reactive<LoginFormData>({
  username: '',
  password: '',
})

const rules: FormRules<LoginFormData> = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { min: 3, max: 20, message: '用户名长度 3-20 个字符', trigger: 'blur' },
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, message: '密码至少 6 个字符', trigger: 'blur' },
  ],
}

// ==================== 方法 ====================

async function handleSubmit(): Promise<void> {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  
  await login({
    username: formData.username,
    password: formData.password,
  })
}

function goToRegister(): void {
  router.push('/register')
}
</script>

<template>
  <div class="login-page">
    <div class="login-card">
      <!-- Logo -->
      <div class="logo-section">
        <img src="/logo.svg" alt="Logo" class="logo" />
        <h1 class="title">StockAgent</h1>
        <p class="subtitle">智能股票分析平台</p>
      </div>
      
      <!-- 表单 -->
      <ElForm
        ref="formRef"
        :model="formData"
        :rules="rules"
        class="login-form"
        @submit.prevent="handleSubmit"
      >
        <ElFormItem prop="username">
          <ElInput
            v-model="formData.username"
            placeholder="用户名"
            size="large"
            :prefix-icon="User"
          />
        </ElFormItem>
        
        <ElFormItem prop="password">
          <ElInput
            v-model="formData.password"
            type="password"
            placeholder="密码"
            size="large"
            :prefix-icon="Lock"
            show-password
          />
        </ElFormItem>
        
        <div class="form-options">
          <ElCheckbox v-model="rememberMe">记住我</ElCheckbox>
          <a href="#" class="forgot-link">忘记密码?</a>
        </div>
        
        <ElFormItem>
          <ElButton
            type="primary"
            size="large"
            :loading="isLoading"
            class="submit-btn"
            native-type="submit"
          >
            登录
          </ElButton>
        </ElFormItem>
      </ElForm>
      
      <ElDivider>或者</ElDivider>
      
      <div class="register-link">
        还没有账号? 
        <a @click="goToRegister">立即注册</a>
      </div>
    </div>
  </div>
</template>

<style scoped lang="scss">
.login-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  padding: 20px;
}

.login-card {
  width: 100%;
  max-width: 400px;
  padding: 40px;
  background: white;
  border-radius: 16px;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.2);
}

.logo-section {
  text-align: center;
  margin-bottom: 32px;
  
  .logo {
    width: 64px;
    height: 64px;
    margin-bottom: 16px;
  }
  
  .title {
    font-size: 28px;
    font-weight: 700;
    color: #1a1a2e;
    margin: 0 0 8px 0;
  }
  
  .subtitle {
    font-size: 14px;
    color: #666;
    margin: 0;
  }
}

.login-form {
  .form-options {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 24px;
    
    .forgot-link {
      color: var(--el-color-primary);
      text-decoration: none;
      font-size: 14px;
      
      &:hover {
        text-decoration: underline;
      }
    }
  }
  
  .submit-btn {
    width: 100%;
  }
}

.register-link {
  text-align: center;
  color: #666;
  font-size: 14px;
  
  a {
    color: var(--el-color-primary);
    cursor: pointer;
    text-decoration: none;
    font-weight: 500;
    
    &:hover {
      text-decoration: underline;
    }
  }
}
</style>
