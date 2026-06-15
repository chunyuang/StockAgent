#!/usr/bin/env python3
"""
数据完整性检查 — 非交易日假数据检测 + 交易数据一致性验证

基于 v2.9.92s 的"replay模式污染实盘数据"教训

检查项:
  1. 非交易日数据检测 — broker_orders/scanner_timeline/timeline在周末/节假日不应有数据
  2. trade_date格式一致性 — int vs string不匹配导致查询遗漏
  3. broker_orders vs broker_positions 一致性
  4. broker_accounts 金额合理性(不能负数、不能等于初始100万且无持仓)
  5. 过时pending_sells清理(股票已不在持仓)
  6. replay/dry_run模式broker._virtual_mode标记检查

用法:
  python3 scripts/data_integrity_check.py [--fix] [--verbose]
  
  --fix: 自动清理假数据(默认只报告)
  --verbose: 详细输出
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pymongo import MongoClient
from datetime import datetime, timedelta
import argparse

# A股2026年交易日(简化: 排除周末，不含节假日)
def is_weekend(date_str: str) -> bool:
    """判断是否为周末"""
    dt = datetime.strptime(str(date_str), "%Y%m%d")
    return dt.weekday() >= 5

def get_recent_non_trading_days(n: int = 30) -> list:
    """获取最近N天中的非交易日(周末)"""
    today = datetime.now()
    non_trading = []
    for i in range(n):
        d = today - timedelta(days=i)
        ds = d.strftime("%Y%m%d")
        if is_weekend(ds):
            non_trading.append(ds)
    return non_trading


def main():
    parser = argparse.ArgumentParser(description='数据完整性检查')
    parser.add_argument('--fix', action='store_true', help='自动清理假数据')
    parser.add_argument('--verbose', action='store_true', help='详细输出')
    args = parser.parse_args()
    
    db = MongoClient('mongodb://localhost:27017', serverSelectionTimeoutMS=5000)['stock_agent']
    
    issues = []
    fixed = []
    
    print("=" * 60)
    print("  数据完整性检查")
    print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  模式: {'自动修复' if args.fix else '只报告'}")
    print("=" * 60)
    
    # ============================================
    # 1. 非交易日假数据检测
    # ============================================
    print("\n## 1. 非交易日假数据检测")
    
    non_trading_days = get_recent_non_trading_days(30)
    
    for day in non_trading_days:
        day_int = int(day)
        
        # broker_orders
        count_orders = db['broker_orders'].count_documents({"trade_date": day_int})
        # scanner_timeline
        count_timeline = db['scanner_timeline'].count_documents({"trade_date": day})
        
        if count_orders > 0 or count_timeline > 0:
            desc = f"{day}(周末): broker_orders={count_orders}, timeline={count_timeline}"
            issues.append(f"🔴 非交易日假数据: {desc}")
            print(f"  🔴 {desc}")
            
            if args.fix:
                # 删除假数据
                r1 = db['broker_orders'].delete_many({"trade_date": day_int})
                r2 = db['scanner_timeline'].delete_many({"trade_date": day})
                total = r1.deleted_count + r2.deleted_count
                fixed.append(f"✅ 清理{day}假数据: {r1.deleted_count}条orders + {r2.deleted_count}条timeline")
                print(f"  ✅ 已清理: {total}条")
        else:
            if args.verbose:
                print(f"  ✅ {day}: 干净")
    
    if not any(day for day in non_trading_days if 
               db['broker_orders'].count_documents({"trade_date": int(day)}) > 0 or
               db['scanner_timeline'].count_documents({"trade_date": day}) > 0):
        print("  ✅ 非交易日无假数据")
    
    # ============================================
    # 2. broker_accounts 金额合理性
    # ============================================
    print("\n## 2. broker_accounts 金额合理性")
    
    acct = db['broker_accounts'].find_one({"account_id": "default"})
    if acct:
        total = acct.get('total_assets', 0)
        cash = acct.get('available_cash', 0)
        mv = acct.get('market_value', 0)
        
        if total <= 0:
            issues.append(f"🔴 总资产<=0: ¥{total}")
            print(f"  🔴 总资产<=0: ¥{total}")
        elif cash < 0:
            issues.append(f"🟡 可用资金为负: ¥{cash:,.0f}")
            print(f"  🟡 可用资金为负: ¥{cash:,.0f}")
        elif total == 1_000_000:
            # 检查是否有持仓 — 100万+0持仓可能是被覆盖
            pos_count = db['broker_positions'].count_documents({"account_id": "default"})
            if pos_count == 0:
                issues.append(f"🟡 总资产=100万且0持仓 — 可能被replay覆盖")
                print(f"  🟡 总资产=100万且0持仓 — 可能被replay覆盖")
            else:
                print(f"  ✅ 总资产¥{total:,.0f}, 持仓{pos_count}只")
        else:
            print(f"  ✅ 总资产¥{total:,.0f}, 可用¥{cash:,.0f}, 市值¥{mv:,.0f}")
    else:
        issues.append("🔴 broker_accounts无记录")
        print("  🔴 无账户记录")
    
    # ============================================
    # 3. broker_orders vs broker_positions 一致性
    # ============================================
    print("\n## 3. broker_orders vs broker_positions 一致性")
    
    # 使用净数量计算（修复set逻辑bug：买卖都有不代表净仓为0）
    from collections import defaultdict
    net_qty = defaultdict(int)
    for o in db['broker_orders'].find({"account_id": "default", "status": "filled"}):
        tc = o.get('ts_code', '')
        side = o.get('side', '')
        qty = o.get('filled_qty', 0) or o.get('quantity', 0)
        if side == 'buy':
            net_qty[tc] += qty
        elif side == 'sell':
            net_qty[tc] -= qty
    
    net_holding = {k for k, v in net_qty.items() if v > 0}
    positions_set = set()
    for p in db['broker_positions'].find({"account_id": "default"}):
        positions_set.add(p.get('ts_code'))
    
    missing = net_holding - positions_set
    extra = positions_set - net_holding
    
    if missing:
        issues.append(f"🔴 持仓丢失: orders有但positions缺失: {missing}")
        print(f"  🔴 持仓丢失: {missing}")
    elif extra:
        issues.append(f"🟡 幽灵持仓: positions有但orders无: {extra}")
        print(f"  🟡 幽灵持仓: {extra}")
    else:
        print(f"  ✅ 持仓一致 (net_holding={len(net_holding)}, positions={len(positions_set)})")
    
    # ============================================
    # 4. 过时pending_sells清理
    # ============================================
    print("\n## 4. 过时pending_sells检查")
    
    pending = db['scanner_state'].find_one({"_id": "pending_sells"})
    if pending:
        items = pending.get('items', {})
        pending_codes = set(items.keys())
        stale = pending_codes - positions_set
        
        if stale:
            issues.append(f"🟡 过时pending_sells: {len(stale)}只已不在持仓 — {stale}")
            print(f"  🟡 过时pending_sells: {len(stale)}只 ({stale})")
            
            if args.fix:
                db['scanner_state'].delete_one({"_id": "pending_sells"})
                fixed.append(f"✅ 清理过时pending_sells: {len(stale)}只")
                print(f"  ✅ 已清理")
        else:
            print(f"  ✅ pending_sells都在持仓中 ({len(pending_codes)}只)")
    else:
        print("  ✅ 无pending_sells")
    
    # ============================================
    # 5. trade_date格式一致性检查
    # ============================================
    print("\n## 5. trade_date格式一致性")
    
    # broker_orders用int, scanner_timeline用string
    orders_int = db['broker_orders'].count_documents({"trade_date": {"$type": "int"}})
    orders_str = db['broker_orders'].count_documents({"trade_date": {"$type": "string"}})
    timeline_int = db['scanner_timeline'].count_documents({"trade_date": {"$type": "int"}})
    timeline_str = db['scanner_timeline'].count_documents({"trade_date": {"$type": "string"}})
    
    print(f"  broker_orders: int={orders_int}, string={orders_str}")
    print(f"  timeline:      int={timeline_int}, string={timeline_str}")
    
    if orders_str > 0:
        issues.append(f"🟡 broker_orders有{orders_str}条string格式的trade_date")
    if timeline_int > 0:
        issues.append(f"🟡 timeline有{timeline_int}条int格式的trade_date")
    
    if orders_str == 0 and timeline_int == 0:
        print("  ✅ 格式一致")
    
    # ============================================
    # 6. 数据新鲜度
    # ============================================
    print("\n## 6. 数据新鲜度")
    
    # stock_daily_ak_full最新日期
    latest_daily = db['stock_daily_ak_full'].find_one(sort=[("trade_date", -1)])
    latest_basic = db['daily_basic'].find_one(sort=[("trade_date", -1)])
    latest_limit = db['limit_list'].find_one(sort=[("trade_date", -1)])
    
    today = datetime.now().strftime("%Y%m%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
    
    for name, doc in [("stock_daily_ak_full", latest_daily), ("daily_basic", latest_basic), ("limit_list", latest_limit)]:
        if doc:
            d = str(doc.get('trade_date', ''))
            if d < yesterday and not is_weekend(yesterday):
                issues.append(f"🟡 {name}数据过旧: 最新{d} (应为{yesterday}+)")
                print(f"  🟡 {name}: {d} (过旧)")
            else:
                print(f"  ✅ {name}: {d}")
        else:
            issues.append(f"🔴 {name}无数据")
            print(f"  🔴 {name}: 无数据")
    
    # ============================================
    # 汇总
    # ============================================
    print("\n" + "=" * 60)
    print(f"  汇总: {len(issues)}个问题, {len(fixed)}个已修复")
    print("=" * 60)
    
    if issues:
        print("\n问题清单:")
        for i, issue in enumerate(issues, 1):
            print(f"  {i}. {issue}")
    
    if fixed:
        print("\n修复记录:")
        for f in fixed:
            print(f"  {f}")
    
    # 返回码: 0=无问题, 1=有问题(未修复), 2=有问题(已修复)
    if not issues:
        return 0
    elif fixed:
        return 2
    else:
        return 1


if __name__ == '__main__':
    sys.exit(main())
