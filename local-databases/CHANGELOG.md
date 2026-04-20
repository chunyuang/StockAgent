# 项目6 操作日志 - 本地数据库管理

记录所有对数据库结构/数据的修改操作，方便追溯变更。

---

## 格式

每条日志格式：
```
- YYYY-MM-DD HH:MM GMT+8 | 操作人 | 操作类型 | 操作对象 | 说明
```

---

## 日志

- **2026-03-22 01:46 GMT+8** | @ou_2344df66cfbc48add043acab9784520 | 新增 | raw/20251217-20260317-akshare | 近一年 A股日线数据 AKShare 获取


- **2026-03-22 01:22 GMT+8** | @ou_2344df66cfbc48add043acab9784520 | 备份 | factors/20251215-20260318-akshare--21pricefactors | 备份 MongoDB strategy_signals → /root/.openclaw/workspace/local-databases/factors/data/20251215-20260318-akshare--21pricefactors/20251215-20260318-akshare--21pricefactors-20260322-012246.tar.gz


- **2026-03-22 01:22 GMT+8** | @ou_2344df66cfbc48add043acab9784520 | 备份 | raw/20251215-20260318-akshare | 备份 MongoDB stock_daily → /root/.openclaw/workspace/local-databases/raw/data/20251215-20260318-akshare/20251215-20260318-akshare-20260322-012242.tar.gz


- **2026-03-22 01:16 GMT+8** | @ou_2344df66cfbc48add043acab9784520 | 新增 | backtests/20251215-20260318-akshare--21pricefactors--top50-monthly | 增加版本号，完整依赖记录


- **2026-03-22 01:16 GMT+8** | @ou_2344df66cfbc48add043acab9784520 | 新增 | factors/20251215-20260318-akshare--21pricefactors | 增加版本号，完整依赖记录


- **2026-03-22 01:16 GMT+8** | @ou_2344df66cfbc48add043acab9784520 | 新增 | raw/20251215-20260318-akshare | 增加版本号，更新时间


- **2026-03-22 01:16 GMT+8** | @ou_2344df66cfbc48add043acab9784520 | 更新 | backtests/20251215-20260318-akshare--21pricefactors--top50-monthly | 增加版本号，完整依赖记录


- **2026-03-22 01:16 GMT+8** | @ou_2344df66cfbc48add043acab9784520 | 更新 | factors/20251215-20260318-akshare--21pricefactors | 增加版本号，完整依赖记录


- **2026-03-22 01:16 GMT+8** | @ou_2344df66cfbc48add043acab9784520 | 更新 | raw/20251215-20260318-akshare | 增加版本号，更新时间


- **2026-03-22 00:48 GMT+8 | @ou_2344df66cfbc48add043acab9784520 | 创建项目 | local-databases | 实现分级存储原始/因子/回测，增加一致性校验，增加自动增量更新，增加dashboard索引**
- **2026-03-22 00:48 GMT+8 | @ou_2344df66cfbc48add043acab9784520 | 新增数据源 | 20251215-20260318-akshare | 原始数据，AKShare 获取，三个月 5491 股票 60 交易日**
- **2026-03-22 00:48 GMT+8 | @ou_2344df66cfbc48add043acab9784520 | 新增因子计算 | 20251215-20260318-akshare--21pricefactors | 基于原始数据，计算 21 个价量因子**
- **2026-03-22 00:48 GMT+8 | @ou_2344df66cfbc48add043acab9784520 | 新增回测 | 20251215-20260318-akshare--21pricefactors--top50-monthly | 月度调仓，top 50 选股，IR > 0 因子等权**
- **2026-03-22 00:48 GMT+8 | @ou_2344df66cfbc48add043acab9784520 | 新增工具 | check-db.py | 一致性校验工具**
- **2026-03-22 00:48 GMT+8 | @ou_2344df66cfbc48add043acab9784520 | 新增工具 | incremental-update.py | 自动增量更新每日数据工具**
