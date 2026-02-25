<script setup lang="ts">
// 认证页面布局
</script>

<template>
  <div class="auth-layout">
    <!-- 背景装饰 -->
    <div class="bg-decoration">
      <div class="circle circle-1"></div>
      <div class="circle circle-2"></div>
      <div class="circle circle-3"></div>
    </div>
    
    <!-- 左侧品牌区 -->
    <div class="brand-section">
      <div class="brand-content">
        <div class="brand-logo">
          <el-icon size="48" color="#fff"><TrendCharts /></el-icon>
        </div>
        <h1 class="brand-title">Stock Agent</h1>
        <p class="brand-desc">AI 驱动的智能股票分析系统</p>
        
        <div class="features">
          <div class="feature-item">
            <el-icon><DataAnalysis /></el-icon>
            <span>多维度智能分析</span>
          </div>
          <div class="feature-item">
            <el-icon><ChatDotRound /></el-icon>
            <span>自然语言交互</span>
          </div>
          <div class="feature-item">
            <el-icon><Timer /></el-icon>
            <span>实时行情推送</span>
          </div>
          <div class="feature-item">
            <el-icon><Aim /></el-icon>
            <span>个性化策略定制</span>
          </div>
        </div>
      </div>
    </div>
    
    <!-- 右侧表单区 -->
    <div class="form-section">
      <div class="form-container">
        <router-view v-slot="{ Component }">
          <transition name="fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </div>
      
      <div class="footer">
        <p>© 2024 Stock Agent. All rights reserved.</p>
      </div>
    </div>
  </div>
</template>

<style lang="scss" scoped>
.auth-layout {
  min-height: 100vh;
  display: flex;
  position: relative;
  overflow: hidden;
}

// 背景装饰
.bg-decoration {
  position: absolute;
  inset: 0;
  pointer-events: none;
  
  .circle {
    position: absolute;
    border-radius: 50%;
    background: linear-gradient(135deg, rgba(59, 130, 246, 0.1), rgba(147, 51, 234, 0.1));
  }
  
  .circle-1 {
    width: 600px;
    height: 600px;
    top: -200px;
    left: -100px;
  }
  
  .circle-2 {
    width: 400px;
    height: 400px;
    bottom: -100px;
    left: 30%;
  }
  
  .circle-3 {
    width: 300px;
    height: 300px;
    top: 20%;
    right: -50px;
  }
}

// 左侧品牌区
.brand-section {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #1e40af 0%, #7c3aed 100%);
  padding: 40px;
  position: relative;
  
  @media (max-width: 768px) {
    display: none;
  }
  
  .brand-content {
    max-width: 400px;
    color: #fff;
    text-align: center;
  }
  
  .brand-logo {
    width: 80px;
    height: 80px;
    background: rgba(255, 255, 255, 0.2);
    border-radius: 20px;
    display: flex;
    align-items: center;
    justify-content: center;
    margin: 0 auto 24px;
  }
  
  .brand-title {
    font-size: 36px;
    font-weight: 700;
    margin-bottom: 12px;
  }
  
  .brand-desc {
    font-size: 16px;
    opacity: 0.9;
    margin-bottom: 48px;
  }
  
  .features {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 16px;
    text-align: left;
    
    .feature-item {
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 12px 16px;
      background: rgba(255, 255, 255, 0.1);
      border-radius: 10px;
      font-size: 14px;
      
      .el-icon {
        font-size: 20px;
      }
    }
  }
}

// 右侧表单区
.form-section {
  width: 480px;
  min-width: 480px;
  display: flex;
  flex-direction: column;
  background: var(--bg-primary);
  
  @media (max-width: 768px) {
    width: 100%;
    min-width: 100%;
  }
  
  .form-container {
    flex: 1;
    display: flex;
    flex-direction: column;
    justify-content: center;
    padding: 40px 60px;
    
    @media (max-width: 768px) {
      padding: 40px 24px;
    }
  }
  
  .footer {
    padding: 20px;
    text-align: center;
    color: var(--text-tertiary);
    font-size: 12px;
  }
}

// 动画
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
