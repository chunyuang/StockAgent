<script setup lang="ts">
/**
 * MongoDB 数据库管理页面
 * 功能：查看数据库统计、清理重复数据、检查缺失数据、验证完整性
 */
import { ref, reactive, onMounted, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

// 导入组件
import {
  ElCard,
  ElButton,
  ElTable,
  ElTableColumn,
  ElInput,
  ElInputNumber,
  ElDescriptions,
  ElTag,
  ElAlert,
  ElDivider,
  ElDialog,
  ElSwitch,
  ElForm,
  ElFormItem,
  ElProgress,
} from 'element-plus'

// 导入 API 客户端（自动注入认证 Token）
import { api } from '@/api'

// ==================== 状态 ====================

// 加载状态
const loading = ref(false)
const operating = ref(false)

// 数据库统计数据
const dbStats = ref<any>(null)

// 弹窗状态
const clearDateDialogVisible = ref(false)
const checkMissingDialogVisible = ref(false)
const deduplicateDialogVisible = ref(false)

// 表单数据
const clearDateForm = reactive({
  start_date: '',
  end_date: '',
  collection_name: '',
})

const deduplicateForm = reactive({
  collection_name: '',
  dry_run: true,
})

// 操作结果
const operationResult = ref<any>(null)
const showResult = ref(false)

// 白名单集合 - 只允许操作这些集合（与后端保持一致）
const ALLOWED_COLLECTIONS = [
  'stock_daily_ak_full',  // 日线行情完整版
  'daily_basic',         // 每日基本信息
  'index_daily',         // 指数日线
  'stock_daily_factors',  // 日线因子
  'stock_1min_factors',   // 1分钟因子
  'backtest_tasks',      // 回测任务
  'limit_list',          // 涨跌停列表
  'trade_cal',           // 交易日历
  'stock_basic',         // 股票基础信息
]

// ==================== 方法 ====================

// 获取数据库统计信息
const fetchStats = async () => {
  loading.value = true
  try {
    const result = await api.get('/admin/db/stats')
    if (result.success) {
      dbStats.value = result.data
      ElMessage.success('获取统计信息成功')
    } else {
      ElMessage.error(result.message || '获取统计信息失败')
    }
  } catch (error) {
    console.error('获取统计信息失败:', error)
    ElMessage.error('获取统计信息失败: ' + (error as Error).message)
  } finally {
    loading.value = false
  }
}

// 清空指定集合
const handleClearCollection = async (collectionName: string) => {
  try {
    await ElMessageBox.confirm(
      `⚠️  危险操作！确定要清空集合 **${collectionName}** 吗？\n\n此操作会删除集合中的所有数据，删除后无法恢复！`,
      '二次确认',
      {
        confirmButtonText: '确定清空',
        cancelButtonText: '取消',
        type: 'warning',
        dangerouslyUseHTMLString: true,
      }
    )

    operating.value = true
    const result = await api.post(`/admin/db/clear-collection/${collectionName}`, { confirm: true })
    if (result.success) {
      ElMessage.success(`集合 ${collectionName} 清空成功`)
      operationResult.value = result.data
      showResult.value = true
      fetchStats() // 刷新统计
    } else {
      ElMessage.error(result.message || '清空失败')
    }
  } catch (error) {
    if (error !== 'cancel') {
      console.error('清空集合失败:', error)
      ElMessage.error('清空集合失败: ' + (error as Error).message)
    }
  } finally {
    operating.value = false
  }
}

// 打开清空日期范围对话框
const openClearDateDialog = (collectionName: string) => {
  clearDateForm.collection_name = collectionName
  clearDateDialogVisible.value = true
}

// 确认清空日期范围
const confirmClearDateRange = async () => {
  if (!clearDateForm.start_date || !clearDateForm.end_date) {
    ElMessage.warning('请输入完整的起始和结束日期')
    return
  }

  try {
    await ElMessageBox.confirm(
      `⚠️ 确定要删除集合 **${clearDateForm.collection_name}** 中日期范围 ${clearDateForm.start_date} ~ ${clearDateForm.end_date} 的所有数据吗？\n此操作不可恢复！`,
      '二次确认',
      {
        confirmButtonText: '确定删除',
        cancelButtonText: '取消',
        type: 'warning',
        dangerouslyUseHTMLString: true,
      }
    )

    operating.value = true
    const result = await api.post('/admin/db/clear-date-range', {
      collection_name: clearDateForm.collection_name,
      start_date: parseInt(clearDateForm.start_date),
      end_date: parseInt(clearDateForm.end_date),
      confirm: true,
    })

    if (result.success) {
      ElMessage.success('日期范围数据删除成功')
      operationResult.value = result.data
      showResult.value = true
      clearDateDialogVisible.value = false
      fetchStats() // 刷新统计
    } else {
      ElMessage.error(result.message || '删除失败')
    }
  } catch (error) {
    if (error !== 'cancel') {
      console.error('删除日期范围失败:', error)
      ElMessage.error('删除失败: ' + (error as Error).message)
    }
  } finally {
    operating.value = false
  }
}

// 打开去重对话框
const openDeduplicateDialog = (collectionName: string) => {
  deduplicateForm.collection_name = collectionName
  deduplicateForm.dry_run = true
  deduplicateDialogVisible.value = true
}

// 确认去重
const confirmDeduplicate = async () => {
  if (!deduplicateForm.collection_name) {
    ElMessage.warning('集合名称不能为空')
    return
  }

  operating.value = true
  try {
    const result = await api.post('/admin/db/deduplicate', {
      collection_name: deduplicateForm.collection_name,
      dry_run: deduplicateForm.dry_run,
    })

    if (result.success) {
      if (deduplicateForm.dry_run) {
        ElMessage.info('预览完成，请查看结果，确认无误后关闭干运行执行实际删除')
      } else {
        ElMessage.success('去重完成')
        fetchStats() // 刷新统计
      }
      operationResult.value = result.data
      showResult.value = true
    } else {
      ElMessage.error(result.message || '去重失败')
    }
  } catch (error) {
    console.error('去重失败:', error)
    ElMessage.error('去重失败: ' + (error as Error).message)
  } finally {
    operating.value = false
  }
}

// 检查缺失数据
const handleCheckMissing = async () => {
  operating.value = true
  try {
    const result = await api.post('/admin/db/check-missing', {})

    if (result.success) {
      ElMessage.success('检查完成')
      operationResult.value = result.data
      showResult.value = true
    } else {
      ElMessage.error(result.message || '检查失败')
    }
  } catch (error) {
    console.error('检查缺失数据失败:', error)
    ElMessage.error('检查失败: ' + (error as Error).message)
  } finally {
    operating.value = false
  }
}

// 验证数据完整性
const handleVerifyIntegrity = async () => {
  operating.value = true
  try {
    const result = await api.post('/admin/db/verify-integrity', {})

    if (result.success) {
      ElMessage.success('验证完成')
      operationResult.value = result.data
      showResult.value = true
    } else {
      ElMessage.error(result.message || '验证失败')
    }
  } catch (error) {
    console.error('验证完整性失败:', error)
    ElMessage.error('验证失败: ' + (error as Error).message)
  } finally {
    operating.value = false
  }
}

// 格式化字节大小
const formatBytes = (bytes: number): string => {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i]
}

