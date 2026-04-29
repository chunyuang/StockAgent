#!/usr/bin/env python3
"""
移动端API服务
提供HTTP接口，供移动端APP/小程序调用，支持查询账户、持仓、信号、绩效，接收推送配置
"""
import sys
import os
import asyncio
import json
from datetime import datetime
from fastapi import FastAPI, HTTPException, Depends
from fastapi.security import APIKeyHeader
from pydantic import BaseModel
from typing import List, Dict, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'AgentServer'))  # FIXME: 使用sys.path.insert做模块查找是反模式，应改用setup.py/pyproject.toml将项目安装到venv中
sys.path.insert(0, os.path.dirname(__file__))

from multi_account_manager import MultiAccountManager
from performance_analyzer import PerformanceAnalyzer
from signal_pusher import SignalPusher

app = FastAPI(title="StockAgent 移动端API", version="1.0")

# API密钥验证 - 必须通过环境变量设置，无默认值
API_KEY = os.getenv("MOBILE_API_KEY", "")
if not API_KEY:
    import warnings
    warnings.warn("MOBILE_API_KEY 未设置，移动端API将无法访问！请在.env中配置MOBILE_API_KEY")
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

async def get_api_key(api_key: str = Depends(api_key_header)):
    if not API_KEY or api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API Key")
    return api_key

# 初始化管理器
account_manager = MultiAccountManager()

# 数据模型
class PushConfig(BaseModel):
    webhook_url: str
    push_type: str  # feishu/wecom/dingtalk
    push_empty: bool = False

class OrderRequest(BaseModel):
    account_id: str
    ts_code: str
    price: float
    shares: int
    order_type: str = "limit"

# 接口路由
@app.get("/api/health", tags=["基础"])
async def health_check():
    """健康检查"""
    return {"status": "ok", "timestamp": datetime.now().isoformat()}

@app.get("/api/accounts", tags=["账户管理"])
async def get_accounts(api_key: str = Depends(get_api_key)):
    """获取账户列表"""
    accounts = account_manager.list_accounts()
    return {"code": 0, "data": accounts, "msg": "success"}

@app.get("/api/accounts/{account_id}", tags=["账户管理"])
async def get_account_detail(account_id: str, api_key: str = Depends(get_api_key)):
    """获取账户详情"""
    info = account_manager.get_account_info(account_id)
    if not info:
        raise HTTPException(status_code=404, detail="账户不存在")
    return {"code": 0, "data": info, "msg": "success"}

@app.get("/api/accounts/{account_id}/performance", tags=["绩效分析"])
async def get_account_performance(account_id: str, period_days: int = 30, api_key: str = Depends(get_api_key)):
    """获取账户绩效"""
    if account_id not in account_manager.performance_analyzers:
        raise HTTPException(status_code=404, detail="账户不存在")
    
    analyzer = account_manager.performance_analyzers[account_id]
    end_date = datetime.now()
    start_date = end_date - timedelta(days=period_days)
    start_date_str = start_date.strftime("%Y%m%d")
    
    stats = analyzer.get_basic_stats(start_date_str)
    recent_trades = analyzer.get_trade_history(20)
    monthly_stats = analyzer.get_monthly_stats()
    strategy_analysis = analyzer.get_strategy_analysis()
    
    return {
        "code": 0,
        "data": {
            "basic": stats,
            "recent_trades": recent_trades,
            "monthly": monthly_stats,
            "strategy": strategy_analysis
        },
        "msg": "success"
    }

@app.get("/api/accounts/{account_id}/positions", tags=["持仓管理"])
async def get_positions(account_id: str, api_key: str = Depends(get_api_key)):
    """获取账户持仓"""
    if account_id not in account_manager.position_managers:
        raise HTTPException(status_code=404, detail="账户不存在")
    
    positions = account_manager.position_managers[account_id].get_positions()
    return {"code": 0, "data": positions, "msg": "success"}

@app.get("/api/accounts/{account_id}/trades", tags=["交易历史"])
async def get_trade_history(account_id: str, limit: int = 50, api_key: str = Depends(get_api_key)):
    """获取交易历史"""
    if account_id not in account_manager.performance_analyzers:
        raise HTTPException(status_code=404, detail="账户不存在")
    
    trades = account_manager.performance_analyzers[account_id].get_trade_history(limit)
    return {"code": 0, "data": trades, "msg": "success"}

@app.post("/api/push/test", tags=["推送管理"])
async def test_push(config: PushConfig, api_key: str = Depends(get_api_key)):
    """测试推送"""
    push_config = {}
    if config.push_type == "feishu":
        push_config["feishu_webhook"] = config.webhook_url
    elif config.push_type == "wecom":
        push_config["wecom_webhook"] = config.webhook_url
    elif config.push_type == "dingtalk":
        push_config["dingtalk_webhook"] = config.webhook_url
    else:
        raise HTTPException(status_code=400, detail="不支持的推送类型")
    
    pusher = SignalPusher(push_config)
    
    # 测试信号
    test_signal = {
        "date": datetime.now().strftime("%Y%m%d"),
        "force_empty": False,
        "sentiment": {"level": "修复", "score": 50, "position_limit": 0.7},
        "signals": [
            {"ts_code": "000001.SZ", "name": "平安银行", "strategy": "半路追涨", "close": 10.25, "pct_chg": 2.5}
        ],
        "trading_plan": "## 🎯 测试推送\n这是一条测试推送消息，用于验证推送配置是否正确。"
    }
    
    try:
        success = pusher.push(test_signal)
        if success:
            return {"code": 0, "msg": "推送测试成功"}
        else:
            return {"code": -1, "msg": "推送测试失败"}
    except Exception as e:
        return {"code": -1, "msg": f"推送异常：{str(e)}"}

@app.get("/api/signal/latest", tags=["信号服务"])
async def get_latest_signal(api_key: str = Depends(get_api_key)):
    """获取最新交易信号"""
    # 这里可以扩展调用信号生成器获取最新信号
    # 现在返回示例数据
    latest_date = datetime.now().strftime("%Y%m%d")
    return {
        "code": 0,
        "data": {
            "date": latest_date,
            "force_empty": False,
            "sentiment": {
                "score": 55,
                "level": "repair",
                "position_limit": 0.7,
                "allowed_strategies": ["龙头低吸", "半路追涨", "首板打板"]
            },
            "universe_size": 85,
            "signals": [
                {
                    "ts_code": "000001.SZ",
                    "name": "平安银行",
                    "strategy": "半路追涨",
                    "industry": "银行",
                    "close": 10.25,
                    "pct_chg": 2.5,
                    "amount": 12500,
                    "has_lhb": True,
                    "lhb_net_buy": 5200,
                    "suggest_buy_price": 10.35,
                    "stop_loss_price": 9.83,
                    "take_profit_price": 11.28
                },
                {
                    "ts_code": "600000.SH",
                    "name": "浦发银行",
                    "strategy": "首板打板",
                    "industry": "银行",
                    "close": 8.12
                }
            ]
        }
    }

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=8001)
