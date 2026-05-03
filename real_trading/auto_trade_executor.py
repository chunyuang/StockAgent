#!/usr/bin/env python3
"""
自动交易执行器
每日盘后读取信号，自动执行模拟交易
"""
import sys
import logging

logger = logging.getLogger(__name__)
import os
import json
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'AgentServer'))  # FIXME: 使用sys.path.insert做模块查找是反模式，应改用setup.py/pyproject.toml将项目安装到venv中
sys.path.insert(0, os.path.dirname(__file__))

from paper_trading import PaperTradingEngine

async def execute_daily_trades(date: str = None, account_id: str = None):
    """执行每日自动交易
    
    完整流程：
    1. 读取当日信号JSON文件（./signals/{date}.json）
    2. 初始化模拟交易引擎，选择活跃账户
    3. 先清空所有旧持仓（模拟卖出）
    4. 按信号买入新标的，平均分配70%仓位
    5. 更新账户绩效指标
    
    Args:
        date: 交易日期（YYYYMMDD），默认当天
        account_id: 指定账户ID，None则使用第一个活跃账户
    
    Returns:
        bool: True执行成功，False执行失败（信号文件缺失或无可用账户）
    """
    if not date:
        date = datetime.now().strftime("%Y%m%d")
    
    # 1. 读取当日信号
    signal_file = f"./signals/{date}.json"  # FIXME: 相对路径，应在项目根目录下使用绝对路径，如 os.path.join(PROJECT_ROOT, 'signals', f'{date}.json')
    if not os.path.exists(signal_file):
        logger.error(f"❌ 未找到{date}的信号文件")
        return False
    
    with open(signal_file, "r", encoding="utf-8") as f:
        signal_data = json.load(f)
    
    logger.info(f"========== 执行 {date} 自动交易 ==========")
    logger.info(f"📊 交易计划：{signal_data['trading_plan']}")
    
    if signal_data.get("force_empty") or not signal_data.get("signals"):
        logger.info("ℹ️  今日无交易信号，保持空仓")
        return True
    
    # 2. 初始化模拟交易引擎
    engine = PaperTradingEngine()
    
    if not account_id:
        # 默认使用第一个活跃账户
        account_id = next((acc_id for acc_id, acc in engine.accounts.items() if acc.status == "active"), None)
        if not account_id:
            logger.error("❌ 无可用活跃模拟账户")
            return False
    
    account = engine.accounts[account_id]
    logger.info(f"💼 使用账户：{account.name}({account_id})，当前资金：{account.current_balance:.2f}元")
    
    # 3. 执行交易逻辑（增量调仓：只卖出不在新信号中的持仓，只买入新信号标的）
    pos_manager = engine.position_managers[account_id]
    current_positions = pos_manager.get_all_positions()
    current_codes = {pos.ts_code for pos in current_positions} if current_positions else set()
    signals = signal_data["signals"] or []
    new_signal_codes = {s["ts_code"] for s in signals}
    
    # 卖出不在新信号中的旧持仓（保留仍在信号中的持仓）
    sell_codes = current_codes - new_signal_codes
    if sell_codes:
        logger.info(f"📤 卖出不在新信号中的持仓：{len(sell_codes)}只（保留{len(current_codes - sell_codes)}只）")
        for pos in current_positions:
            if pos.ts_code not in sell_codes:
                continue
            # 卖出价从MongoDB获取收盘价
            try:
                from core.managers import mongo_manager
                await mongo_manager.initialize()
                doc = await mongo_manager.find_one(
                    "stock_daily_ak_full",
                    {"ts_code": pos.ts_code, "trade_date": int(date)},
                    projection={"close": 1}
                )
                sell_price = doc["close"] if doc and doc.get("close", 0) > 0 else pos.cost_price
            except Exception:
                sell_price = pos.cost_price  # 回退到成本价
            engine.sell(
                account_id=account_id,
                ts_code=pos.ts_code,
                price=sell_price,
                shares=pos.shares,
                trade_date=date
            )
    else:
        logger.info(f"📤 无需卖出（无旧持仓或所有旧持仓仍在信号中）")
    
    # 买入新信号标的（仅买入当前未持仓的）
    buy_codes = new_signal_codes - current_codes
    if buy_codes:
        # 仅买入新标的（不在当前持仓中的）
        buy_signals = [s for s in signals if s["ts_code"] in buy_codes]
        per_stock_amount = account.current_balance * 0.7 / max(len(buy_signals), 1)
        logger.info(f"📥 买入新标的：{len(buy_signals)}只（保留{len(current_codes & new_signal_codes)}只），每只分配{per_stock_amount:.2f}元")
        
        for signal in buy_signals:
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
            logger.info(f"✅ 买入 {signal['ts_code']} {signal['name']}：{shares}股，价格{buy_price:.2f}元")
    
    # 4. 更新账户绩效
    engine.update_account_performance(account_id, date)
    account = engine.accounts[account_id]
    logger.info(f"📈 账户最新收益：{account.total_profit_pct:.2f}%，最大回撤：{account.max_drawdown:.2f}%")
    
    return True

if __name__ == "__main__":
    import argparse
    import asyncio
    parser = argparse.ArgumentParser(description="自动交易执行器")
    parser.add_argument("--date", help="指定交易日期(YYYYMMDD)")
    parser.add_argument("--account", help="指定模拟账户ID")
    args = parser.parse_args()
    
    asyncio.run(execute_daily_trades(args.date, args.account))
