# 数据源管理规范

> ⚠️ **核心原则：不经用户同意，不引入新数据源。不重复尝试已知失败的数据源。**

## 一、当前可用数据源（2026-05-10 更新）

### 历史日线数据 ✅ 可用

| 数据源 | 用途 | 状态 | 限制 |
|--------|------|------|------|
| **AKShare** `akshare_daily_manager` | 日线行情批量下载 | ✅ 主力 | 按日期批量下载，无频率限制 |
| **AKShare** `stock_zh_a_spot_em` | 全市场实时快照(流通市值) | ✅ 可用 | 单次调用，用于circ_mv修复 |
| MongoDB `stock_daily_ak_full` | 日线行情读取(回测源) | ✅ 可用 | 本地数据库，无限制 |
| MongoDB `daily_basic` | PE/PB/换手率/市值(精确值) | ✅ 可用 | 本地数据库，无限制 |

### 实时/盘中数据 ⚠️ 受限

| 数据源 | 用途 | 状态 | 限制 |
|--------|------|------|------|
| **量脉** `LiangMaiClient` | 实时行情/1分钟K线/涨停池 | ⚠️ IP受限 | 120次/分钟 + Token绑定2个IP |
| `SimulatedGateway` | 模拟交易行情 | ⚠️ 从MongoDB读 | 回测用，非真实实时数据 |

### 已失效数据源 ❌ 不可用

| 数据源 | 失效原因 |
|--------|----------|
| **Tushare** 官方token `d9f3d9c...` | 积分不足/接口封禁 |
| **Tushare** 代理token `2f031a2...` | 已过期 |
| **AKShare** `stock_zh_a_hist_min_em` | 仅返回近期1分钟K线，无法获取2个月前历史 |
| **BaoStock** | 优先级最低，数据质量差，仅作最后降级 |

## 二、数据获取规则

### 规则1：明确区分历史数据 vs 实时数据

```
历史数据（回测用）:
  └─ MongoDB stock_daily_ak_full (主力，本地读取，无限制)
  └─ MongoDB daily_basic (精确PE/PB/circ_mv)
  └─ AKShare akshare_daily_manager (下载→写入MongoDB，仅在数据缺失时调用)

实时数据（交易用）:
  └─ 量脉 LiangMaiClient (实时行情、1分钟K线)
     ⚠️ 限流: 120次/分钟，Token绑定2个IP
     ⚠️ IP被占时不要反复重试！等用户确认IP释放后再用
```

### 规则2：不重复尝试已知失败的数据源

- Tushare token已失效 → **不要调用**
- 量脉IP被占(4291错误) → **不要反复重试**，等用户确认
- AKShare被RemoteDisconnected → **不要反复重试**

### 规则3：不自行引入新数据源

新增任何数据获取方式（新API、新Python库、新数据文件）前，**必须先跟用户沟通**。

### 规则4：因子计算数据源

```
factor_auto_compute (回测因子自动计算):
  输入: MongoDB stock_daily_ak_full + daily_basic
  输出: 写回 stock_daily_ak_full
  
  ⚠️ 不要用其他数据源重算已有因子！
  ⚠️ 如需新因子，先用现有数据计算，不够再跟用户确认
```

## 三、数据源优先级（DataSourceManager）

当前priority（数字越大越优先）：

| 优先级 | 适配器 | 说明 |
|--------|--------|------|
| 100 | TushareAdapter | ❌ token失效，实际不可用 |
| 50 | AKShareAdapter | ✅ 历史数据可用 |
| 5 | LiangMaiAdapter | ⚠️ IP受限时不可用 |
| 10 | BaoStockAdapter | 最后降级 |

**建议调整**：Tushare失效后应降为最低优先级，AKShare提升为默认主力。

## 四、脚本/工具的数据源使用

| 脚本 | 数据源 | 用途 |
|------|--------|------|
| `scripts/sync_stock_daily_akshare.py` | AKShare → MongoDB | 日线同步 |
| `scripts/sync_daily_basic.py` | AKShare → MongoDB | PE/PB同步 |
| `scripts/sync_limit_list.py` | AKShare → MongoDB | 涨跌停同步 |
| `scripts/compute_intraday_from_daily.py` | MongoDB → MongoDB | 日线推算盘中因子 |
| `scripts/compute_intraday_1min.py` | 量脉 → MongoDB | 1分钟K线(⚠️IP受限) |
| `scripts/fix_turnover_rate.py` | AKShare spot → MongoDB | 换手率修复 |

## 五、变更日志

- 2026-05-06: 初始版本，梳理全部数据源现状
