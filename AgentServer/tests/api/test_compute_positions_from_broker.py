"""
Unit tests for _compute_positions_from_broker (v2.9.93b)

测试持仓计算函数从 broker_positions 读取数据的正确性:
- 空持仓 → 返回 []
- 单只持仓 → 返回正确字段
- qty=0 / total_qty=None → 跳过
- 跌破止损 → status=broken
- 接近止损 → status=near
- 安全 → status=safe
"""
import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# 加 AgentServer 到 path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))


class FakeAsyncCursor:
    """模拟 motor 的 async cursor: async for ..."""
    def __init__(self, docs):
        self._docs = list(docs)

    def __aiter__(self):
        self._iter = iter(self._docs)
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration


def make_fake_db(positions: list, latest_close: float = None) -> MagicMock:
    """构造一个 fake mongo db 对象，支持 broker_positions.find + stock_daily_ak_full.find_one"""
    db = MagicMock()

    # broker_positions.find(...) → 返回 async cursor
    bp = MagicMock()
    bp.find = MagicMock(return_value=FakeAsyncCursor(positions))

    # stock_daily_ak_full.find_one → AsyncMock
    sk = MagicMock()
    if latest_close is not None:
        sk.find_one = AsyncMock(return_value={"close": latest_close})
    else:
        sk.find_one = AsyncMock(return_value=None)

    def getitem(name):
        return {
            "broker_positions": bp,
            "stock_daily_ak_full": sk,
        }.get(name, MagicMock())

    db.__getitem__.side_effect = getitem
    return db


@pytest.mark.asyncio
async def test_empty_positions_returns_empty_list() -> None:
    """无持仓 → []"""
    from nodes.web.api.scanner_analysis import _compute_positions_from_broker
    db = make_fake_db([])
    result = await _compute_positions_from_broker(db)
    assert result == []


@pytest.mark.asyncio
async def test_single_position_basic_fields() -> None:
    """单只持仓 → 返回所有必填字段"""
    from nodes.web.api.scanner_analysis import _compute_positions_from_broker
    db = make_fake_db(
        [{
            "ts_code": "000001.SZ",
            "stock_name": "平安银行",
            "total_qty": 1000,
            "avg_cost": 10.0,
            "strategy": "halfway_chase",
        }],
        latest_close=10.5,
    )
    result = await _compute_positions_from_broker(db)
    assert len(result) == 1
    p = result[0]
    assert p["ts_code"] == "000001.SZ"
    assert p["stock_name"] == "平安银行"
    assert p["shares"] == 1000
    assert p["cost_price"] == 10.0
    assert p["current_price"] == 10.5
    assert p["profit_pct"] == 5.0
    assert p["market_value"] == 10500
    # 必填字段都有
    for key in [
        "stop_loss_price", "stop_loss_pct", "take_profit_price",
        "stop_loss_status", "stop_loss_desc",
        "risk_monitor_active", "risk_monitor_desc",
    ]:
        assert key in p, f"缺字段 {key}"


@pytest.mark.asyncio
async def test_zero_qty_skipped() -> None:
    """qty=0 应被跳过"""
    from nodes.web.api.scanner_analysis import _compute_positions_from_broker
    db = make_fake_db(
        [{"ts_code": "000001.SZ", "total_qty": 0, "avg_cost": 10.0}],
        latest_close=10.5,
    )
    result = await _compute_positions_from_broker(db)
    assert result == []


@pytest.mark.asyncio
async def test_no_qty_field_skipped() -> None:
    """total_qty/quantity 都缺 → 跳过"""
    from nodes.web.api.scanner_analysis import _compute_positions_from_broker
    db = make_fake_db(
        [{"ts_code": "000001.SZ", "avg_cost": 10.0}],
        latest_close=10.5,
    )
    result = await _compute_positions_from_broker(db)
    assert result == []


@pytest.mark.asyncio
async def test_quantity_field_used_as_fallback() -> None:
    """没有 total_qty 时用 quantity"""
    from nodes.web.api.scanner_analysis import _compute_positions_from_broker
    db = make_fake_db(
        [{
            "ts_code": "000001.SZ",
            "stock_name": "test",
            "quantity": 500,  # 用 quantity 而非 total_qty
            "avg_cost": 8.0,
        }],
        latest_close=8.0,
    )
    result = await _compute_positions_from_broker(db)
    assert len(result) == 1
    assert result[0]["shares"] == 500


@pytest.mark.asyncio
async def test_stop_loss_status_broken() -> None:
    """跌破止损 → broken"""
    from nodes.web.api.scanner_analysis import _compute_positions_from_broker
    # 假设默认止损 3%, 成本 10 → 止损价 9.7
    # 当前价 9.5 < 9.7 → broken
    db = make_fake_db(
        [{
            "ts_code": "000001.SZ",
            "stock_name": "t",
            "total_qty": 100,
            "avg_cost": 10.0,
            "strategy": "halfway_chase",
        }],
        latest_close=9.0,  # 跌 10%, 一定破止损
    )
    result = await _compute_positions_from_broker(db)
    assert len(result) == 1
    assert result[0]["stop_loss_status"] == "broken"
    assert "已跌破止损" in result[0]["stop_loss_desc"]


@pytest.mark.asyncio
async def test_stop_loss_status_safe_when_profit() -> None:
    """盈利状态 → safe"""
    from nodes.web.api.scanner_analysis import _compute_positions_from_broker
    db = make_fake_db(
        [{
            "ts_code": "000001.SZ",
            "stock_name": "t",
            "total_qty": 100,
            "avg_cost": 10.0,
            "strategy": "halfway_chase",
        }],
        latest_close=12.0,  # +20%, 安全
    )
    result = await _compute_positions_from_broker(db)
    assert len(result) == 1
    assert result[0]["stop_loss_status"] == "safe"


@pytest.mark.asyncio
async def test_no_dependency_on_scanner_timeline() -> None:
    """【P0回归】函数不应该读 scanner_timeline (避免被污染数据影响)"""
    from nodes.web.api.scanner_analysis import _compute_positions_from_broker
    db = make_fake_db([])

    # 给 scanner_timeline 设一个会抛错的 mock，验证函数根本不会去碰它
    db.__getitem__.side_effect = lambda name: (
        MagicMock(find=MagicMock(return_value=FakeAsyncCursor([])))
        if name == "broker_positions"
        else MagicMock(find_one=AsyncMock(return_value=None))
        if name == "stock_daily_ak_full"
        else (_ for _ in ()).throw(AssertionError(f"不应访问集合 {name}"))
    )

    result = await _compute_positions_from_broker(db)
    assert result == []
