#!/usr/bin/env python3
"""
回填 broker_orders 的 profit_pct 和 profit_amount

从同股票的买入和卖出价格配对计算盈亏
"""
import asyncio
import sys
import os
import re
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core.managers import mongo_manager


async def backfill_profit():
    await mongo_manager.initialize()
    db = mongo_manager.db
    
    # 按股票分组收集买卖记录
    stocks = defaultdict(lambda: {"buys": [], "sells": []})
    
    async for doc in db["broker_orders"].find({"status": "filled"}).sort("fill_time", 1):
        side = doc.get("side")
        ts_code = doc.get("ts_code", "")
        if side == "buy":
            stocks[ts_code]["buys"].append(doc)
        elif side == "sell":
            stocks[ts_code]["sells"].append(doc)
    
    # FIFO配对计算
    ops = []
    updated = 0
    
    for ts_code, data in stocks.items():
        buys = list(data["buys"])  # 复制，会pop
        for sell in data["sells"]:
            # 从reason提取profit_pct(如果有)
            reason = sell.get("reason", "")
            pct_match = re.search(r'曾盈([\d.]+)%', reason)
            if not pct_match:
                pct_match = re.search(r'([+-]?[\d.]+)%', reason)
            
            profit_pct = 0.0
            profit_amount = 0.0
            
            # 尝试从买入价计算
            remaining_qty = sell.get("filled_qty", 0) or 0
            total_cost = 0.0
            total_qty = 0
            
            while remaining_qty > 0 and buys:
                buy = buys[0]
                buy_qty = buy.get("filled_qty", 0) or 0
                buy_price = buy.get("filled_price", 0) or 0
                
                if buy_qty <= 0:
                    buys.pop(0)
                    continue
                
                match_qty = min(remaining_qty, buy_qty)
                total_cost += match_qty * buy_price
                total_qty += match_qty
                
                # 更新买入剩余
                buy["filled_qty"] = buy_qty - match_qty
                if buy["filled_qty"] <= 0:
                    buys.pop(0)
                remaining_qty -= match_qty
            
            sell_price = sell.get("filled_price", 0) or 0
            if total_qty > 0 and total_cost > 0:
                avg_buy_price = total_cost / total_qty
                profit_pct = round((sell_price - avg_buy_price) / avg_buy_price * 100, 2)
                profit_amount = round((sell_price - avg_buy_price) * (sell.get("filled_qty", 0) or 0), 2)
            elif pct_match:
                # fallback to reason
                try:
                    profit_pct = float(pct_match.group(1))
                    if "止损" in reason or "亏损" in reason or profit_pct > 0 and "-" not in reason and sell_price < total_cost / max(total_qty, 1):
                        pass  # keep sign from reason
                except:
                    pass
            
            if profit_pct != 0 or profit_amount != 0:
                ops.append({
                    "filter": {"_id": sell["_id"]},
                    "update": {"$set": {"profit_pct": profit_pct, "profit_amount": profit_amount}}
                })
                updated += 1
    
    # 批量更新
    if ops:
        from pymongo import UpdateOne
        bulk_ops = [UpdateOne(o["filter"], o["update"]) for o in ops]
        result = await db["broker_orders"].bulk_write(bulk_ops)
        print(f"更新 {result.modified_count} 条broker_orders的profit_pct")
    
    # 验证
    has_pp = await db["broker_orders"].count_documents({"profit_pct": {"$ne": 0}})
    total_sells = await db["broker_orders"].count_documents({"side": "sell", "status": "filled"})
    print(f"验证: {has_pp}/{total_sells} 条sell有profit_pct")
    
    # 展示几条
    async for doc in db["broker_orders"].find({"side": "sell", "profit_pct": {"$ne": 0}}).limit(5):
        print(f"  {doc['ts_code']} profit_pct={doc['profit_pct']}% profit_amount=¥{doc['profit_amount']}")


if __name__ == "__main__":
    asyncio.run(backfill_profit())