// 集合列表
const collections = computed(() => {
  if (!dbStats.value || !dbStats.value.collections) return []
  return dbStats.value.collections.filter((c: any) =>
    ALLOWED_COLLECTIONS.includes(c.name)
  )
})

// 页面加载
onMounted(() => {
  fetchStats()
})
</script>

<template>
  <div class="db-admin-page">
    <div class="page-header">
      <h1 class="page-title">🗄️ MongoDB 数据库管理</h1>
      <p class="page-description">数据库统计查看、数据清理、完整性校验</p>
    </div>

    <!-- 总体统计信息 -->
    <ElCard class="stats-card" header="总体统计信息">
      <div class="stats-grid">
        <div class="stats-item">
          <div class="stats-label">MongoDB 版本</div>
          <div class="stats-value">{{ dbStats?.mongodb_version || '-' }}</div>
        </div>
        <div class="stats-item">
          <div class="stats-label">数据库名称</div>
          <div class="stats-value">{{ dbStats?.db_name || '-' }}</div>
        </div>
        <div class="stats-item">
          <div class="stats-label">总数据大小</div>
          <div class="stats-value"><ElTag type="primary">{{ dbStats ? formatBytes(dbStats.total_size_bytes) : '0 B' }}</ElTag></div>
        </div>
        <div class="stats-item">
          <div class="stats-label">总文档数</div>
          <div class="stats-value"><ElTag type="info">{{ dbStats?.total_documents || 0 }}</ElTag></div>
        </div>
      </div>

      <div class="mt-4">
        <ElButton type="primary" :loading="loading" @click="fetchStats">
          🔄 刷新统计
        </ElButton>
      </div>
    </ElCard>

    <ElDivider />

    <!-- 集合列表 -->
    <ElCard class="collections-card" header="集合详细统计">
      <ElTable
        :data="collections"
        v-loading="loading"
        border
        stripe
      >
        <ElTableColumn
          prop="name"
          label="集合名称"
          width="200"
          v-slot="{ row }"
        >
          <ElTag type="primary">{{ row.name }}</ElTag>
        </ElTableColumn>
        <ElTableColumn prop="document_count" label="文档数" width="120" />
        <ElTableColumn prop="avg_document_size" label="平均文档大小" width="140">
          <template #default="{ row }">
            {{ row.avg_document_size ? `${row.avg_document_size.toFixed(2)} B` : '0 B' }}
          </template>
        </ElTableColumn>
        <ElTableColumn prop="size_bytes" label="总大小" width="120">
          <template #default="{ row }">
            {{ formatBytes(row.size_bytes) }}
          </template>
        </ElTableColumn>
        <ElTableColumn label="操作" width="480" fixed="right">
          <template #default="{ row }">
            <el-button
              size="small"
              type="success"
              @click="handleCheckMissing"
              :disabled="operating"
            >
              🔍 检查缺失
            </el-button>
            <el-button
              size="small"
              type="warning"
              @click="openDeduplicateDialog(row.name)"
              :disabled="operating"
            >
              🧹 去重
            </el-button>
            <el-button
              size="small"
              type="primary"
              @click="openClearDateDialog(row.name)"
              :disabled="operating"
            >
              📅 按日期清空
            </el-button>
            <el-button
              size="small"
              type="danger"
              @click="handleClearCollection(row.name)"
              :disabled="operating"
            >
              🗑️ 清空全部
            </el-button>
          </template>
        </ElTableColumn>
      </ElTable>
    </ElCard>

    <ElDivider />

    <!-- 全局操作 -->
    <ElCard class="actions-card" header="全局操作">
      <div class="actions-grid">
        <div>
          <h4>🔍 检查缺失数据</h4>
          <p>检查哪些股票缺少哪些必需因子，帮助补全数据</p>
          <ElButton
            type="primary"
            @click="handleCheckMissing"
            :loading="operating"
          >
            开始检查
          </ElButton>
        </div>
        <div>
          <h4>✅ 验证数据完整性</h4>
          <p>验证所有数据的完整性，检查数据格式、必填字段</p>
          <ElButton
            type="primary"
            @click="handleVerifyIntegrity"
            :loading="operating"
          >
            开始验证
          </ElButton>
        </div>
      </div>
    </ElCard>

    <!-- 操作结果展示 -->
    <div v-if="showResult && operationResult" class="mt-4">
      <ElCard class="result-card" header="操作结果">
        <pre class="result-json">{{ JSON.stringify(operationResult, null, 2) }}</pre>
      </ElCard>
    </div>

    <!-- 清空日期范围对话框 -->
    <ElDialog
      v-model="clearDateDialogVisible"
      title="按日期范围删除数据"
      width="500px"
    >
      <ElForm label-width="100px">
        <ElFormItem label="集合名称">
          <ElInput v-model="clearDateForm.collection_name" disabled />
        </ElFormItem>
        <ElFormItem label="起始日期">
          <ElInput
            v-model="clearDateForm.start_date"
            placeholder="YYYYMMDD 格式，例如: 20260101"
          />
        </ElFormItem>
        <ElFormItem label="结束日期">
          <ElInput
            v-model="clearDateForm.end_date"
            placeholder="YYYYMMDD 格式，例如: 20260131"
          />
        </ElFormItem>
      </ElForm>
      <template #footer>
        <ElButton @click="clearDateDialogVisible = false">取消</ElButton>
        <ElButton
          type="danger"
          @click="confirmClearDateRange"
          :loading="operating"
        >
          确认删除
        </ElButton>
      </template>
    </ElDialog>

    <!-- 去重对话框 -->
    <ElDialog
      v-model="deduplicateDialogVisible"
      title="清理重复数据"
      width="500px"
    >
      <ElForm label-width="120px">
        <ElFormItem label="集合名称">
          <ElInput v-model="deduplicateForm.collection_name" disabled />
        </ElFormItem>
        <ElFormItem label="干运行（只预览不删除）">
          <ElSwitch
            v-model="deduplicateForm.dry_run"
            active-text="开启"
            inactive-text="关闭"
          />
        </ElFormItem>
        <ElAlert
          title="说明"
          type="info"
          description="重复数据按照 ts_code + trade_date 去重，保留第一条，删除后续重复记录。建议先开启干运行预览结果，确认无误后再执行实际删除。"
        />
      </ElForm>
      <template #footer>
        <ElButton @click="deduplicateDialogVisible = false">取消</ElButton>
        <ElButton
          type="primary"
          @click="confirmDeduplicate"
          :loading="operating"
        >
          开始去重
        </ElButton>
      </template>
    </ElDialog>
  </div>
