#!/usr/bin/env python3
"""自测脚本：提交一次完整回测验证全流程"""

import asyncio
import aiohttp
import json

async def main():
    url = "http://localhost:8000/api/backtest/submit"
    
    # 超短策略回测配置 - half way chase 策略
    config = {
        "strategy_name": "ultra_short_combo",
        "start_date": 20260105,
        "end_date": 20260110,  # 先跑几个交易日测试
        "initial_cash": 1000000,
        "position_limit": 5,
        "models": [
            {
                "strategy_name": "halfway_chase",
                "params": {
                    "volume_increase_min": 0.5,
                    "limit_up_amount_min": 10000,
                    "pullback_ma5": 1,
                    "sentiment_score_min": 100
                }
            }
        ],
        "weight_method": "equal",
        "risk_config": {
            "enable_ma60_filter": True
        },
        "benchmark_code": "000001.SH"
    }
    
    print(f"🚀 提交回测: {config['strategy_name']} {config['start_date']} ~ {config['end_date']}")
    print(f"配置: {json.dumps(config, indent=2)}")
    
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=config) as response:
            result = await response.json()
            print(f"\n📋 响应: {json.dumps(result, indent=2, ensure_ascii=False)}")
            return result

if __name__ == "__main__":
    asyncio.run(main())
