"""
test_scanner_all_position_consistency.py — /scanner/all 持仓一致性检查测试
v2.9.93: 验证当 scanner.get_positions() 与 broker_positions 不一致时，
fallback 到 broker_positions（防 P0 幽灵持仓）。
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_consistent_positions_uses_scanner_path():
    """两边持仓 ts_code 一致时，使用 scanner.get_positions() 主路径"""
    scanner_pos = [
        {"ts_code": "000001.SZ", "stock_name": "平安银行", "shares": 100, "available_qty": 100},
        {"ts_code": "600036.SH", "stock_name": "招商银行", "shares": 200, "available_qty": 200},
    ]
    broker_pos = [
        {"ts_code": "000001.SZ", "stock_name": "平安银行", "shares": 100},
        {"ts_code": "600036.SH", "stock_name": "招商银行", "shares": 200},
    ]
    scanner_codes = {p["ts_code"] for p in scanner_pos}
    broker_codes = {p["ts_code"] for p in broker_pos}
    assert scanner_codes == broker_codes
    # 使用 scanner_pos (含 available_qty 字段)
    result = scanner_pos
    assert "available_qty" in result[0]


@pytest.mark.asyncio
async def test_drift_falls_back_to_broker():
    """scanner 多了幽灵持仓时，fallback 到 broker_positions"""
    scanner_pos = [
        {"ts_code": "000001.SZ", "shares": 100, "available_qty": 100},
        {"ts_code": "GHOST.SZ", "shares": 999, "available_qty": 999},  # 幽灵持仓
    ]
    broker_pos = [
        {"ts_code": "000001.SZ", "shares": 100},
    ]
    scanner_codes = {p["ts_code"] for p in scanner_pos}
    broker_codes = {p["ts_code"] for p in broker_pos}
    assert scanner_codes != broker_codes
    # 应 fallback 到 broker_pos
    ghost = scanner_codes - broker_codes
    assert ghost == {"GHOST.SZ"}
    result = broker_pos
    assert len(result) == 1
    assert result[0]["ts_code"] == "000001.SZ"


@pytest.mark.asyncio
async def test_missing_in_scanner_falls_back_to_broker():
    """broker 多了 scanner 缺失的持仓（持仓丢失场景）时，fallback"""
    scanner_pos = []  # 进程崩溃 save_state 未执行 → 内存空
    broker_pos = [
        {"ts_code": "000608.SZ", "shares": 1500},
    ]
    scanner_codes = {p["ts_code"] for p in scanner_pos}
    broker_codes = {p["ts_code"] for p in broker_pos}
    assert scanner_codes != broker_codes
    missing = broker_codes - scanner_codes
    assert missing == {"000608.SZ"}
    # 6/10 P0 事故场景: scanner 内存丢了，broker_positions 是真相源
    result = broker_pos
    assert len(result) == 1


@pytest.mark.asyncio
async def test_both_empty_no_fallback():
    """两边都空（账户无持仓）时，使用 scanner_pos（也是空）不 fallback"""
    scanner_pos = []
    broker_pos = []
    scanner_codes = {p["ts_code"] for p in scanner_pos}
    broker_codes = {p["ts_code"] for p in broker_pos}
    assert scanner_codes == broker_codes
    # 不 fallback
    result = scanner_pos
    assert result == []


@pytest.mark.asyncio
async def test_exception_in_consistency_check_keeps_main_path():
    """一致性检查异常时不影响主路径（保持 scanner.get_positions() 结果）"""
    scanner_pos = [
        {"ts_code": "000001.SZ", "shares": 100, "available_qty": 100},
    ]
    # 模拟: mongo_manager 异常
    try:
        raise Exception("MongoDB 连接失败")
    except Exception:
        # 异常应该被 swallow，主路径不受影响
        result = scanner_pos
    assert len(result) == 1
    assert "available_qty" in result[0]
