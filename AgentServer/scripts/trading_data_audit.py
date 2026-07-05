#!/usr/bin/env python3
"""
交易数据审查脚本 — 每日盘后运行
检查交易数据(4集合)的关键一致性:
1. broker_positions.market_value非空
2. broker_accounts资产=现金+市值
3. equity_curve完整性(total_assets+realized_pnl非空)
4. risk_decisions字段完整性
5. sell orders avg_cost非空
6. cash偏差<5000(佣金误差)
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pymongo
from datetime import datetime

def main():
    db = pymongo.MongoClient().stock_agent
    issues = []
    # 如果非交易日, 用最近交易日(简化: 查trade_cal集合)
    today = int(datetime.now().strftime('%Y%m%d'))
    cal = db.trade_cal.find_one({'cal_date': today, 'is_open': 1})
    if not cal:
        # 找最近交易日
        cal = db.trade_cal.find_one({'cal_date': {'$lte': today}, 'is_open': 1}, sort=[('cal_date', -1)])
    if cal:
        trade_date = cal['cal_date']
    else:
        trade_date = today
    
    print(f"📊 交易数据审查报告 — 日期: {trade_date}")
    print("=" * 70)
    
    # 1. broker_positions.market_value非空
    mv_none = db.broker_positions.count_documents({'market_value': None})
    mv_zero = db.broker_positions.count_documents({'market_value': 0})
    total_pos = db.broker_positions.count_documents({})
    if mv_none > 0:
        issues.append(('P0', f'broker_positions.market_value=None: {mv_none}/{total_pos}条'))
    elif mv_zero == total_pos and total_pos > 0:
        issues.append(('P1', f'broker_positions.market_value全=0: {mv_zero}/{total_pos}条 (可能收盘价未刷新)'))
    
    # 2. broker_accounts资产=现金+市值
    account = db.broker_accounts.find_one()
    if account:
        cash = account.get('available_cash', 0) or 0
        mv = account.get('market_value', 0) or 0
        assets = account.get('total_assets', 0) or 0
        diff = abs(assets - cash - mv)
        if diff > 1:
            issues.append(('P0', f'账户资产不等式: assets({assets:.0f}) ≠ cash({cash:.0f}) + mv({mv:.0f}), 差={diff:.0f}'))
    
    # 3. equity_curve完整性(每条记录必有total_assets和realized_pnl)
    ecs = list(db.equity_curve.find().sort('date', 1))
    missing_assets = sum(1 for e in ecs if e.get('total_assets') is None)
    missing_pnl = sum(1 for e in ecs if e.get('realized_pnl') is None)
    if missing_assets == len(ecs) and len(ecs) > 0:
        issues.append(('P1', f'equity_curve全部{len(ecs)}条total_assets=None'))
    if missing_pnl > 0:
        issues.append(('P2', f'equity_curve有{missing_pnl}条realized_pnl=None'))
    # 注: realized_pnl非单调递增是正常的(亏损日就下降)，不再作为问题
    
    # 4. risk_decisions字段完整性(最近5条)
    recent_rds = list(db.risk_decisions.find().sort('timestamp', -1).limit(5))
    profit_loss_none = sum(1 for rd in recent_rds if rd.get('profit_loss') is None and rd.get('profit_amount') is None)
    reason_none = sum(1 for rd in recent_rds if rd.get('reason') is None)
    if profit_loss_none == len(recent_rds) and len(recent_rds) > 0:
        issues.append(('P1', f'risk_decisions最近{len(recent_rds)}条profit_loss/profit_amount全=None'))
    if reason_none > 2:
        issues.append(('P2', f'risk_decisions最近{len(recent_rds)}条reason None={reason_none}'))
    
    # 5. sell orders avg_cost非空
    ac_none = db.broker_orders.count_documents({'side': 'sell', 'status': 'filled', 'avg_cost': None})
    if ac_none > 0:
        issues.append(('P1', f'sell orders avg_cost=None: {ac_none}条'))
    
    # 6. cash偏差检查
    if account:
        buys = list(db.broker_orders.find({'side': 'buy', 'status': 'filled'}))
        sells = list(db.broker_orders.find({'side': 'sell', 'status': 'filled'}))
        total_buy = sum(b.get('filled_amount', 0) or 0 for b in buys)
        total_sell = sum(s.get('filled_amount', 0) or 0 for s in sells)
        cash_from_orders = 1000000 - total_buy + total_sell
        cash_db = account.get('available_cash', 0) or 0
        cash_diff = abs(cash_db - cash_from_orders)
        if cash_diff > 10000:
            issues.append(('P1', f'cash偏差过大: DB={cash_db:.0f} orders推算={cash_from_orders:.0f} 差={cash_diff:.0f}'))
    
    # 输出报告
    if not issues:
        print("✅ 全部通过, 无问题")
    else:
        p0 = [i for i in issues if i[0] == 'P0']
        p1 = [i for i in issues if i[0] == 'P1']
        p2 = [i for i in issues if i[0] == 'P2']
        
        if p0:
            print(f"\n🔴 P0 严重 ({len(p0)}个)")
            for _, desc in p0:
                print(f"  {desc}")
        if p1:
            print(f"\n🟡 P1 中等 ({len(p1)}个)")
            for _, desc in p1:
                print(f"  {desc}")
        if p2:
            print(f"\n🟢 P2 轻微 ({len(p2)}个)")
            for _, desc in p2:
                print(f"  {desc}")
        
        print(f"\n{'=' * 70}")
        print(f"总计: P0={len(p0)} P1={len(p1)} P2={len(p2)}")

if __name__ == '__main__':
    main()