</template>

<style scoped lang="scss">
.db-admin-page {
  padding: 20px;
  max-width: 1400px;
  margin: 0 auto;
}

.page-header {
  margin-bottom: 20px;

  .page-title {
    font-size: 26px;
    font-weight: 700;
    color: #303133;
    margin: 0 0 8px 0;
  }

  .page-description {
    color: #606266;
    margin: 0;
  }
}

.stats-card {
  margin-bottom: 20px;
}

.mt-4 {
  margin-top: 16px;
}

.mb-4 {
  margin-bottom: 16px;
}

.actions-card {
  margin-bottom: 20px;
}

.actions-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 20px;

  > div {
    h4 {
      margin: 0 0 8px 0;
      font-size: 16px;
      color: #303133;
    }

    p {
      margin: 0 0 16px 0;
      color: #606266;
      font-size: 14px;
    }
  }
}

.result-card {
  margin-bottom: 20px;

  .result-json {
    background: #f5f7fa;
    padding: 16px;
    border-radius: 4px;
    font-family: 'Courier New', monospace;
    font-size: 13px;
    line-height: 1.5;
    overflow-x: auto;
    margin: 0;
  }
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;

  .stats-item {
    .stats-label {
      font-size: 13px;
      color: #909399;
      margin-bottom: 4px;
    }
    .stats-value {
      font-size: 16px;
      font-weight: 600;
      color: #303133;
    }
  }
}
</style>
