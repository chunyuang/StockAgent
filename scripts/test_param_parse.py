import json
from AgentServer.nodes.web.api.backtest import UltraShortBacktestRequest

# 模拟前端提交的完全一样的请求数据（和浏览器网络面板的JSON完全一致）
test_request_data = {
    "strategies": ["halfway_chase"],
    "start_date": "20260105",
    "end_date": "20260320",
    "initial_cash": 1000000,
    "params": {
        "liquidity_threshold": 500,
        "volume_threshold": 3.0,
        "stop_loss_pct": 0.05,
        "take_profit_pct": 0.1,
        "max_hold_days": 3,
        "max_position_per_stock": 0.3,
        "max_position": 0.7,
        # 这里模拟前端提交的selected_strategies，带参数
        "selected_strategies": [
            {
                "id": "halfway_chase",
                "name": "半路追涨",
                "params": {
                    "volume_threshold": 2.0,
                    "rise_range": "3%-7%"
                }
            }
        ]
    },
    "enable_force_empty": True,
    "enable_sentiment_cycle": True,
    "enable_auction_filter": True
}

print("="*80)
print("📌 1. 模拟前端提交的原始JSON:")
print(json.dumps(test_request_data, ensure_ascii=False, indent=2))
print("="*80)

print("\n📌 2. FastAPI反序列化后的对象:")
request = UltraShortBacktestRequest(**test_request_data)
print(f"   strategies: {request.strategies}")
print(f"   start_date: {request.start_date}")
print(f"   end_date: {request.end_date}")

print("\n📌 3. params子对象内容:")
print(f"   全局volume_threshold: {request.params.volume_threshold}")
print(f"   selected_strategies数量: {len(request.params.selected_strategies)}")

print("\n📌 4. 每个策略的params原始内容:")
for idx, strategy in enumerate(request.params.selected_strategies):
    print(f"   策略[{idx}] - {strategy['name']} ({strategy['id']}):")
    print(f"     params: {json.dumps(strategy['params'], ensure_ascii=False, indent=2)}")
    if 'volume_threshold' in strategy['params']:
        print(f"     ✅ 找到量比阈值: {strategy['params']['volume_threshold']}")

print("\n" + "="*80)
print("✅ 解析完成！如果上面能看到volume_threshold=2.0，说明后端解析逻辑100%正常")
print("如果看不到，就是反序列化逻辑有问题，需要修改模型定义")
