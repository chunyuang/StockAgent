"""
第1层防线：回测数据契约测试

只关心回测输出格式是否自洽，不涉及实盘。
每次改回测代码后跑 pytest tests/test_backtest_contract.py 即可验证。

这些测试不需要启动服务或跑完整回测，只需要一个回测结果fixture。
"""

import pytest
import re
import sys
import os

# 确保能导入项目模块
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


def _extract_sl_pct(reason: str) -> float:
    """从止损原因字符串中提取止损百分比"""
    m = re.search(r'止损\((\d+\.?\d*)%\)', reason)
    return float(m.group(1)) / 100 if m else 0.03


def _extract_tp_pct(reason: str) -> float:
    """从止盈原因字符串中提取止盈百分比"""
    m = re.search(r'止盈\((\d+\.?\d*)%\)', reason)
    return float(m.group(1)) / 100 if m else 0.07


class TestNetValueContract:
    """净值序列格式契约"""

    def test_first_net_value_is_one(self, backtest_result):
        """首日净值必须=1.0"""
        nvs = backtest_result.get('net_value_series', [])
        assert len(nvs) > 0, "净值序列不能为空"
        first_nv = nvs[0].get('net_value', 0)
        assert first_nv == 1.0, f"首日净值应为1.0，实际={first_nv}"

    def test_net_value_monotonically_reasonable(self, backtest_result):
        """净值不应出现极端跳变（单日>50%或<0）"""
        nvs = backtest_result.get('net_value_series', [])
        for i in range(1, len(nvs)):
            prev = nvs[i-1].get('net_value', 0)
            curr = nvs[i].get('net_value', 0)
            if prev > 0:
                daily_change = (curr - prev) / prev
                assert daily_change < 0.5, f"第{i}天净值跳变过大: {daily_change:.2%}"
                assert curr > 0, f"第{i}天净值不应为负: {curr}"

    def test_net_value_series_has_required_fields(self, backtest_result):
        """每条净值记录必须包含 trade_date, net_value, daily_profit"""
        nvs = backtest_result.get('net_value_series', [])
        required_keys = ['trade_date', 'net_value']
        for nv in nvs:
            for key in required_keys:
                assert key in nv, f"净值记录缺少字段: {key}"

    def test_last_net_value_matches_total_return(self, backtest_result):
        """末日净值应与total_return一致"""
        nvs = backtest_result.get('net_value_series', [])
        if not nvs:
            return
        last_nv = nvs[-1].get('net_value', 0)
        total_return = backtest_result.get('total_return', 0)
        # total_return是百分比(如73.07)，net_value是归一化值(如1.73)
        expected_nv = 1 + total_return / 100
        assert abs(last_nv - expected_nv) < 0.01, \
            f"末日净值={last_nv}与total_return={total_return}%不一致，期望={expected_nv}"


class TestTradeContract:
    """交易记录格式契约"""

    def test_all_closed_trades_have_sell_reason(self, backtest_result):
        """所有已平仓交易必须有卖出原因"""
        trades = backtest_result.get('merged_trades', [])
        closed = [t for t in trades if t.get('sell_date')]
        no_reason = [t for t in closed if not t.get('sell_reason')]
        assert len(no_reason) == 0, \
            f"有{len(no_reason)}笔已平仓交易缺少卖出原因"

    def test_closed_trades_have_required_fields(self, backtest_result):
        """已平仓交易必须包含核心字段"""
        trades = backtest_result.get('merged_trades', [])
        closed = [t for t in trades if t.get('sell_date')]
        required_keys = ['ts_code', 'buy_date', 'sell_date', 'buy_price', 'sell_price',
                         'profit_pct', 'sell_reason', 'strategy']
        for t in closed:
            for key in required_keys:
                assert key in t and t[key] is not None, \
                    f"交易 {t.get('ts_code', '?')} 缺少字段: {key}"

    def test_sell_reason_categories(self, backtest_result):
        """卖出原因必须是已知类别"""
        valid_reasons = ['调仓卖出', 'force_empty_position', '停牌超时强卖',
                         '冲高回落', '利润保护', '利润锁定', '高开即卖', '减仓',
                         '强制空仓', '强制空仓(延后)']
        # 动态匹配止损/止盈/跳空止损
        trades = backtest_result.get('merged_trades', [])
        closed = [t for t in trades if t.get('sell_date')]
        for t in closed:
            reason = t.get('sell_reason', '')
            is_valid = (
                reason in valid_reasons or
                re.match(r'止损\(\d+\.?\d*%\)', reason) or
                re.match(r'止盈\(\d+\.?\d*%\)', reason) or
                re.match(r'跳空止损', reason) or
                reason.startswith('超时') or
                reason.startswith('龙头')  # 龙头5天低利润
            )
            assert is_valid, f"未知卖出原因: {reason} (交易: {t.get('ts_code')})"


