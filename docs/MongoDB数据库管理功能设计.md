# MongoDB 数据库管理功能设计

## 📋 功能需求

| # | 功能 | 需求描述 | 状态 |
|---|------|----------|------|
| 1 | 数据统计展示 | 显示数据库基本信息（版本、集合大小、文档总数、磁盘占用） | ✅ 设计完成 |
| 2 | 股票统计 | 显示总股票数、交易日范围、最后更新时间 | ✅ 设计完成 |
| 3 | 因子覆盖统计 | 显示哪些因子已经计算、哪些还没有 | ✅ 设计完成 |
| 4 | 一键清空集合 | 清空 `stock_daily_ak_full` 集合 | ✅ 设计完成 |
| 5 | 清空时间范围 | 删除指定时间范围的数据 | ✅ 设计完成 |
| 6 | 清理重复数据 | 删除重复文档（按 ts_code + trade_date 去重） | ✅ 设计完成 |
| 7 | 检查缺失数据 | 检查哪些股票缺少哪些因子 | ✅ 设计完成 |
| 8 | 校验数据完整性 | 完整的数据完整性校验 | ✅ 设计完成 |

---

## 🏗️ 架构设计

### 1. API 端点设计

遵循现有项目 API 风格，添加到 `backtest_router`：

| 端点 | 方法 | 功能 |
|------|------|------|
| `GET /api/v1/admin/db/stats` | GET | 获取数据库整体统计信息 |
| `POST /api/v1/admin/db/clear-collection/{collection_name}` | POST | 清空指定集合 |
| `POST /api/v1/admin/db/clear-date-range` | POST | 删除指定时间范围数据 |
| `POST /api/v1/admin/db/deduplicate` | POST | 清理重复数据 |
| `POST /api/v1/admin/db/check-missing` | POST | 检查缺失数据 |
| `POST /api/v1/admin/db/verify-integrity` | POST | 验证数据完整性 |

### 2. 响应格式统一

```json
{
  "success": true,
  "data": {
    // 具体数据
  },
  "message": "操作成功描述"
}
```

错误响应：
```json
{
  "success": false,
  "data": null,
  "message": "错误描述"
}
```

---

## 📊 功能详细设计

### 1. 获取数据库整体统计信息 `GET /api/v1/admin/db/stats`

**返回数据结构：**

```python
{
  "mongodb_version": string,           // MongoDB 版本号
  "collections": [                   // 每个集合的统计信息
    {
      "name": string,                // 集合名称
      "document_count": int,        // 文档总数
      "size_bytes": int,            // 占用磁盘字节数
      "size_human": string,         // 人性化显示（如 "2.3 GB"）
      "avg_document_size": int     // 平均文档大小
    }
  ],
  "stock_daily_ak_full": {            // 特别关注的集合
    "document_count": int,
    "size_bytes": int,
    "size_human": string,
    "date_range": {
      "min_date": int,             // 最早交易日
      "max_date": int,             // 最晚交易日
      "total_trading_days": int    // 交易日总数
    },
    "stock_count": int,             // 不重复股票数量
    "last_update": string          // 最后更新时间 (ISO)
  },
  "factors": {                      // 因子统计
    "total_factors": int,           // 总因子数
    "covered_factors": int,         // 至少有一个文档包含的因子数
    "missing_factors": list[string], // 完全缺失的因子列表
    "coverage": {                   // 每个因子覆盖统计
      "factor_name": {
        "total_docs": int,          // 总文档数
        "non_null_docs": int,       // 非空文档数
        "coverage_pct": float       // 覆盖百分比
      }
    }
  }
}
```

**实现要点：**
- 使用 `db.command("collstats", collection)` 获取集合统计信息
- 使用聚合查询获取日期范围和不重复股票数
- 抽样检查因子覆盖情况，不需要全表扫描（性能考虑）

---

### 2. 一键清空集合 `POST /api/v1/admin/db/clear-collection/{collection_name}`

**请求参数：**
- 路径参数：`collection_name` - 集合名称
- 查询参数：`confirm=true` - 必须确认才能执行

**响应：**
```json
{
  "success": true,
  "data": {
    "collection_name": "stock_daily_ak_full",
    "documents_before": 267930,
    "documents_after": 0,
    "time_seconds": 0.23
  },
  "message": "集合 stock_daily_ak_full 已成功清空"
}
```

**安全考虑：**
- 只允许清空特定集合 (`stock_daily_ak_full`, `daily_basic`)，不允许清空系统集合
- 必须传入 `confirm=true` 才执行，防止误操作
- 操作记录到日志

---

### 3. 清空指定时间范围 `POST /api/v1/admin/db/clear-date-range`

**请求参数：**
```json
{
  "collection_name": "stock_daily_ak_full",
  "start_date": 20260101,
  "end_date": 20260131,
  "confirm": true
}
```

**响应：**
```json
{
  "success": true,
  "data": {
    "deleted_count": 1234,
    "start_date": 20260101,
    "end_date": 20260131
  },
  "message": "成功删除 1234 篇文档"
}
```

---

### 4. 清理重复数据 `POST /api/v1/admin/db/deduplicate`

**请求参数：**
```json
{
  "collection_name": "stock_daily_ak_full",
  "dry_run": true  // true = 只统计不删除，false = 实际删除
}
```

**算法：**
1. 按 `ts_code` + `trade_date` 分组，找出分组大小 > 1 的重复文档
2. 对于每个重复分组，保留第一个文档，删除其余重复文档
3. 返回统计结果

