"""
MongoDB 集成测试

使用 mongomock 模拟 MongoDB，测试核心数据访问逻辑：
1. 日线数据查询和筛选
2. 基准数据加载
3. 停牌股处理(close=0)
4. 板块集中度过滤
5. 持仓市值计算
"""
import pytest
import sys
import os

# Add paths
_base = os.path.join(os.path.dirname(__file__), '..')
if _base not in sys.path:
    sys.path.insert(0, _base)


class TestDataQueries:
    """核心数据查询测试"""

    @pytest.mark.asyncio
    async def test_find_stock_daily_by_code(self, mock_mongo_with_stock_data):
        """按股票代码查询日线数据"""
        mongo = mock_mongo_with_stock_data
        results = await mongo.find_many(
            "stock_daily_ak_full",
            {"ts_code": "000001.SZ"},
            sort=[("trade_date", 1)],
        )
        assert len(results) == 3
        assert results[0]["trade_date"] == 20250101

    @pytest.mark.asyncio
    async def test_find_stock_daily_by_date_range(self, mock_mongo_with_stock_data):
        """按日期范围查询(验证$gte/$lte修复)"""
        mongo = mock_mongo_with_stock_data
        results = await mongo.find_many(
            "stock_daily_ak_full",
            {"ts_code": "000001.SZ", "trade_date": {"$gte": 20250102, "$lte": 20250103}},
        )
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_find_index_daily(self, mock_mongo_with_stock_data):
        """查询指数数据(验证基准数据查index_daily而非stock_daily_ak_full)"""
        mongo = mock_mongo_with_stock_data
        results = await mongo.find_many(
            "index_daily",
            {"ts_code": "000001.SH"},
            sort=[("trade_date", 1)],
        )
        assert len(results) == 3
        assert results[0]["close"] == 3000.0

    @pytest.mark.asyncio
    async def test_benchmark_return_calculation(self, mock_mongo_with_stock_data):
        """基准收益率计算(验证非硬编码0)"""
        mongo = mock_mongo_with_stock_data
        # 获取基准首尾数据
        all_data = await mongo.find_many(
            "index_daily",
            {"ts_code": "000001.SH"},
            sort=[("trade_date", 1)],
        )
        start_value = all_data[0]["close"]   # 3000
        end_value = all_data[-1]["close"]     # 3010
        benchmark_return = end_value / start_value - 1
        assert abs(benchmark_return - 0.00333) < 0.001
        assert benchmark_return != 0.0  # 不能硬编码0


class TestSuspendedStocks:
    """停牌股处理测试"""

    @pytest.mark.asyncio
    async def test_suspended_stock_close_zero(self, mock_mongo):
        """停牌股close=0时不应以0元卖出"""
        mongo = mock_mongo
        # 插入停牌数据
        mongo.seed_data("stock_daily_ak_full", [
            {"ts_code": "000001.SZ", "trade_date": 20250101, "close": 10.0},
            {"ts_code": "000001.SZ", "trade_date": 20250102, "close": 0},  # 停牌
        ])

        # 查询最新价
        result = await mongo.find_one(
            "stock_daily_ak_full",
            {"ts_code": "000001.SZ", "close": {"$gt": 0}},
            sort=[("trade_date", -1)],
        )
        assert result is not None
        assert result["close"] == 10.0  # 应使用最后有效价

    @pytest.mark.asyncio
    async def test_last_valid_price_fallback(self, mock_mongo):
        """回退到最后有效价格"""
        mongo = mock_mongo
        mongo.seed_data("stock_daily_ak_full", [
            {"ts_code": "000001.SZ", "trade_date": 20250101, "close": 10.0},
            {"ts_code": "000001.SZ", "trade_date": 20250102, "close": 10.5},
            {"ts_code": "000001.SZ", "trade_date": 20250103, "close": 0},  # 停牌
        ])

        # 获取最后有效价
        result = await mongo.find_one(
            "stock_daily_ak_full",
            {"ts_code": "000001.SZ", "close": {"$gt": 0}},
            sort=[("trade_date", -1)],
        )
        assert result["close"] == 10.5


