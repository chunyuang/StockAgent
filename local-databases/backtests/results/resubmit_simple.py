#!/usr/bin/env python3
"""
简化版本，直接打印错误
"""

import requests
import sys

# 超短策略配置
config = {
    "start_date": "20260105",
    "end_date": "20260320",
    "initial_cash": 1000000,
    "strategies": ["halfway_chase", "first_limit_up", "limit_up_open", "leader_buy_dip", "limit_down_qiao"],
    "selected_strategies": [
        {
            "name": "半路追涨",
            "params": {
                "min_rise_pct": 0.03,
                "max_rise_pct": 0.07,
                "volume_threshold": 1.5,
                "allow_after_10am": False
            }
        },
        {
            "name": "首板打板",
            "params": {
                "min_seal_amount": 5000,
                "max_limit_up_time": 600,
                "max_circulation_market_cap": 100,
                "max_blast_count": 1,
                "require_hot_sector": True
            }
        },
        {
            "name": "涨停开板",
            "params": {
                "min_consecutive_limit": 2,
                "max_open_duration": 5,
                "min_seal_after_open": 3000,
                "min_turnover_rate": 0.15
            }
        },
        {
            "name": "龙头低吸",
            "params": {
                "min_correction_pct": 0.15,
                "max_correction_pct": 0.30,
                "correction_days_min": 2,
                "correction_days_max": 5,
                "support_level": "ma5"
            }
        },
        {
            "name": "跌停翘板",
            "params": {
                "open_above_limit_down": True,
                "min_qiao_amount": 10000,
                "min_rise_after_qiao": 0.03,
                "require_high_sentiment": True
            }
        }
    ],
    "params": {
        "liquidity_threshold": 500,
        "volume_threshold": 1.5,
        "stop_loss_pct": 0.05,
        "take_profit_pct": 0.10,
        "max_hold_days": 3,
        "max_position": 0.7,
        "max_position_per_stock": 0.2,
        "force_empty_position": True,
        "sentiment_cycle": True,
        "auction_filter": True,
        "selected_strategies": [
            {
                "name": "半路追涨",
                "params": {
                    "min_rise_pct": 0.03,
                    "max_rise_pct": 0.07,
                    "volume_threshold": 1.5,
                    "allow_after_10am": False
                }
            },
            {
                "name": "首板打板",
                "params": {
                    "min_seal_amount": 5000,
                    "max_limit_up_time": 600,
                    "max_circulation_market_cap": 100,
                    "max_blast_count": 1,
                    "require_hot_sector": True
                }
            },
            {
                "name": "涨停开板",
                "params": {
                    "min_consecutive_limit": 2,
                    "max_open_duration": 5,
                    "min_seal_after_open": 3000,
                    "min_turnover_rate": 0.15
                }
            },
            {
                "name": "龙头低吸",
                "params": {
                    "min_correction_pct": 0.15,
                    "max_correction_pct": 0.30,
                    "correction_days_min": 2,
                    "correction_days_max": 5,
                    "support_level": "ma5"
                }
            },
            {
                "name": "跌停翘板",
                "params": {
                    "open_above_limit_down": True,
                    "min_qiao_amount": 10000,
                    "min_rise_after_qiao": 0.03,
                    "require_high_sentiment": True
                }
            }
        ]
    },
    "enable_force_empty": True,
    "enable_sentiment_cycle": True,
    "enable_auction_filter": True,
}

base_url = "http://localhost:8000"
print(f"🔍 提交回测请求到: {base_url}/api/v1/backtest/ultra-short")
print(f"回测区间: {config['start_date']} ~ {config['end_date']}")
print(f"选中策略数量: {len(config['selected_strategies'])}")

try:
    response = requests.post(f"{base_url}/api/v1/backtest/ultra-short", json=config, timeout=30)
    print(f"📡 响应码: {response.status_code}")
    print(f"📄 响应内容: {response.text}")
except Exception as e:
    print(f"❌ 异常: {e}")
    sys.exit(1)