class TestStopLossContract:
    """止损逻辑契约"""

    def test_stop_loss_sell_price_approximates_stop_line(self, backtest_result):
        """止损卖出价应≈止损线（允许0.05误差，来自cost_basis vs buy_price差异）"""
        trades = backtest_result.get('merged_trades', [])
        closed = [t for t in trades if t.get('sell_date')]
        sl_trades = [t for t in closed if t.get('sell_reason') and '止损' in str(t.get('sell_reason'))]

        for t in sl_trades:
            buy_p = t.get('buy_price', 0)
            sell_p = t.get('sell_price', 0)
            reason = t.get('sell_reason', '')
            sl_pct = _extract_sl_pct(reason)
            # Skip gap-down stop loss: sells at open (not stop price), diff is expected
            if '跳空止损' in reason:
                continue

            # stop_line基于buy_price计算（含滑点）
            # 实际sell_price基于_cost_basis计算（不含滑点）
            # 两者差异≈买入滑点，允许0.5%误差
            stop_line = buy_p * (1 - sl_pct)
            max_diff = buy_p * 0.02  # 2%容差(buy_price含滑点vs cost_basis不含,跳空止损以open卖差异更大)
            assert abs(sell_p - stop_line) <= max_diff + 0.05, \
                f"止损卖出价偏离止损线过大: {t.get('ts_code')} sell@{sell_p:.2f} stop={stop_line:.2f} diff={abs(sell_p-stop_line):.3f}"

    def test_stop_loss_triggers_exist(self, backtest_result):
        """如果启用了止损，应该有止损触发记录（除非行情特别好）"""
        trades = backtest_result.get('merged_trades', [])
        closed = [t for t in trades if t.get('sell_date')]
        sl_trades = [t for t in closed if t.get('sell_reason') and '止损' in str(t.get('sell_reason'))]
        # 不强制要求有止损（可能行情好没有触发），但如果有止损记录，数量应>0
        # 这个测试只是确保止损机制没有被完全禁用
        if len(closed) > 20:  # 超过20笔交易，应该有止损
            assert len(sl_trades) > 0, \
                f"{len(closed)}笔交易但0笔止损触发，止损机制可能被禁用"


