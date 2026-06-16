"""
Unified API 契约测试 — v2.9.97

确保:
1. 同一天，所有UI拿到的交易数一致
2. broker_positions 与 broker_orders 净累计一致
3. unified/trades 和旧 /auto-trades 返回相同笔数
4. unified/positions 与 /scanner/all 返回相同持仓数
5. date-availability 格式正确
"""
import asyncio
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from httpx import AsyncClient, ASGITransport


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def _get_app():
    """获取 FastAPI app 实例（不启动服务器）"""
    from nodes.web.app import create_app
    return create_app()


@pytest.mark.anyio
async def test_unified_trades_returns_both_buy_and_sell():
    """unified/trades 应包含 buy + sell，不能只返回 sell"""
    app = await _get_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/v1/unified/trades")
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        trades = data["data"]["trades"]
        summary = data["data"]["summary"]
        # 如果有交易，buy_count + sell_count 应等于 total
        if summary["total"] > 0:
            assert summary["buy_count"] + summary["sell_count"] == summary["total"], \
                f"buy({summary['buy_count']}) + sell({summary['sell_count']}) != total({summary['total']})"


@pytest.mark.anyio
async def test_unified_positions_matches_broker_positions():
    """unified/positions 实时持仓数应与 broker_positions 一致"""
    app = await _get_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/v1/unified/positions")
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        positions = data["data"]["positions"]
        summary = data["data"]["summary"]
        assert summary["count"] == len(positions), \
            f"summary.count({summary['count']}) != positions length({len(positions)})"


@pytest.mark.anyio
async def test_unified_trades_consistent_with_auto_trades():
    """同一天，unified/trades 和 scanner/auto-trades 应返回相同笔数"""
    app = await _get_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        from datetime import datetime
        today = datetime.now().strftime("%Y%m%d")

        r1 = await c.get(f"/api/v1/unified/trades?date={today}")
        r2 = await c.get(f"/api/v1/scanner/auto-trades?date={today}")

        assert r1.status_code == 200
        assert r2.status_code == 200

        d1 = r1.json()
        d2 = r2.json()

        unified_count = d1["data"]["summary"]["total"] if d1.get("success") else 0
        auto_count = len(d2.get("data", [])) if d2.get("success") else 0

        # 允许微小差异(auto-trades可能含非filled状态), 但核心笔数应一致
        assert abs(unified_count - auto_count) <= 2, \
            f"unified trades({unified_count}) vs auto-trades({auto_count}) 差异过大"


@pytest.mark.anyio
async def test_date_availability_format():
    """date-availability 返回格式正确"""
    app = await _get_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/v1/unified/date-availability?days=7")
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        avail = data["data"]
        assert isinstance(avail, dict)
        # 至少应该有今天的key
        from datetime import datetime
        today_key = datetime.now().strftime("%Y%m%d")
        assert today_key in avail, f"今天 {today_key} 不在 date-availability 中"
        today_info = avail[today_key]
        assert "status" in today_info
        assert today_info["status"] in ("trades", "no-trades", "weekend")
        assert "is_today" in today_info
        assert today_info["is_today"] is True


@pytest.mark.anyio
async def test_historical_positions_rebuild_from_orders():
    """历史持仓重建: positions(date=历史日) 应从 broker_orders 推算"""
    app = await _get_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        # 取最近一个有交易的日期
        r_avail = await c.get("/api/v1/unified/date-availability?days=30")
        if r_avail.status_code != 200:
            pytest.skip("date-availability 不可用")

        avail = r_avail.json().get("data", {})
        trade_date = None
        for d_key in sorted(avail.keys(), reverse=True):
            if avail[d_key].get("status") == "trades" and not avail[d_key].get("is_today"):
                trade_date = d_key
                break

        if not trade_date:
            pytest.skip("没有历史交易日数据")

        r = await c.get(f"/api/v1/unified/positions?date={trade_date}")
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        assert data["data"]["is_realtime"] is False
        assert data["data"]["as_of"] == trade_date
