# 已废弃模块

这些文件不再被任何活动代码导入，属于死代码。

| 文件 | 行数 | 原用途 | 替代方案 |
|------|------|--------|----------|
| `factors.py` | 324 | 因子数据系统 | `factor_library.py` + `factor_engine.py` |
| `incremental_backtest.py` | 153 | 增量回测 | 无（功能未实现） |
| `walk_forward.py` | 219 | 滚动前进回测 | 无（功能未实现） |
| `performance.py` | 427 | 绩效分析器 | `portfolio_backtest._calculate_performance()` |

如需恢复，请从 git history 获取。