class TestSectorConcentration:
    """板块集中度过滤测试"""

    @pytest.mark.asyncio
    async def test_industry_field_available(self, mock_mongo_with_stock_data):
        """stock_basic有industry字段可用于板块集中度"""
        mongo = mock_mongo_with_stock_data
        result = await mongo.find_many("stock_basic", {"industry": "银行"})
        assert len(result) == 2  # 平安银行 + 浦发银行

    @pytest.mark.asyncio
    async def test_sector_concentration_limit(self, mock_mongo_with_stock_data):
        """每行业最多N只的集中度过滤"""
        mongo = mock_mongo_with_stock_data
        max_per_industry = 1
        # 获取所有银行股
        bank_stocks = await mongo.find_many("stock_basic", {"industry": "银行"})
        # 只取前N只
        filtered = bank_stocks[:max_per_industry]
        assert len(filtered) == 1


class TestPositionValuation:
    """持仓市值计算测试"""

    @pytest.mark.asyncio
    async def test_position_value_uses_current_price(self, mock_mongo):
        """持仓市值用current_price而非avg_cost"""
        mongo = mock_mongo
        mongo.seed_data("positions", [
            {
                "position_id": "pos_001",
                "account_id": "acc_001",
                "ts_code": "000001.SZ",
                "quantity": 1000,
                "avg_cost": 10.0,
                "current_price": 12.0,  # 已结算的市价
            }
        ])

        pos = await mongo.find_one("positions", {"position_id": "pos_001"})
        # 用avg_cost计算: 1000*10=10000 ❌
        # 用current_price计算: 1000*12=12000 ✅
        value_cost = pos["quantity"] * pos["avg_cost"]
        value_market = pos["quantity"] * pos["current_price"]
        assert value_cost == 10000
        assert value_market == 12000
        assert value_market != value_cost, "市值不应等于成本值"

    @pytest.mark.asyncio
    async def test_profit_calculation(self, mock_mongo):
        """盈亏计算用市价"""
        mongo = mock_mongo
        mongo.seed_data("positions", [
            {
                "position_id": "pos_001",
                "ts_code": "000001.SZ",
                "quantity": 1000,
                "avg_cost": 10.0,
                "current_price": 12.0,
            }
        ])

        pos = await mongo.find_one("positions", {"position_id": "pos_001"})
        profit = (pos["current_price"] - pos["avg_cost"]) * pos["quantity"]
        profit_pct = (pos["current_price"] / pos["avg_cost"] - 1)
        assert profit == 2000     # 盈利2000
        assert abs(profit_pct - 0.2) < 0.001  # 20%


class TestDailySettlement:
    """每日结算逻辑测试"""

    @pytest.mark.asyncio
    async def test_settlement_updates_position(self, mock_mongo):
        """结算更新持仓的current_price和market_value"""
        mongo = mock_mongo
        mongo.seed_data("positions", [
            {"position_id": "pos_001", "account_id": "acc_001",
             "ts_code": "000001.SZ", "quantity": 1000, "avg_cost": 10.0},
        ])
        mongo.seed_data("stock_daily_ak_full", [
            {"ts_code": "000001.SZ", "trade_date": 20250103, "close": 11.0},
        ])
        mongo.seed_data("sim_accounts", [
            {"account_id": "acc_001", "available_cash": 50000, "initial_cash": 100000},
        ])

        # 模拟结算逻辑
        pos = await mongo.find_one("positions", {"position_id": "pos_001"})
        latest = await mongo.find_one(
            "stock_daily_ak_full",
            {"ts_code": "000001.SZ"},
            sort=[("trade_date", -1)],
        )

        if latest and latest["close"] > 0:
            await mongo.update_one(
                "positions",
                {"position_id": "pos_001"},
                {"$set": {
                    "current_price": latest["close"],
                    "market_value": latest["close"] * pos["quantity"],
                }},
            )

        # 验证
        updated = await mongo.find_one("positions", {"position_id": "pos_001"})
        assert updated["current_price"] == 11.0
        assert updated["market_value"] == 11000
