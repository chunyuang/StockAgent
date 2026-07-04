# 多数据源写入单位统一规范

> **根因**: 不同数据源(API)返回的字段单位不同，写入MongoDB时如果不做转换，
> 就会导致同一集合中同一字段存在多种单位，回测/筛选/风控全部失效。
> 
> **已发生3次严重事故**: 换手率×100、circ_mv亿元/百万元/万元混存、vol手/股混存。

---

## 一、MongoDB集合字段单位标准（不可更改）

### stock_daily_ak_full

| 字段 | 标准单位 | 合理范围 | 参照值 |
|------|---------|---------|--------|
| close/open/high/low/pre_close | **元** | 0.01-99999 | 茅台≈1500元 |
| pct_chg | **百分数** | -30~+30 | 10.0 (表示10%) |
| vol | **手** | 1-1e8 | 891848手 |
| amount | **百元** | 1-1e10 | 891848百元 |
| turnover_rate | **百分数** | 0.01-100 | 5.31 (表示5.31%) |
| volume_ratio | **倍数** | 0-50 | 1.52 |
| circ_mv | **万元** | 100-1e8 | 茅台≈1.5e7万元 |
| total_mv | **万元** | 100-1e8 | — |

### daily_basic

| 字段 | 标准单位 | 合理范围 | 参照值 |
|------|---------|---------|--------|
| turnover_rate | **百分数** | 0.01-100 | 5.31 |
| volume_ratio | **倍数** | 0-50 | 1.52 |
| pe_ttm | **倍数** | -1000~1000 | 25.3 |
| pb | **倍数** | 0-100 | 3.2 |
| circ_mv | **亿元** | 0.01-1e4 | 茅台≈1500亿 |
| total_mv | **亿元** | 0.01-1e4 | — |
| close | **元** | 0.01-99999 | 25.38 |

> ⚠️ **关键差异**: circ_mv/total_mv 在 stock_daily_ak_full=万元，在 daily_basic=亿元，差10000倍！

---

## 二、数据源API返回单位 → MongoDB转换表

### stock_daily_ak_full 写入

| 数据源 | vol | amount | turnover_rate | circ_mv | 备注 |
|--------|-----|--------|---------------|---------|------|
| 东方财富push2 | 手(直接存) | 元(÷100→百元) | 百分数(直接存) | 元(÷10000→万元) | ✅主力 |
| 搜狐hisHq | 手(直接存) | 万元(×100→百元) | 小数(×100→百分数) | 无 | ✅fallback |
| AKShare | 股(÷100→手) | 元(÷100→百元) | 百分数(直接存) | **亿元(×10000→万元)** | ⚠️circ_mv易错 |
| Tushare daily | 手(×100→股❌) | 千元(×1000→元❌) | — | — | ❌vol/amount单位错 |
| 腾讯QQ | 手(×100→股❌) | 万元(×10000→元❌) | 百分数(直接存) | 无 | ❌vol/amount单位错 |

### daily_basic 写入

| 数据源 | turnover_rate | volume_ratio | circ_mv | 备注 |
|--------|---------------|-------------|---------|------|
| 东方财富push2 | 百分数(直接存) | 倍数(直接存) | 元(÷1e8→亿元) | ✅主力 |
| 东方财富datacenter | — | — | 元(÷1e8→亿元) | ✅周末可用 |
| Tushare daily_basic | 小数(×100→百分数) | 倍数(直接存) | **万元(÷10000→亿元)** | ✅已修 |
| lightweight_factor_fill | — | — | **亿元(×10000→万元)** | ✅同步到ak_full时转换 |

---

## 三、已发现并修复的bug清单

| # | 日期 | bug | 影响范围 | 根因 | 修复 |
|---|------|-----|---------|------|------|
| 1 | 6/23-6/29 | turnover_rate被×100 | 23954+14937条 | 搜狐写入时多×100 | ÷100恢复 |
| 2 | 6/24-6/29 | first_limit_up全0 | 350条 | daily_factor_precompute逻辑 | is_limit_up=1→first_limit_up=1 |
| 3 | 6/24-6/25 | circ_mv=亿元(差12500倍) | ~5000条/天 | AKShare写入未×10000 | 用6/30正确数据覆盖 |
| 4 | 6/26-6/29 | circ_mv=百万元(差100倍) | ~3100条/天 | 不明数据源 | ×100修复 |
| 5 | 7/1-7/2 | circ_mv=亿元(差10000倍) | ~5500条/天 | AKShare写入未×10000 | ×10000修复 |
| 6 | — | tushare_fill_v2写入daily_basic时circ_mv未÷10000 | 每次Tushare补采 | Tushare返回万元,daily_basic标准亿元 | ÷10000 |
| 7 | — | lightweight_factor_fill同步circ_mv未×10000 | 每次同步 | daily_basic=亿元,ak_full=万元 | ×10000 |

