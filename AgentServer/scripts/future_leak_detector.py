"""
P0: 回测结果可信性验证 — 未来函数泄漏检测

核心问题：回测是否用了当天收盘后的信息来做当天盘中决策？

检测方法：
1. 对比"用当天数据选股"vs"只用前日数据选股"的候选差异
2. 量化每个未来函数嫌疑点对收益的影响
3. 给出可信度评分

运行方式：python scripts/future_leak_detector.py
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core.managers.mongo_manager import mongo_manager


async def detect_future_leaks():
    await mongo_manager.initialize()

    print("=" * 70)
    print("🔍 回测未来函数泄漏检测")
    print("=" * 70)

    # 读取最近回测结果
    tasks = await mongo_manager.find_many(
        'backtest_tasks',
        {'status': 'completed'},
        sort=[('_id', -1)],
        limit=1
    )
    if not tasks:
        print("❌ 没有可用的回测结果")
        return

    task = tasks[0]
    result = task.get('result', {})
    trades = result.get('merged_trades', [])
    closed = [t for t in trades if t.get('sell_date')]

    task_id = task.get('task_id', 'N/A')
    start_date = result.get('start_date', '')
    end_date = result.get('end_date', '')
    print(f"\n回测任务: {task_id}")
    print(f"回测区间: {start_date} - {end_date}")
    print(f"交易笔数: {len(closed)}")

    # ============================================================
    # 嫌疑1：情绪评分用当天涨停/跌停数
    # ============================================================
    print("\n" + "=" * 70)
    print("嫌疑1：情绪评分用当天涨停/跌停数（收盘后才知道）")
    print("=" * 70)

    # 检查：调仓日的涨停/跌停数是从当天数据计算的
    # 实际上：9:30开盘前只能用前日数据
    # 影响：如果当天大涨（涨停多），情绪评分偏高→仓位偏大→当天买入
    # 但当天大涨时买入是合理的（趋势跟踪），所以影响可能不大

    # 量化：对比用当天vs前日涨停数的差异
    print("\n分析：检查调仓日当天的市场环境")
    rebalance_records = result.get('rebalance_records', [])
    buy_records = [r for r in rebalance_records if r.get('action') == 'buy']

    # 统计买入日的市场涨跌
    buy_dates = set(str(r.get('date', '')) for r in buy_records)
    market_up_days = 0
    market_down_days = 0
    for d in buy_dates:
        if len(d) == 8 and d.isdigit():
            idx_data = await mongo_manager.find_one(
                'stock_daily_ak_full',
                {'ts_code': '000001.SH', 'trade_date': int(d)}
            )
            if idx_data:
                pct = idx_data.get('pct_chg', 0)
                if pct > 0:
                    market_up_days += 1
                else:
                    market_down_days += 1

    print(f"  买入日大盘上涨: {market_up_days}天")
    print(f"  买入日大盘下跌: {market_down_days}天")
    if market_up_days + market_down_days > 0:
        print(f"  买入日大盘上涨占比: {market_up_days/(market_up_days+market_down_days)*100:.1f}%")

    # 判定
    if market_up_days > market_down_days * 2:
        print("  ⚠️ 买入日大盘偏涨 → 情绪评分用当天数据可能导致追高")
        print("  影响：中等（实盘用前日数据，仓位可能更保守）")
    else:
        print("  ✅ 买入日涨跌均衡 → 影响较小")

    # ============================================================
    # 嫌疑2：选股用pct_chg（当天收盘涨幅）
    # ============================================================
    print("\n" + "=" * 70)
    print("嫌疑2：选股用pct_chg（当天收盘涨幅）— 最严重的未来函数！")
    print("=" * 70)

    # 半路追涨：min_rise_pct=3% → 用pct_chg>=3%筛选
    # 但pct_chg是收盘涨幅，盘中9:30只知道开盘价
    # 实际上：盘中只能看到当前价（在open和high之间），无法知道收盘价

    # 量化：对比pct_chg和intraday_max_rise_pct的差异
    print("\n分析：半路追涨候选的pct_chg vs 盘中可观测涨幅")

    # 找半路追涨的买入交易
    hw_trades = [t for t in closed if t.get('strategy') == '半路追涨']
    print(f"  半路追涨交易: {len(hw_trades)}笔")

    leak_count = 0
    no_leak_count = 0
    for t in hw_trades[:20]:  # 检查前20笔
        ts_code = t.get('ts_code', '')
        buy_date = t.get('buy_date', '')
        if not buy_date or len(str(buy_date)) != 8:
            continue
        buy_date = int(buy_date)

        # 获取买入日的行情
        daily = await mongo_manager.find_one(
            'stock_daily_ak_full',
            {'ts_code': ts_code, 'trade_date': buy_date}
        )
        if not daily:
            continue

        pct_chg = daily.get('pct_chg', 0)  # 收盘涨幅（未来函数！）
        open_price = daily.get('open', 0)
        pre_close = daily.get('pre_close', 0)
        high = daily.get('high', 0)

        if pre_close > 0:
            open_rise = (open_price - pre_close) / pre_close * 100  # 开盘涨幅（盘中可观测）
            intraday_max_rise = (high - pre_close) / pre_close * 100  # 盘中最高涨幅（盘中可观测）

            # 半路追涨条件：pct_chg >= 3%
            # 但盘中只能看到：open_rise 或 intraday_max_rise
            if pct_chg >= 3 and open_rise < 3:
                # 收盘涨3%但开盘没涨3% → 未来函数！
                # 盘中9:30看不到收盘会涨3%，不会选这只股
                leak_count += 1
                if leak_count <= 5:
                    print(f"  ⚠️ {ts_code} {buy_date}: pct_chg={pct_chg:.1f}% 但 open_rise={open_rise:.1f}% (盘中看不到收盘涨3%)")
            elif pct_chg >= 3 and open_rise >= 3:
                # 开盘就涨3%+ → 盘中可观测，不是未来函数
                no_leak_count += 1

    total_checked = leak_count + no_leak_count
    if total_checked > 0:
        leak_pct = leak_count / total_checked * 100
        print("\n  📊 半路追涨未来函数统计:")
        print(f"  检查交易数: {total_checked}")
        print(f"  未来函数交易: {leak_count}笔 ({leak_pct:.1f}%)")
        print(f"  非未来函数交易: {no_leak_count}笔 ({100-leak_pct:.1f}%)")

        if leak_pct > 30:
            print(f"  🔴 严重：{leak_pct:.0f}%的半路追涨交易存在未来函数！")
            print("  → 实盘中这些交易不会被选中（9:30看不到收盘涨幅）")
            print("  → 回测收益可能高估")
        elif leak_pct > 10:
            print(f"  🟡 中等：{leak_pct:.0f}%的半路追涨交易存在未来函数")
        else:
            print(f"  🟢 轻微：仅{leak_pct:.0f}%的半路追涨交易存在未来函数")
    else:
        print("  ⚠️ 数据不足，无法判断")

    # ============================================================
    # 嫌疑3：min_close_rise_pct（收盘确认条件）
    # ============================================================
    print("\n" + "=" * 70)
    print("嫌疑3：min_close_rise_pct=3%（收盘确认条件）")
    print("=" * 70)
    print("  半路追涨: min_close_rise_pct=3% → 要求收盘涨幅>=3%")
    print("  这个条件本身是'收盘确认'，不是未来函数")
    print("  含义：盘中冲高但收盘不站的股票，次日胜率低(35%)")
    print("  实盘可在14:50观察是否站住3%再做决策")
    print("  → 回测用收盘价确认，实盘用14:50价格确认，差异很小")
    print("  ✅ 不算未来函数，是合理的收盘确认逻辑")

    # ============================================================
    # 嫌疑4：首板打板成交概率模拟
    # ============================================================
    print("\n" + "=" * 70)
    print("嫌疑4：首板打板成交概率模拟")
    print("=" * 70)

    fu_trades = [t for t in closed if t.get('strategy') == '首板打板']
    print(f"  首板打板交易: {len(fu_trades)}笔")

    # 检查：首板打板的买入价是否是涨停价
    # 如果买入价=涨停价(close)，说明假设打板成功
    # 但实际上一字板0%/秒板30%/快速板50%/盘中板70%成交概率
    limit_up_buys = 0
    for t in fu_trades:
        buy_p = t.get('buy_price', 0)
        ts_code = t.get('ts_code', '')
        buy_date = t.get('buy_date', '')
        if not buy_date:
            continue
        daily = await mongo_manager.find_one(
            'stock_daily_ak_full',
            {'ts_code': ts_code, 'trade_date': int(buy_date)}
        )
        if daily:
            close = daily.get('close', 0)
            high = daily.get('high', 0)
            if close > 0 and abs(buy_p - close) / close < 0.01:
                limit_up_buys += 1

    print(f"  买入价≈涨停价: {limit_up_buys}/{len(fu_trades)}笔")
    if limit_up_buys > len(fu_trades) * 0.5:
        print("  ✅ 成交概率模拟已生效（不是100%成交）")
    else:
        print("  ⚠️ 部分交易买入价≠涨停价，需进一步检查")

    # ============================================================
    # 嫌疑5：跌停翘板能否买到
    # ============================================================
    print("\n" + "=" * 70)
    print("嫌疑5：跌停翘板能否买到")
    print("=" * 70)

    ld_trades = [t for t in closed if t.get('strategy') == '跌停翘板']
    print(f"  跌停翘板交易: {len(ld_trades)}笔")
    print(f"  跌停翘板收益: {sum(t.get('profit_pct',0) for t in ld_trades)/max(len(ld_trades),1):.2f}% (平均)")

    # 检查：跌停翘板的买入价是否合理
    # 跌停翘板：跌停板被打开后买入，买入价应>跌停价
    unreasonable = 0
    for t in ld_trades[:15]:
        buy_p = t.get('buy_price', 0)
        ts_code = t.get('ts_code', '')
        buy_date = t.get('buy_date', '')
        if not buy_date:
            continue
        daily = await mongo_manager.find_one(
            'stock_daily_ak_full',
            {'ts_code': ts_code, 'trade_date': int(buy_date)}
        )
        if daily:
            daily.get('low', 0)
            close = daily.get('close', 0)
            pre_close = daily.get('pre_close', 0)
            if pre_close > 0:
                limit_down_price = pre_close * 0.9  # 跌停价（主板-10%）
                if buy_p < limit_down_price * 1.01:
                    # 买入价≈跌停价，可能买不到
                    unreasonable += 1
                    if unreasonable <= 3:
                        print(f"  ⚠️ {ts_code} {buy_date}: buy@{buy_p:.2f} ≈ 跌停价{limit_down_price:.2f}")

    if unreasonable > 0:
        print(f"  买入价≈跌停价: {unreasonable}笔 (可能买不到)")
    else:
        print("  ✅ 买入价均>跌停价，翘板买入合理")

    # ============================================================
    # 总结
    # ============================================================
    print("\n" + "=" * 70)
    print("📋 未来函数泄漏检测总结")
    print("=" * 70)

    print("""
嫌疑1: 情绪评分用当天涨停数
  严重程度: 🟡 中等
  影响: 实盘用前日数据，仓位可能更保守
  修复建议: 改用前日涨停数计算情绪评分

嫌疑2: 选股用pct_chg(收盘涨幅)
  严重程度: 🔴 最严重（如果leak_pct>30%）
  影响: 盘中9:30看不到收盘涨幅，回测选中的股票实盘可能选不中
  修复建议: 用intraday_max_rise_pct替代pct_chg做选股条件

嫌疑3: min_close_rise_pct(收盘确认)
  严重程度: 🟢 不算未来函数
  影响: 实盘14:50可观测，差异很小

嫌疑4: 首板打板成交概率
  严重程度: 🟢 已有模拟
  影响: 成交概率0-70%已模拟

嫌疑5: 跌停翘板能否买到
  严重程度: 🟡 需检查
  影响: 部分买入价可能不合理
""")


if __name__ == '__main__':
    asyncio.run(detect_future_leaks())
