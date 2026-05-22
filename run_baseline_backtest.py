#!/usr/bin/env python3
"""独立回测运行脚本 - 将结果写入backtest_tasks集合，可在前端回测历史中查看"""
import asyncio
import sys
import os
import time
import json
from datetime import datetime, timezone

# 添加路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'AgentServer'))

from core.managers import mongo_manager
from nodes.backtest_engine.factor_selection import PortfolioBacktester
from nodes.backtest_engine.strategy_defaults import ALL_STRATEGIES, STRATEGY_CONFIGS


async def run_backtest():
    """运行标准3个月回测(2025Q1)"""
    await mongo_manager.initialize()
    
    # 构建配置 - 与前端提交一致的格式
    selected_strategies = []
    for cfg in STRATEGY_CONFIGS.values():
        if cfg.get('enabled', True):
            selected_strategies.append({
                "id": cfg["id"],
                "name": cfg["name"],
                "params": dict(cfg["params"]),
                "riskParams": dict(cfg["riskParams"]),
            })
    
    # 生成task_id - 使用cron前缀标识定时回测
    now = datetime.now(timezone.utc)
    task_id = f"cron_{now.strftime('%Y%m%d%H%M%S')}"
    
    config = {
        "start_date": "20250101",
        "end_date": "20250331",
        "initial_cash": 1000000,
        "max_position_percent": 0.2,
        "liquidity_threshold": 500,
        "factors": [],
        "top_n": 3,
        "rebalance_freq": "daily",
        "task_id": task_id,
        "push_log": None,
        "strategy_weights": {s["name"]: 1.0/len(selected_strategies) for s in selected_strategies},
        "selected_strategies": selected_strategies,
        "weight_method": "equal",
        "commission_rate": 0.0003,
        "stamp_duty_rate": 0.001,
        "slippage_pct": 0.002,
        "stop_loss_pct": 0.03,
        "take_profit_pct": 0.07,
        "max_hold_days": 3,
        "max_position_per_stock": 0.2,
        "enable_auction_filter": True,
        "enable_sentiment_cycle": True,
        "enable_force_empty": True,
        "enable_stop_loss": True,
        "enable_take_profit": True,
        "enable_ma60_filter": True,
        "enable_sector_concentration": True,
        "force_empty_config": {},
        "global_filter_config": {},
    }
    
    # ====== 关键修复: 先写入backtest_tasks集合(状态running) ======
    task_doc = {
        "task_id": task_id,
        "task_type": "ultra_short",  # 必须有此字段，前端history查询依赖
        "status": "running",
        "progress": 0,
        "params": {
            "strategies": [s["id"] for s in selected_strategies],
            "start_date": config["start_date"],
            "end_date": config["end_date"],
            "initial_cash": config["initial_cash"],
            "params": {
                "liquidity_threshold": config["liquidity_threshold"],
                "stop_loss_pct": config["stop_loss_pct"],
                "take_profit_pct": config["take_profit_pct"],
                "max_hold_days": config["max_hold_days"],
                "commission_rate": config["commission_rate"],
                "stamp_duty_rate": config["stamp_duty_rate"],
                "slippage_pct": config["slippage_pct"],
                "enable_force_empty": config["enable_force_empty"],
                "enable_stop_loss": config["enable_stop_loss"],
                "enable_take_profit": config["enable_take_profit"],
                "enable_ma60_filter": config["enable_ma60_filter"],
                "enable_sector_concentration": config["enable_sector_concentration"],
                "selected_strategies": selected_strategies,
            },
            "selected_strategies": selected_strategies,
            "enable_force_empty": config["enable_force_empty"],
            "enable_sentiment_cycle": config["enable_sentiment_cycle"],
            "enable_auction_filter": config["enable_auction_filter"],
        },
        "created_at": now,
    }
    await mongo_manager.insert_one("backtest_tasks", task_doc)
    print(f"任务已写入backtest_tasks: {task_id}")
    
    # ====== 执行回测 ======
    backtester = PortfolioBacktester()
    
    start = time.time()
    result = await backtester.run(config)
    elapsed = time.time() - start
    
    if result and 'error' not in result:
        metrics = result.get('metrics', {})
        returns = metrics.get('returns', {})
        risk = metrics.get('risk', {})
        trades = metrics.get('trades', {})
        
        print(f"\n{'='*60}")
        print(f"回测结果 (2025Q1)")
        print(f"{'='*60}")
        print(f"总收益: {returns.get('total_return_pct', 0):.2f}%")
        print(f"年化收益: {returns.get('annual_return_pct', 0):.2f}%")
        print(f"最大回撤: {risk.get('max_drawdown_pct', 0):.2f}%")
        print(f"胜率: {risk.get('win_rate_pct', 0):.2f}%")
        print(f"夏普: {risk.get('sharpe_ratio', 0):.2f}")
        print(f"索提诺: {risk.get('sortino_ratio', 0):.2f}")
        print(f"卡玛: {risk.get('calmar_ratio', 0):.2f}")
        print(f"盈亏比: {risk.get('profit_loss_ratio', 0):.2f}")
        print(f"交易笔数: {trades.get('total_trades', 0)}")
        print(f"耗时: {elapsed:.1f}s")
        
        # 策略分解
        strategy_results = result.get('strategy_results', {})
        print(f"\n策略分解:")
        for sname, sdata in strategy_results.items():
            print(f"  {sname}: {sdata.get('trades_count',0)}笔 "
                  f"胜率{sdata.get('win_rate',0):.1f}% "
                  f"收益{sdata.get('total_return',0):.2f}% "
                  f"盈亏比{sdata.get('profit_loss_ratio',0):.2f}")
        
        # 月度收益
        monthly = result.get('monthly_profit', {})
        print(f"\n月度收益:")
        for month, ret in monthly.items():
            print(f"  {month}: {ret*100:.2f}%")
        
        # ====== 关键修复: 更新backtest_tasks状态为completed ======
        # 注意: result中包含大量数据(交易记录、净值曲线等)，需要完整保存
        # MongoDB单文档上限16MB，需要精简不必要的大数组
        save_result = {}
        for k, v in result.items():
            if k in ['push_log']:
                continue
            # 精简大数组，只保留统计摘要
            if k == 'net_value_series' and isinstance(v, list):
                save_result[k] = v  # 净值曲线不大，保留
            elif k == 'drawdown_series' and isinstance(v, list):
                save_result[k] = v  # 回撤曲线保留
            elif k == 'daily_profit' and isinstance(v, list):
                save_result[k] = v  # 日收益保留
            elif k in ('all_trades', 'merged_trades', 'rebalance_records'):
                # 交易记录保留(前端详情页需要)
                save_result[k] = v
            else:
                save_result[k] = v
        
        await mongo_manager.update_one(
            "backtest_tasks",
            {"task_id": task_id},
            {"$set": {
                "status": "completed",
                "progress": 100,
                "result": save_result,
                "completed_at": datetime.now(timezone.utc),
            }}
        )
        print(f"\n✅ 结果已写入backtest_tasks，可在前端回测历史中查看")
        
    else:
        # 回测失败
        error_msg = str(result.get('error', 'Unknown error'))
        await mongo_manager.update_one(
            "backtest_tasks",
            {"task_id": task_id},
            {"$set": {
                "status": "failed",
                "progress": 100,
                "error": error_msg,
                "completed_at": datetime.now(timezone.utc),
            }}
        )
        print(f"❌ 回测失败: {error_msg}")
    
    await mongo_manager.shutdown()

if __name__ == "__main__":
    asyncio.run(run_backtest())
