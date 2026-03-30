#!/usr/bin/env python3
"""
自动交易执行器
每日盘后读取信号，自动执行模拟交易
"""
import sys
import os
import json
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'AgentServer'))
sys.path.insert(0, os.path.dirname(__file__))

from paper_trading import PaperTradingEngine

def execute_daily_trades(date: str = None, account_id: str = None):
    """执行每日交易"""
    if not date:
        date = datetime.now().strftime("%Y%m%d")
    
    # 1. 读取当日信号
    signal_file = f"./signals/{date}.json"
    if not os.path.exists(signal_file):
        print(f"❌ 未找到{date}的信号文件")
        return False
    
    with open(signal_file, "r", encoding="utf-8") as f:
        signal_data = json.load(f)
    
    print(f"========== 执行 {date} 自动交易 ==========")
    print(f"📊 交易计划：{signal_data['trading_plan']}")
    
    if signal_data.get("force_empty") or not signal_data.get("signals"):
        print("ℹ️  今日无交易信号，保持空仓")
        return True
    
    # 2. 初始化模拟交易引擎
    engine = PaperTradingEngine()
    
    if not account_id:
        # 默认使用第一个活跃账户
        account_id = next((acc_id for acc_id, acc in engine.accounts.items() if acc.status == "active"), None)
        if not account_id:
            print("❌ 无可用活跃模拟账户")
            return False
    
    account = engine.accounts[account_id]
    print(f"💼 使用账户：{account.name}({account_id})，当前资金：{account.current_balance:.2f}元")
    
    # 3. 执行交易逻辑（先清空旧持仓，再买入新信号标的）
    pos_manager = engine.position_managers[account_id]
    current_positions = pos_manager.get_all_positions()
    
    # 卖出所有旧持仓
    if current_positions:
        print(f"📤 卖出所有现有持仓：{len(current_positions)}只")
        for pos in current_positions:
            # 模拟卖出，这里简化处理，实际应获取当日收盘价计算
            sell_price = 10.0  # 实际应从数据库获取
            engine.sell(
                account_id=account_id,
                ts_code=pos.ts_code,
                price=sell_price,
                shares=pos.shares,
                trade_date=date
            )
    
    # 买入新信号标的
    signals = signal_data["signals"]
    if signals:
        # 平均分配仓位
        per_stock_amount = account.current_balance * 0.7 / len(signals)
        print(f"📥 买入新标的：{len(signals)}只，每只分配{per_stock_amount:.2f}元")
        
        for signal in signals:
            buy_price = signal["price"]
            shares = int(per_stock_amount / buy_price / 100) * 100  # 整百股买入
            if shares <= 0:
                continue
            
            engine.buy(
                account_id=account_id,
                ts_code=signal["ts_code"],
                price=buy_price,
                shares=shares,
                trade_date=date,
                reason=signal["reason"]
            )
            print(f"✅ 买入 {signal['ts_code']} {signal['name']}：{shares}股，价格{buy_price:.2f}元")
    
    # 4. 更新账户绩效
    engine.update_account_performance(account_id, date)
    account = engine.accounts[account_id]
    print(f"📈 账户最新收益：{account.total_profit_pct:.2f}%，最大回撤：{account.max_drawdown:.2f}%")
    
    return True

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="自动交易执行器")
    parser.add_argument("--date", help="指定交易日期(YYYYMMDD)")
    parser.add_argument("--account", help="指定模拟账户ID")
    args = parser.parse_args()
    
    execute_daily_trades(args.date, args.account)
