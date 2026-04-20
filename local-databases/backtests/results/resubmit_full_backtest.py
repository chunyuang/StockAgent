#!/usr/bin/env python3
"""
重新提交完整组合回测
参数：20260105 ~ 20260320，全选5个策略，初始资金100万
"""

import requests
import json
import sys
import time

# 回测配置
config = {
    "start_date": "20260105",
    "end_date": "20260320",
    "initial_cash": 1000000,
    "rebalance_freq": "daily",
    "weight_method": "equal",
    "top_n": 20,
    "selected_strategies": [
        {
            "name": "半路追涨",
            "params": {
                "limit_up_open_ratio_min": 1.5,
                "pct_chg_min": 0.03,
                "pct_chg_max": 0.07,
                "allow_after_10am": False
            }
        },
        {
            "name": "首板打板",
            "params": {
                "limit_up_amount_min": 5000,
                "limit_up_time_max": 600,
                "circ_mv_max": 1000000,
                "limit_up_open_count_max": 1,
                "require_hot_sector": True
            }
        },
        {
            "name": "涨停开板",
            "params": {
                "limit_up_count_min": 2,
                "limit_up_open_duration_max": 5,
                "limit_up_open_amount_min": 3000,
                "turnover_rate_min": 0.15
            }
        },
        {
            "name": "龙头低吸",
            "params": {
                "pullback_pct_max": 0.07,
                "pullback_days_max": 5,
                "prev_leader": True
            }
        },
        {
            "name": "跌停翘板",
            "params": {
                "open_above_limit_down": True,
                "limit_down_open_amount_min": 5000,
                "rise_after_limit_down": True
            }
        }
    ]
}

# 提交回测 - 超短策略专用端点
base_url = "http://localhost:8000"
print("🔍 提交回测请求...")
print(f"回测区间: {config['start_date']} ~ {config['end_date']}")
print(f"初始资金: {config['initial_cash']}")
print(f"选中策略: {[s['name'] for s in config['selected_strategies']]}")

# 转换为超短API要求的格式
# 中文 -> 英文id映射
strategy_id_map = {
    "半路追涨": "halfway_chase",
    "首板打板": "first_limit_up",
    "涨停开板": "limit_up_open",
    "龙头低吸": "leader_buy_dip",
    "跌停翘板": "limit_down_qiao",
}

ultra_short_config = {
    "start_date": config["start_date"],
    "end_date": config["end_date"],
    "initial_cash": config["initial_cash"],
    "strategies": [strategy_id_map[s["name"]] for s in config["selected_strategies"]],
    "selected_strategies": config["selected_strategies"],
    "params": {
        "selected_strategies": config["selected_strategies"],
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
    },
    "enable_force_empty": True,
    "enable_sentiment_cycle": True,
    "enable_auction_filter": True,
}

print(f"🔧 转换为超短API格式，策略ids: {ultra_short_config['strategies']}")

try:
    response = requests.post(f"{base_url}/api/v1/backtest/ultra-short", json=ultra_short_config, timeout=30)
    print(f"📡 响应码: {response.status_code}")
    
    if response.status_code == 200:
        result = response.json()
        print(f"📄 完整响应: {result}")
        # 超短API返回格式不同
        if "task_id" in result:
            task_id = result["task_id"]
            print(f"✅ 回测提交成功，task_id: {task_id}")
            
            # 等待回测完成
            print("\n⏳ 等待回测完成...")
            last_progress = ""
            
            while True:
                time.sleep(30)  # 每30秒检查一次
                status_response = requests.get(f"{base_url}/api/backtest/status/{task_id}", timeout=10)
                if status_response.status_code == 200:
                    status_result = status_response.json()
                    if status_result.get("success"):
                        status = status_result["data"]["status"]
                        if "progress" in status_result["data"]:
                            progress = status_result["data"]["progress"]
                            if progress != last_progress:
                                print(f"  进度: {progress}")
                                last_progress = progress
                        
                        if status == "completed":
                            print("\n✅ 回测完成！正在获取结果...")
                            # 获取完整结果
                            result_response = requests.get(f"{base_url}/api/backtest/result/{task_id}", timeout=60)
                            if result_response.status_code == 200:
                                full_result = result_response.json()
                                
                                # 保存到指定路径
                                output_path = f"/root/.openclaw/workspace/StockAgent/local-databases/backtests/results/task3-{config['start_date']}-{config['end_date']}-{config['initial_cash']}.json"
                                
                                with open(output_path, "w", encoding="utf-8") as f:
                                    json.dump(full_result, f, ensure_ascii=False, indent=2)
                                
                                print(f"💾 结果已保存到: {output_path}")
                                print(f"📊 文件大小: {len(json.dumps(full_result)) / 1024 / 1024:.2f} MB")
                                
                                # 验证内容
                                if "combination" in full_result.get("data", {}):
                                    print("✅ 包含组合绩效数据")
                                if "strategies" in full_result.get("data", {}):
                                    print("✅ 包含各策略单独绩效数据")
                                if "rebalance_records" in full_result.get("data", {}):
                                    records = full_result["data"]["rebalance_records"]
                                    print(f"✅ 包含 {len(records)} 条调仓交易记录")
                                
                                sys.exit(0)
                            else:
                                print(f"❌ 获取结果失败: {result_response.status_code}")
                                sys.exit(1)
                        elif status == "failed":
                            error_msg = status_result["data"].get("error", "未知错误")
                            print(f"❌ 回测失败: {error_msg}")
                            sys.exit(1)
            else:
                print(f"❌ 获取状态失败: {status_response.text}")
                sys.exit(1)
        else:
            print(f"❌ 提交失败: {result.get('message', '未知错误')}")
            sys.exit(1)
    else:
        print(f"❌ 提交失败，状态码: {response.status_code}")
        print(f"响应: {response.text}")
        sys.exit(1)
except Exception as e:
    print(f"❌ 异常: {e}")
    sys.exit(1)