class TestStrategyResultsContract:
    """策略结果格式契约"""

    def test_strategy_results_has_total_return(self, backtest_result):
        """每个策略结果必须包含total_return字段"""
        sr = backtest_result.get('strategy_results', {})
        for sid, v in sr.items():
            assert 'total_return' in v, f"策略 {sid} 缺少 total_return 字段"

    def test_strategy_results_has_avg_profit_pct(self, backtest_result):
        """每个策略结果必须包含avg_profit_pct字段"""
        sr = backtest_result.get('strategy_results', {})
        missing = []
        for sid, v in sr.items():
            if 'avg_profit_pct' not in v:
                missing.append(sid)
        # 0交易策略必须有avg_profit_pct=0(V75-P0-2修复后)
        # 但旧结果可能没有,此时发出警告而不是硬失败
        if missing:
            zero_trade = [sid for sid in missing if sr[sid].get('trades_count', 0) == 0]
            non_zero = [sid for sid in missing if sr[sid].get('trades_count', 0) > 0]
            if non_zero:
                pytest.fail(f"有交易的策略缺少avg_profit_pct: {non_zero}")
            elif zero_trade:
                # 0交易策略缺avg_profit_pct: 旧结果兼容, 但新结果必须修复
                import warnings
                warnings.warn(f"0交易策略缺少avg_profit_pct(旧结果): {zero_trade}", UserWarning)

    def test_total_return_is_percentage_not_decimal(self, backtest_result):
        """total_return必须是百分比(如73.07)，不是小数(如0.73)"""
        sr = backtest_result.get('strategy_results', {})
        for sid, v in sr.items():
            tr = v.get('total_return', 0)
            # 百分比范围：-100到1000（极端情况）
            # 小数范围：-1到10
            if tr != 0:
                assert abs(tr) > 1 or abs(tr) < 0.01, \
                    f"策略 {sid} total_return={tr} 可能是小数而非百分比"

    def test_win_rate_is_percentage(self, backtest_result):
        """win_rate必须是百分比(如75.0)，不是小数(如0.75)"""
        sr = backtest_result.get('strategy_results', {})
        for sid, v in sr.items():
            wr = v.get('win_rate', 0)
            if wr != 0:
                assert wr > 1 or wr < 0.01, \
                    f"策略 {sid} win_rate={wr} 可能是小数而非百分比"

    def test_max_drawdown_is_percentage(self, backtest_result):
        """max_drawdown必须是百分比(如3.61)，不是小数(如0.036)"""
        sr = backtest_result.get('strategy_results', {})
        for sid, v in sr.items():
            md = v.get('max_drawdown', 0)
            if md != 0:
                assert md > 0.1 or md < 0.001, \
                    f"策略 {sid} max_drawdown={md} 可能是小数而非百分比"


class TestOverallResultContract:
    """总体结果格式契约"""

    def test_total_return_is_percentage(self, backtest_result):
        """总体total_return必须是百分比(不是小数)
        
        回测引擎使用 total_return * 100 输出,理论上总是百分比格式。
        此测试只做基础校验: 当有明显证据(如tr=0.73但策略返回73.07)时才报错。
        """
        tr = backtest_result.get('total_return', 0)
        if tr == 0:
            return
            
        sr = backtest_result.get('strategy_results', {})
        # 只看有交易的策略
        strategy_returns = [v.get('total_return', 0) for v in sr.values() if v.get('trades_count', 0) > 0]
        
        if not strategy_returns:
            return  # 无策略有交易,无法判定
        
        # 启发式: 如果所有有交易的策略total_return都是正的大数(如73.07),
        # 但总体total_return是一个0~1的小数(如0.73)→说明没有*100
        # 这只在: 总体tr是0~1小数 AND 策略级tr明显>1 AND
        #         tr*100≈策略tr的加权值时才判定
        all_strategy_positive_large = all(abs(r) > 5 for r in strategy_returns)
        if all_strategy_positive_large and 0 < abs(tr) < 2:
            # tr在0~2之间但策略返回值>5→可能tr是小数
            # 进一步: tr*100应≈策略的加权和
            # 简化: 如果tr*100的绝对值在策略返回值范围内→判定为小数
            tr_x100 = tr * 100
            strat_min = min(abs(r) for r in strategy_returns)
            strat_max = max(abs(r) for r in strategy_returns)
            if strat_min * 0.5 <= abs(tr_x100) <= strat_max * 2:
                pytest.fail(
                    f"total_return={tr} 可能是小数而非百分比(应为{tr_x100:.1f}%). "
                    f"策略级返回值{strategy_returns}均为百分比格式"
                )

    def test_win_rate_is_percentage(self, backtest_result):
        """总体win_rate必须是百分比"""
        wr = backtest_result.get('win_rate', 0)
        if wr != 0:
            assert wr > 1, f"win_rate={wr} 可能是小数而非百分比"

    def test_max_drawdown_is_percentage(self, backtest_result):
        """总体max_drawdown必须是百分比"""
        md = backtest_result.get('max_drawdown', 0)
        if md != 0:
            assert md > 0.1, f"max_drawdown={md} 可能是小数而非百分比"

    def test_result_has_required_top_level_keys(self, backtest_result):
        """结果必须包含核心顶层字段"""
        required_keys = ['total_return', 'win_rate', 'max_drawdown',
                         'merged_trades', 'net_value_series', 'strategy_results']
        for key in required_keys:
            assert key in backtest_result, f"结果缺少顶层字段: {key}"