### 已全部修复 ✅ (2026-07-04)

| # | 脚本 | 原问题 | 修复 |
|---|------|------|------|
| P1 | tushare_fill_daily.py | vol: 手×100→股, amount: 千元×1000→元 | vol直接存(手), amount×10→百元 |
| P2 | tushare_fill_2years_v2.py | 同P1 | 同上 |
| P3 | tencent_daily_bar.py | vol: 手×100→股, amount: 万元×10000→元 | vol直接存(手), amount×100→百元 |
| P4 | fill_old_segment_em.py | vol: 手×100→股, amount: 元 | vol直接存(手), amount÷100→百元 |
| P5 | fill_missing_daily_ak.py | vol: 股(未÷100), amount: 元(未÷100) | vol÷100→手, amount÷100→百元 |
| P6 | tushare_fill_basic.py | circ_mv未÷10000(写入daily_basic) | circ_mv÷10000→亿元 |
| P7 | tushare_fill_2years_v2.py | daily_basic部分circ_mv未÷10000 | circ_mv/total_mv÷10000→亿元 |

---

## 四、写入校验规则（所有脚本必须遵守）

```python
def validate_stock_daily_ak_full(doc):
    """写入stock_daily_ak_full前的校验"""
    errors = []
    
    # close: 元, 茅台≈1500, *ST股≈1
    close = doc.get('close', 0)
    if close and (close < 0.1 or close > 100000):
        errors.append(f"close={close} 异常(0.1-100000元)")
    
    # vol: 手, 1手=100股
    vol = doc.get('vol', 0)
    if vol and vol < 1:
        errors.append(f"vol={vol} 异常(手, 最小1)")
    
    # amount: 百元
    amount = doc.get('amount', 0)
    if amount and amount < 1:
        errors.append(f"amount={amount} 异常(百元, 最小1)")
    
    # turnover_rate: 百分数
    tr = doc.get('turnover_rate', 0)
    if tr and tr > 100:
        errors.append(f"turnover_rate={tr}% >100! 可能被×100")
    if tr and tr < 0.001:
        errors.append(f"turnover_rate={tr}% <0.001! 可能是小数未×100")
    
    # circ_mv: 万元
    cm = doc.get('circ_mv', 0)
    if cm and cm < 100:
        errors.append(f"circ_mv={cm}万元 <100万! 可能是亿元或百万元")
    if cm and cm > 1e9:
        errors.append(f"circ_mv={cm}万元 >1万亿! 可能是元未÷10000")
    
    return errors

def validate_daily_basic(doc):
    """写入daily_basic前的校验"""
    errors = []
    
    tr = doc.get('turnover_rate', 0)
    if tr and tr > 100:
        errors.append(f"turnover_rate={tr}% >100!")
    
    # circ_mv: 亿元
    cm = doc.get('circ_mv', 0)
    if cm and cm < 0.001:
        errors.append(f"circ_mv={cm}亿元 <0.001亿! 可能是万元未÷10000")
    if cm and cm > 1e5:
        errors.append(f"circ_mv={cm}亿元 >10万亿! 可能是万元或元")
    
    return errors
```

---

## 五、验证脚本 (scripts/validate_data_units.py)

每次数据写入后必须跑验证，cron每日自动执行。

---

## 六、操作规范

1. **新增数据源前**：必须在此文档中登记API返回单位→MongoDB转换规则
2. **写入前校验**：调用validate_stock_daily_ak_full/validate_daily_basic
3. **写入后验证**：跑validate_data_units.py --date YYYYMMDD
4. **cron自动审查**：每日盘后自动跑验证，发现异常立即告警
5. **修改此文档**：任何单位相关改动必须同步更新此文档
