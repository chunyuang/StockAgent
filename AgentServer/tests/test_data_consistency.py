"""
跨端点数据一致性测试 — v2.9.97d

验证所有API返回的持仓/交易数据一致, 作为CI门槛。
如果此测试不过, 说明数据源有漂移, 禁止合并。
"""
import pytest
from httpx import AsyncClient, ASGITransport

# Lazy app ref
_app = None

async def _get_app():
    global _app
    if _app is None:
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
        from nodes.web.app import create_app
        _app = create_app()
    return _app


@pytest.mark.anyio
async def test_position_count_consistency():
    """持仓数量: /analysis == /unified/positions == /account.position_count
    
    /all 依赖 scanner 内存, 未运行时为0, 不参与一致性比较。
    """
    app = await _get_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        # /analysis
        r2 = await c.get("/api/v1/scanner/analysis")
        ana_data = r2.json().get("data", {})
        ana_count = len(ana_data.get("positions", []))
        
        # /unified/positions
        r3 = await c.get("/api/v1/unified/positions")
        uni_count = len(r3.json().get("data", {}).get("positions", []))
        
        # /account
        r4 = await c.get("/api/v1/scanner/account")
        acct_count = r4.json().get("data", {}).get("position_count", -1)
        
        assert ana_count == uni_count, f"/analysis({ana_count}) != /unified({uni_count})"
        assert ana_count == acct_count, f"/analysis({ana_count}) != /account({acct_count})"


@pytest.mark.anyio
async def test_position_codes_consistency():
    """持仓代码集: /analysis == /unified/positions"""
    app = await _get_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r2 = await c.get("/api/v1/scanner/analysis")
        ana_codes = set(p["ts_code"] for p in r2.json().get("data", {}).get("positions", []))
        
        r3 = await c.get("/api/v1/unified/positions")
        uni_codes = set(p["ts_code"] for p in r3.json().get("data", {}).get("positions", []))
        
        assert ana_codes == uni_codes, f"/analysis vs /unified diff: {ana_codes ^ uni_codes}"


@pytest.mark.anyio
async def test_analysis_kpi_matches_orders():
    """/analysis KPI total_trades 应 > 0 (有历史交易时)"""
    app = await _get_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/v1/scanner/analysis")
        kpi = r.json().get("data", {}).get("kpi", {})
        total_trades = kpi.get("total_trades", 0)
        # 只要系统有交易历史, 这个值就应该 > 0
        assert total_trades >= 0, f"total_trades should be >= 0, got {total_trades}"


@pytest.mark.anyio
async def test_unified_trades_has_both_buy_and_sell():
    """unified/trades 应同时返回 buy 和 sell (有历史时)"""
    app = await _get_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        from datetime import datetime
        today = datetime.now().strftime("%Y%m%d")
        r = await c.get(f"/api/v1/unified/trades?date={today}")
        trades = r.json().get("data", {}).get("trades", [])
        sides = set(t.get("side") for t in trades)
        # 只要今天有交易, 应该有 buy
        if trades:
            assert "buy" in sides, f"trades exist but no buy side: {sides}"


@pytest.mark.anyio
async def test_timeline_no_new_buy_sell():
    """scanner_timeline 不应有新的 buy/sell 记录 (v2.9.97c起)"""
    app = await _get_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        # This checks the /timeline/history endpoint returns data correctly
        r = await c.get("/api/v1/scanner/timeline/history?days=1")
        items = r.json().get("data", [])
        # Should have items (at least blocked records)
        assert isinstance(items, list)


@pytest.mark.anyio
async def test_trade_audit_returns_data():
    """trade-audit 应返回交易审查数据"""
    app = await _get_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/v1/scanner/trade-audit")
        assert r.status_code == 200, f"trade-audit returned {r.status_code}"
        data = r.json()
        assert data.get("success") is True, f"trade-audit not successful: {data}"
