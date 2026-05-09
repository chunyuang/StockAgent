# 量脉API实测结果 [2026-05-07]

> 基于实际API调用验证，非文档推测

## ✅ 已验证接口

### quote_bars_history（历史K线）
- **请求**: `ts_code=000001, klt=d, fqt=n, beg=20260428, end=20260430, lt=5`
- **返回字段**: `t, o, h, l, c, v, a, pc, sf`
- **关键发现**: ❌ **没有**换手率(hs)、流通市值(lt)、PE/PB
- **只有**: OHLCV + 前收盘价(pc) + 停牌标记(sf)
- **v单位**: 手(×100=股), **a单位**: 元
- **价值**: 可替代通达信补pre_close，但不能解决circ_mv/turnover_rate缺失

### pool_limit_up（涨停池）
- **请求**: `trade_date=2026-04-01`
- **返回字段**: `dm, mc, zf, p, cje, lt, zsz, hs, zj, fbt, lbt, zbc, tj, lbc, hy`
- **✅ 有**: lt(流通市值,元), zsz(总市值,元), hs(换手率%)
- **额外**: 封板时间(fbt/lbt), 炸板次数(zbc), 封板资金(zj), 连板数(lbc), 行业(hy)
- **支持历史**: ✅ 逐日查询
- **限制**: 仅覆盖当日涨停股(约30-80只/天)

### stock_realtime（单只实时行情）
- **请求**: `ts_code=000001`
- **返回字段**: `t, p, pc, ud, v, cje, zf, hs, pe, lb, fm, h, l, o, yc, sz, lt, zs, sjl, zdf60`
- **✅ 全字段**: pe, sjl(PB), lt(流通市值), sz(总市值), hs(换手率), lb(量比)
- **返回格式**: dict(非list), 21个字段
- **仅实时**: ❌ 无历史

## 之前已验证的接口(2026-05-06)

### market_realtime_all_broker（全市场券商源）
- 8479只(SH+SZ)，有pe/pb_ratio，**无**lt/sz/hs/lb
- 限1次/分

### market_realtime_all_network（全市场网络源）
- 仅300只SH，有pe/sjl(PB)/lt/sz/hs/lb
- 限1次/分

## 📋 缺失数据 × 接口映射

| 缺失数据 | 可用接口 | 历史回补 | 当日增量 |
|----------|---------|---------|---------|
| 涨停池历史 | `pool_limit_up` | ✅ | ✅ |
| 涨停股circ_mv | `pool_limit_up.lt` | ✅ | ✅ |
| 涨停股turnover_rate | `pool_limit_up.hs` | ✅ | ✅ |
| 全市场PE/PB | `all_broker` | ❌ | ✅(1次) |
| SZ circ_mv/total_mv | `stock_realtime` | ❌ | ✅(逐只) |
| SZ turnover_rate | `stock_realtime` | ❌ | ✅(逐只) |
| SZ volume_ratio | `stock_realtime` | ❌ | ✅(逐只) |
| 非涨停股历史circ_mv | **无** | ❌ | - |
| 非涨停股历史volume_ratio | **无** | ❌ | - |