**响应：**
```json
{
  "success": true,
  "data": {
    "total_groups": int,
    "duplicate_groups": int,
    "total_duplicates": int,
    "will_delete": int,
    "actually_deleted": int,
    "dry_run": bool
  },
  "message": "找到 X 组重复文档，共 Y 条重复记录，已删除 Z 条"
}
```

**性能考虑：**
- 使用聚合框架 `$group` 找出重复，不需要在应用层遍历全表
- 批量删除，减少网络往返

---

### 5. 检查缺失数据 `POST /api/v1/admin/db/check-missing`

**请求参数：**
```json
{
  "date": "20260105",  // 可选，指定检查某个日期，不指定检查最新日期
  "factors": []       // 可选，指定检查哪些因子，不指定检查所有预计算因子
}
```

**响应：**
```json
{
  "success": true,
  "data": {
    "date": int,
    "total_stocks": int,
    "results": {
      "factor_name": {
        "total_stocks": int,
        "missing_stocks": int,
        "missing_list": list[string],  // 前 100 个缺失股票
        "missing_pct": float
      }
    },
    "date_has_all_factors": bool,   // 当前日期是否所有因子都完整
    "all_factors_complete": bool   // 所有检查日期是否都完整
  },
  "message": "检查完成，X 个因子有缺失数据"
}
```

---

### 6. 验证数据完整性 `POST /api/v1/admin/db/verify-integrity`

**检查内容：**
1. 检查交易日历中的每个交易日，是否都有数据
2. 检查每个交易日文档数是否正常（应该接近 5000 只）
3. 检查每个文档是否包含所有必填字段
4. 统计总的缺失情况

**请求参数：**
```json
{
  "start_date": "20260101",
  "end_date": "20260320",
  "sample_size": 100  // 抽样检查，不需要全表扫描
}
```

**响应：**
```json
{
  "success": true,
  "data": {
    "date_range": {
      "start": int,
      "end": int,
      "total_days": int,
      "trading_days": int
    },
    "trading_days_check": [
      {
        "date": int,
        "expected_count": int,
        "actual_count": int,
        "complete": bool,
        "missing_pct": float
      }
    ],
    "field_check": {
      "total_docs_checked": int,
      "total_fields_expected": int,
      "total_fields_missing": int,
      "missing_by_field": {
        "field_name": int  // 缺失次数
      }
    },
    "overall": {
      "complete_days": int,
      "incomplete_days": int,
      "completion_pct": float,
      "is_healthy": bool  // 整体是否健康
    }
  },
  "message": "完整性校验完成，整体健康度 XX%"
}
```

---

## 🎨 前端界面设计

### 页面布局

```
┌─────────────────────────────────────────────────────────┐
│  📊 数据库概览                                            │
│  MongoDB版本: 6.0.1                                       │
│  总磁盘占用: 2.3 GB                                       │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ 集合              │ 文档数      │ 大小      │ 最后更新 │   │
│  ├─────────────────────────────────────────────────────┤   │
│  │ stock_daily_ak_full │ 267,930    │ 1.2 GB   │ 今天   │   │
│  │ stock_basic       │ 5,492      │ 0.5 MB   │ -      │   │
│  │ trade_cal         │ 730        │ 0.1 MB   │ -      │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│  🧬 因子覆盖统计                                          │
│                                                             │
│  ┌───────────────────────────┬──────────────┬────────────┐  │
│  │ 因子名称             │ 覆盖百分比 │ 状态       │  │
│  ├───────────────────────────┼──────────────┼────────────┤  │
│  │ limit_up_amount       │ 100%      │ ✅ 完整   │  │
│  │ circ_mv             │ 100%      │ ✅ 完整   │  │
│  │ ...                │ ...       │ ...      │  │
│  └───────────────────────────┴──────────────┴────────────┘  │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│  ⚙️  操作工具                                              │
│                                                             │
│  [🔄 清空整个集合]  [🗑️  清空时间范围]  [🧹 清理重复]  │
│                                                             │
│  🔍 检查缺失数据  [✅ 校验完整性]                            │
└─────────────────────────────────────────────────────────┘
```

### 交互设计

1. **概览数据** 页面加载自动获取，刷新可更新
2. **因子覆盖** 自动展开，绿色表示完整，黄色表示部分缺失，红色表示完全缺失
3. **操作按钮** 点击后弹出确认对话框（防止误操作）
4. **危险操作** (清空/删除) 需要二次确认输入 `CONFIRM` 才能执行
5. **操作结果** 以表格形式展示统计信息

---

## 🔐 安全考虑

| 安全措施 | 实现 |
|----------|------|
| 只允许操作指定集合 | 不允许删除系统集合、用户集合 |
| 危险操作需要确认 | 必须输入 `CONFIRM` 确认才能执行清空/删除 |
| 支持干运行 | 去重功能支持 `dry_run` 先看结果再删除 |
| 所有操作记日志 | 记录操作人、操作时间、操作内容 |
| 不允许DROP集合 | 只清空文档，不删除集合 |

---

## 📝 代码实现位置

| 文件 | 功能 |
|------|------|
| `AgentServer/nodes/web/api/admin_db.py` | API 端点实现 |
| `AgentServer/nodes/web/api/__init__.py` | 注册路由 |
| `docs/MongoDB数据库管理功能设计.md` | 本设计文档 |

---

## 📋 实现TODO

- [x] 完成设计文档
- [x] 实现 API 端点
- [x] Python 语法检查通过
- [ ] 测试各功能
- [x] 提交代码
