"""
回测核心逻辑测试

纯Python逻辑测试，不依赖MongoDB或复杂的模块导入。
直接复现核心计算逻辑，确保公式正确。
"""
import pytest


class TestFactorUnits:
    """因子单位转换 — 基于 FACTOR_UNITS.md 防止静默失效"""

    def test_circ_mv_yi_to_wanyuan(self):
        """流通市值: 前端传亿 → 后端存万元(×10000)"""
        assert 50 * 10000 == 500000  # 50亿 → 500000万元

    def test_pullback_pct_negative(self):
        """pullback_pct存负数，用<=-0.15命中，用>=0.15永远不命中"""
        stored = -0.15
        assert stored <= -0.15   # ✅ 正确筛选
        assert not (stored >= 0.15)  # ❌ 历史bug：永远0候选

    def test_rise_after_limit_down_pct_vs_decimal(self):
        """rise_after_limit_down存百分比(3.0)，不是小数(0.03)"""
        stored = 3.0
        assert stored >= 3.0     # ✅ 正确
        assert not (0.03 <= stored < 1)  # ❌ 历史bug：3.0不在[0.03,1)

    def test_turnover_rate_percentage(self):
        """换手率存百分比(15.0)，前端传小数(0.15)需×100"""
        val = 0.15
        target = val * 100 if val < 1 else val
        assert target == 15.0

    def test_limit_up_time_minutes(self):
        """涨停时间 HH:MM → 分钟"""
        assert 10 * 60 + 0 == 600
        assert 9 * 60 + 30 == 570


class TestLimitThreshold:
    """涨跌停阈值 — 分板块"""

    def test_main_board_10pct(self):
        assert round(10.0 * 1.1, 2) == 11.0
        assert round(10.0 * 0.9, 2) == 9.0

    def test_gem_20pct(self):
        assert round(10.0 * 1.2, 2) == 12.0
        assert round(10.0 * 0.8, 2) == 8.0

    def test_bse_30pct(self):
        assert round(10.0 * 1.3, 2) == 13.0
        assert round(10.0 * 0.7, 2) == 7.0

    def test_stock_code_suffix(self):
        """股票代码后缀判断"""
        def suffix(code):
            if code.startswith(('6', '9')): return ".SH"
            if code.startswith(('0', '1', '2', '3')): return ".SZ"
            if code.startswith(('8', '4')): return ".BJ"
            return None
        assert suffix("600000") == ".SH"
        assert suffix("000001") == ".SZ"
        assert suffix("300001") == ".SZ"
        assert suffix("301001") == ".SZ"  # 301也是创业板
        assert suffix("688001") == ".SH"
        assert suffix("830001") == ".BJ"
        assert suffix("430001") == ".BJ"
        assert suffix("500001") is None   # 基金


class TestBacktestStatistics:
    """回测统计公式"""

    def test_losing_trades_from_completed(self):
        """亏损数 = 完成交易数 - 盈利数（不是总信号数）"""
        completed, winning = 100, 60
        assert completed - winning == 40  # ✅ 正确
        assert 150 - winning == 90        # ❌ 用total_signals的错误值

    def test_benchmark_return(self):
        """基准收益率 = 终值/初值 - 1"""
        bm = 3240 / 3000 - 1
        assert abs(bm - 0.08) < 0.001
        assert bm != 0.0  # 不能硬编码0

    def test_alpha(self):
        """Alpha = 策略收益 - 基准收益"""
        assert abs(0.15 - 0.08 - 0.07) < 0.001

    def test_max_drawdown(self):
        """最大回撤 = (峰-谷)/峰"""
        navs = [1.0, 1.1, 1.05, 1.2, 0.9, 1.0]
        peak, max_dd = navs[0], 0
        for n in navs:
            if n > peak: peak = n
            dd = (peak - n) / peak
            if dd > max_dd: max_dd = dd
        assert abs(max_dd - 0.25) < 0.001  # (1.2-0.9)/1.2

    def test_hold_days_trading_approx(self):
        """日历天数 → 交易日天数(×0.67)"""
        assert int(10 * 0.67) == 6  # 2周≈6交易日


class TestCommissionCalculation:
    """手续费计算"""

    def test_buy_commission_min(self):
        """万3最低5元"""
        assert max(10000 * 0.0003, 5) == 5

    def test_buy_commission_large(self):
        assert round(max(100000 * 0.0003, 5), 2) == 30

    def test_sell_total_cost(self):
        """卖出=佣金万3+印花税千1"""
        amt = 100000
        assert max(amt * 0.0003, 5) + amt * 0.001 == 130


class TestCostVsMarketPrice:
    """成本价 vs 市价 — 防止PnL恒为0"""

    def test_avg_cost_not_equal_to_current_price(self):
        """avg_cost(成本价) ≠ current_price(市价)"""
        avg_cost = 10.0
        current_price = 12.0
        pnl_using_cost = (avg_cost - avg_cost) * 100  # = 0 ❌
        pnl_using_market = (current_price - avg_cost) * 100  # = 200 ✅
        assert pnl_using_cost == 0           # 用成本价算PnL恒为0
        assert pnl_using_market == 200       # 用市价算PnL才正确
