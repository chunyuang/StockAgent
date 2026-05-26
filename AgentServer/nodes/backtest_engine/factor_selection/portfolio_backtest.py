"""
组合回测引擎

【双模式架构设计说明】
═══════════════════════════════════════════════════════════════

▶️ 回测模式 (MODE=backtest)
   ┌─────────────────────────────────────────────────────────┐
   │  读取路径: MongoDB (stock_daily_ak_full) → 筛选 → 调仓 │
   │  性能: 极速 (无需计算因子,直接读取)                   │
   │  适用: 大规模历史回测、参数寻优、策略验证              │
   │  依赖: DATA_SYNC 节点预计算所有因子 (次日批量计算)    │
   └─────────────────────────────────────────────────────────┘

【回测模式说明】
  • 本文件专用于历史回测,不包含实盘交易逻辑
  • 所有数据基于已收盘的日线数据
  • 因子均为预计算,不依赖实时计算

【因子字段映射关系(两种模式输出完全一致)】
  • first_limit_up     → 首板标记 (0.0/1.0)
  • hot_sector         → 热点板块标记 (0.0/1.0)
  • limit_up_yesterday → 昨日涨停标记 (0.0/1.0)
  • turnover_rate      → 换手率 (float)
  • volume_ratio       → 量比 (float)
  • circ_mv            → 流通市值 (float)
  • ... 其他 40+ 个因子字段 ...

═══════════════════════════════════════════════════════════════

支持:
- 定期调仓
- 多种权重方法
- 交易成本
- 基准对比
- 绩效统计
"""

import gc
import math
import pandas as pd
from datetime import datetime as dt_now  # 【修复:避免局部from datetime import datetime导致UnboundLocalError】

from core.constants import C
from core.managers import mongo_manager, redis_manager
from core.utils.logger import logger
from .factor_quality_checker import FactorQualityChecker
from .models import RebalanceRecord

# 【修复:PerformanceAnalyzer已弃用(API不匹配),移除import避免ModuleNotFoundError】
# from real_trading.performance_analyzer import PerformanceAnalyzer

from .factor_engine import FactorEngine, log_memory_usage
from ..strategy_defaults import GLOBAL_RISK, STRATEGY_CONFIGS, merge_strategy_params
from .sell_signal_checker import SellSignalChecker, should_apply_slippage, get_buy_price_for_strategy, PositionManager, resolve_sell_price_and_reason
from .universe import ExcludeRule, UniverseManager, UniverseType
from .special_period_filter import get_special_period_filter


class PortfolioBacktester:
    """
    组合回测引擎

    支持:
    - 定期调仓 (日/周/月/季)
    - 多种权重方法 (等权/因子加权)
    - 交易成本 (佣金+印花税)
    - 基准对比
    """

    # 交易成本
    BUY_COMMISSION = 0.0003     # 买入佣金 万3(含规费),对齐前端commission_rate默认值
    SELL_COMMISSION = 0.0003   # 卖出佣金 万3(含规费),对齐前端commission_rate默认值
    STAMP_TAX = 0.001          # 印花税 千1 (卖出)
    MIN_COMMISSION = 5         # 最低佣金 5元

    # 【V33:回测-实盘一致性标志】
    # 当live_trading_mode=True时,T_close因子自动降级为T_prev,消除未来函数
    # 回测模式始终为False(使用完整因子),实盘模式始终为True(只使用可用因子)
    # 此标志通过strategy_defaults.GLOBAL_RISK["live_trading_mode"]单一来源控制
    LIVE_TRADING_MODE = GLOBAL_RISK.get("live_trading_mode", False)

    # 【P2-3修复:策略买入时间常量,避免硬编码重复】
    STRATEGY_BUY_TIMES = {
        '半路追涨': '10:00',
        '首板打板': '09:35',
        '涨停开板': '10:00',
        '龙头低吸': '14:00',
        '跌停翘板': '10:30',
    }

    # 【P1-5修复(第十一轮):强制空仓阈值提升为类常量,避免两处分别定义不一致】
    # 【P1-5修复】强制空仓阈值从strategy_defaults.py读取(单一来源)
    FORCE_EMPTY_LIMIT_DOWN = GLOBAL_RISK.get("force_empty_limit_down", 80)
    FORCE_EMPTY_LIMIT_UP = GLOBAL_RISK.get("force_empty_limit_up", 10)

    def __init__(self):
        # 🔒 优先初始化所有基础属性,避免构造过程中抛出异常导致属性缺失
        # 这非常重要!如果后续构造过程抛出异常,属性已经存在,不会导致 AttributeError
        # 所有可能用到的属性都在这里初始化,一个都不能少
        self.weight_method = "equal"
        self.universe_mgr = UniverseManager()
        self.factor_engine = FactorEngine()
        self._stock_name_cache: dict[str, str] = {}
        self._industry_map_cache: dict[str, str] = {}  # 【P1-3修复(V14)】板块映射缓存
        self._ma60_cache: dict[int, tuple] = {}  # 【P0-1修复(V20)】MA60缓存{trade_date: (ma60_value, current_close)}
        self._trade_date_index_map: dict[int, int] = {}  # 【V30:P1-1】交易日→索引映射，用于O(1)计算持仓天数
        # 初始资金(用于计算累计收益)
        self._initial_cash: float = 1000000.0
        # 🔧 _run_impl中使用的属性,提前初始化避免hasattr检查
        self._risk_config = {}
        self._slippage_pct = 0.002
        self._strategy_risk_params = {}
        self._strategy_params = {}
        self._cost_basis = {}
        self._cost_basis_date = {}
        self._last_valid_price = {}
        self._last_valid_price_date = {}  # 【V36:停牌股折价需要记录最后有效价格日期】
        self._prev_day_close = {}
        self._strategy_signal_stats = {}
        self.stock_to_strategy = {}

    def _calc_trade_days_held(self, buy_date, sell_date):
        """【V30:P1-1】O(1)计算持仓交易日数

        替代原来的O(N)遍历: sum(1 for d in _all_td if buy_dt_int < d <= trade_dt_int)
        预构建{trade_date: index}映射，持仓天数 = idx_sell - idx_buy

        Args:
            buy_date: 买入日期(int)
            sell_date: 卖出/当前日期(int)

        Returns:
            int: 持仓交易日数(不含买入日，含卖出日)
        """
        idx_map = self._trade_date_index_map
        idx_buy = idx_map.get(buy_date)
        idx_sell = idx_map.get(sell_date)
        if idx_buy is not None and idx_sell is not None:
            return idx_sell - idx_buy
        # fallback: O(N)遍历(映射未构建时)
        _all_td = getattr(self, '_all_trade_dates', [])
        if _all_td:
            return sum(1 for d in _all_td if buy_date < d <= sell_date)
        return 0

    def _check_early_sell_signals(self, code: str, strategies: list, cost: float,
                                         open_price: float, close_price: float) -> tuple:
        """早盘保护性卖出检查(冲高回落/利润保护/高开即卖)

        【V29重构】委托给SellSignalChecker,消除if/elif链和策略硬编码。
        新增策略只需在sell_signal_checker.py的STRATEGY_SELL_SIGNALS中注册,
        不需要修改此方法或添加elif分支。

        历史bug追踪:
        - V25: elif链导致利润保护被冲高回落elif吞掉 → 改为独立if
        - V23: 中文参数名fallback到0.05 → 改用next_day_open_sell_pct
        - V27: 龙头低吸缺少冲高回落/利润保护 → 已在STRATEGY_SELL_SIGNALS中注册
        - V28: 低开场景利润保护误触发 → check_profit_protect已加open_rise>=2%条件

        Args:
            code: 股票代码
            strategies: 策略名列表
            cost: 成本价
            open_price: 开盘价
            close_price: 收盘价

        Returns:
            (sell_price, sell_reason) or (0, '') if no signal
        """
        if not isinstance(strategies, list) or not strategies:
            return 0, ''
        if cost <= 0:
            return 0, ''

        # 【V29:委托给SellSignalChecker】
        # 延迟初始化checker(依赖_strategy_params和_strategy_risk_params)
        if not hasattr(self, '_sell_checker') or self._sell_checker is None:
            self._sell_checker = SellSignalChecker(
                self._strategy_params, self._strategy_risk_params,
                self._risk_config, self._slippage_pct)

        return self._sell_checker.check_early_sell(code, strategies, cost, open_price, close_price)

    def _check_intraday_profit_lock(self, cost: float, high_price: float, close_price: float, code: str = None) -> bool:
        """【V58优化:增加code参数,读取策略级利润锁定参数,与sell_signal_checker保持一致】
        
        检查逻辑: 盘中冲高≥min_high_rise 且 从高点回撤≥pullback_pct 且 收盘仍≥min_profit
        
        Args:
            cost: 成本价
            high_price: 盘中最高价
            close_price: 收盘价
            code: 股票代码(可选,用于读取策略级参数)
            
        Returns:
            True=触发利润锁定, False=不触发
        """
        if cost <= 0 or high_price <= 0 or close_price <= 0 or close_price >= high_price:
            return False
        high_rise = (high_price / cost - 1)
        close_rise = (close_price / cost - 1)
        # 【V58优化:尝试从策略级参数读取,fallbaack到risk_config再fallbaack到GLOBAL_RISK】
        lock_min_high = self._risk_config.get('intraday_lock_min_high_rise', GLOBAL_RISK.get('intraday_lock_min_high_rise', 0.04))
        lock_pullback = self._risk_config.get('intraday_lock_pullback_pct', GLOBAL_RISK.get('intraday_lock_pullback_pct', 0.015))
        lock_min_profit = self._risk_config.get('intraday_lock_min_profit', GLOBAL_RISK.get('intraday_lock_min_profit', 0.02))
        # 【V58-优化:如果有code,检查策略级STRATEGY_PULLBACK_PARAMS和INTRADAY_PROFIT_LOCK_SIGNALS参数】
        # sell_signal_checker.check_intraday_profit_lock会读策略级参数,这里也要保持一致
        if code and hasattr(self, 'stock_to_strategy'):
            _strategies = self.stock_to_strategy.get(code, [])
            if isinstance(_strategies, list) and _strategies:
                from nodes.backtest_engine.factor_selection.sell_signal_checker import STRATEGY_PULLBACK_PARAMS
                _merged_params = {}
                for sname in _strategies:
                    _sp = STRATEGY_PULLBACK_PARAMS.get(sname, {})
                    _srp = self._strategy_risk_params.get(sname, {})
                    _merged_params.update(_sp)
                    _merged_params.update(_srp)
                if 'intraday_lock_min_high_rise' in _merged_params:
                    lock_min_high = _merged_params['intraday_lock_min_high_rise']
                if 'intraday_lock_pullback_pct' in _merged_params:
                    lock_pullback = _merged_params['intraday_lock_pullback_pct']
                if 'intraday_lock_min_profit' in _merged_params:
                    lock_min_profit = _merged_params['intraday_lock_min_profit']
        if high_rise >= lock_min_high and close_price < high_price:
            intraday_pullback = (high_price - close_price) / high_price
            if intraday_pullback >= lock_pullback and close_rise >= lock_min_profit:
                return True
        return False

    async def _check_and_execute_forced_sells(self, trade_date, holdings, _sl_tp_prices,
                                                    forced_sell_codes, forced_sell_prices,
                                                    forced_sell_codes_set, check_timeout=True):
        """统一的止损止盈/冲高回落/超时检查+执行

        【V29重构】合并调仓日无交易和非调仓日的重复卖出逻辑。
        两处代码~150行几乎完全相同,现统一为一个方法。

        Args:
            trade_date: 交易日
            holdings: 当前持仓dict
            _sl_tp_prices: 价格数据dict
            forced_sell_codes: 已有强制卖出列表(可能已有其他原因)
            forced_sell_prices: 已有卖出价dict
            forced_sell_codes_set: 已有强制卖出set(去重)
            check_timeout: 是否检查超时强卖(调仓日无交易=是)

        Returns:
            (forced_sell_codes, forced_sell_prices, forced_sell_codes_set) 更新后
        """
        enable_sl = self._risk_config.get('enable_stop_loss', True)
        enable_tp = self._risk_config.get('enable_take_profit', True)

        for code in list(holdings.keys()):
            if holdings.get(code, 0) <= 0:
                continue
            # T+1: 当日买入不可止损/止盈卖出
            buy_dt = self._cost_basis_date.get(code)
            if buy_dt is not None and buy_dt == trade_date:
                continue
            p = _sl_tp_prices.get(code, {})
            cost = self._cost_basis.get(code, 0)
            if cost <= 0 or p.get('close', 0) <= 0:
                continue

            strategies = self.stock_to_strategy.get(code, [])

            # === 1. 冲高回落/利润保护/高开即卖 ===
            open_p = p.get('open', p.get('close', 0))
            _close_p = p.get('close', 0)

            early_sell_price, early_sell_reason = self._check_early_sell_signals(
                code, strategies, cost, open_p, _close_p)
            # 【V41修正:利润保护(close价卖出)且盘中触止损时,止损优先】
            # 冲高回落/高开即卖 → 以open卖出,发生在开盘,先于盘中止损,不覆盖
            # 利润保护 → 以close卖出,如果盘中low跌破止损,止损更保守应优先
            if early_sell_price > 0 and enable_sl and early_sell_reason == '利润保护':
                sl_pct, _ = self._get_sl_tp_for_code(code)
                stop_price = cost * (1 - sl_pct)
                low_p = p.get('low', p.get('close', 0))
                if low_p <= stop_price:
                    if open_p <= stop_price:
                        early_sell_price = open_p
                        early_sell_reason = '跳空止损'
                    else:
                        early_sell_price = stop_price
                        early_sell_reason = f'止损({sl_pct*100:.0f}%)'

            # 【V48:冲高回落 vs 利润锁定优先级优化】
            # 冲高回落以open价卖,利润锁定以close价卖
            # 当两者都触发时(高开≥3%+盘中冲高≥5%+收盘回撤),取更优价格:
            # - close>open时(收盘高于开盘): 利润锁定更优(收盘价更高)
            # - close<=open时(冲高回落): 冲高回落更优(开盘价更高)
            # 但注意: 冲高回落条件要求close<open,所以两者同时触发时close必然<open
            # 因此冲高回落优先级更高是正确的——因为close<open时open价更优
            # 唯一例外: 冲高回落有pullback_profit_lock_threshold(V47龙头低吸8%),
            # 此时冲高回落被跳过,利润锁定可以正常触发

            if early_sell_price > 0:
                forced_sell_prices[code] = early_sell_price
                forced_sell_codes.append((code, early_sell_reason))
                forced_sell_codes_set.add(code)

            # === 2. 止损/止盈 ===
            if code not in forced_sell_codes_set:
                sl_pct, tp_pct = self._get_sl_tp_for_code(code)
                stop_price = cost * (1 - sl_pct)
                tp_price = cost * (1 + tp_pct)
                low_p = p.get('low', p.get('close', 0))
                high_p = p.get('high', p.get('close', 0))
                if enable_sl and low_p <= stop_price:
                    if open_p <= stop_price:
                        forced_sell_prices[code] = open_p
                        forced_sell_codes.append((code, '跳空止损'))
                    else:
                        forced_sell_prices[code] = stop_price
                        forced_sell_codes.append((code, f'止损({sl_pct*100:.0f}%)'))
                    forced_sell_codes_set.add(code)
                elif enable_tp and high_p >= tp_price:
                    forced_sell_prices[code] = tp_price
                    forced_sell_codes.append((code, f'止盈({tp_pct*100:.0f}%)'))
                    forced_sell_codes_set.add(code)

            # === 2.5 盘中利润锁定(V42) ===
            # 盘中冲高≥6%但从高点回撤≥2.5%→以close价卖出
            # 此信号在止盈之下(止盈价未触达但利润已大幅回吐),保护利润不被完全回撤
            # 【V55-BUG-001修复:提取为_check_intraday_profit_lock方法,消除重复代码】
            if code not in forced_sell_codes_set:
                high_p = p.get('high', p.get('close', 0))
                _close_p = p.get('close', 0)
                if high_p > 0 and _close_p > 0 and cost > 0:
                    if self._check_intraday_profit_lock(cost, high_p, _close_p, code):
                        forced_sell_prices[code] = _close_p
                        forced_sell_codes.append((code, '利润锁定'))
                        forced_sell_codes_set.add(code)

            # === 3. 超时强卖 ===
            if check_timeout and code not in forced_sell_codes_set:
                buy_date_raw = self._cost_basis_date.get(code)
                max_hold = self._get_max_hold_for_code(code)
                if buy_date_raw is not None and max_hold < 999:
                    try:
                        buy_dt_int = int(str(buy_date_raw))
                        trade_dt_int = int(str(trade_date))
                        trade_days_held = self._calc_trade_days_held(buy_dt_int, trade_dt_int)
                        if trade_days_held >= max_hold:
                            # 【V31修复:>=替代>,max_hold_days=3时第3天即触发超时(不是第4天)】
                            # 旧: trade_days_held(3) > max_hold(3)=False→多持1天
                            # 新: trade_days_held(3) >= max_hold(3)=True→第3天超时卖出
                            sell_p = _close_p
                            if sell_p > 0:
                                forced_sell_prices[code] = sell_p
                                forced_sell_codes.append((code, f'超时({trade_days_held}交易日≥{max_hold}交易日)'))
                                forced_sell_codes_set.add(code)
                    except (ValueError, TypeError):
                        pass

        return forced_sell_codes, forced_sell_prices, forced_sell_codes_set

    async def _execute_forced_sells(self, trade_date, holdings, cash, forced_sell_codes,
                                      forced_sell_prices, _sl_tp_prices, rebalance_records, log_prefix=''):
        """执行强制卖出(止损止盈/冲高回落/超时)

        【V29重构】合并调仓日无交易和非调仓日的卖出执行逻辑。

        Args:
            trade_date: 交易日
            holdings: 当前持仓dict
            cash: 当前现金
            forced_sell_codes: [(code, reason)]
            forced_sell_prices: {code: sell_price}
            _sl_tp_prices: 价格数据dict
            rebalance_records: 交易记录列表
            log_prefix: 日志前缀

        Returns:
            cash (更新后)
        """
        for code, reason in forced_sell_codes:
            shares = holdings.get(code, 0)
            if shares <= 0:
                continue
            sell_p = forced_sell_prices.get(code, _sl_tp_prices.get(code, {}).get('close', 0))
            if sell_p <= 0:
                continue
            # 【V29:统一滑点规则】
            slippage_pct = 0 if not should_apply_slippage(reason) else self._get_slippage_for_code(code)
            sell_price_adj = sell_p * (1 - slippage_pct)
            gross_amount = shares * sell_price_adj
            commission = max(gross_amount * self.SELL_COMMISSION, self.MIN_COMMISSION)
            stamp_tax = gross_amount * self.STAMP_TAX
            net_amount = gross_amount - commission - stamp_tax
            cash += net_amount
            del holdings[code]
            if code in self._cost_basis:
                del self._cost_basis[code]
            if code in self._cost_basis_date:
                del self._cost_basis_date[code]
            _sell_strategy = self._get_strategy_for_stock(code)
            rebalance_records.append(RebalanceRecord(
                date=str(trade_date), action='sell', ts_code=code,
                shares=shares, price=sell_p, amount=net_amount,
                reason=reason, strategy_name=_sell_strategy, sentiment=''))
            await self.log(f"   │  ⚠️  {log_prefix}强制卖出: {code} {shares}股 @ {sell_p:.2f} ({reason})")
        return cash

    def _get_max_hold_for_code(self, code):
        """获取股票对应的最大持仓天数"""
        strategies = self.stock_to_strategy.get(code, [])
        strategy_rp = getattr(self, '_strategy_risk_params', {})
        global_max_hold = self._risk_config.get('max_hold_days', 999)
        strategy_max_hold = None
        if isinstance(strategies, list):
            for sname in strategies:
                smh = strategy_rp.get(sname, {}).get('max_hold_days')
                if smh is not None and (strategy_max_hold is None or smh < strategy_max_hold):
                    strategy_max_hold = smh
        return strategy_max_hold if strategy_max_hold is not None else global_max_hold

    def _update_run_state(self, run_state: dict, **kwargs) -> dict:
        """【P1-2修复(V12)】统一更新run_state,消除9处重复的逐字段赋值"""
        # 从kwargs更新,同时支持从局部变量批量更新
        standard_keys = [
            'cash', 'holdings', 'rebalance_records', 'last_prices', 'stock_names',
            'net_value_series', 'daily_profit_list', 'drawdown_series', 'daily_cash_list',
            'peak_value', 'last_net_value',
        ]
        for key in standard_keys:
            if key in kwargs:
                run_state[key] = kwargs[key]
        return run_state

    # ==================== 🎯 【统一输出函数集】 One Function, One Format ====================
    # 所有日志输出必须走以下统一入口!绝对不允许直接调用 await self.log()!
    # ==================================================================================

    async def _print_daily_header(self, day_idx: int, total_days: int, trade_date: str):
        """【统一入口!每日开头必须调用!】"""
        await self.log(f"")
        await self.log(f"═══════════════════════════════════════════════════════════")
        await self.log(f"📅 [第 {day_idx}/{total_days} 天] 处理日期: {trade_date}")
        await self.log(f"═══════════════════════════════════════════════════════════")

    @staticmethod
    def _calc_sentiment_score(limit_up_count: int, limit_down_count: int, index_change: float) -> tuple:
        """【P2-8修复:情绪评分公共方法,消除重复计算】

        Args:
            limit_up_count: 涨停家数
            limit_down_count: 跌停家数
            index_change: 大盘涨跌幅(百分比)

        Returns:
            (sentiment_score: int, sentiment_level: str)
        """
        sentiment_score = min(100, max(0, (limit_up_count - limit_down_count) + int(index_change * 10) + 50))
        if sentiment_score >= 70:
            sentiment_level = 'rising'
        elif sentiment_score >= 40:
            sentiment_level = 'chaos'
        else:
            sentiment_level = 'depression'
        return sentiment_score, sentiment_level

    async def _print_market_environment(self, trade_date: int):
        """【统一入口!每日市场环境判断必须调用!】

        Returns:
            tuple: (sentiment_level, market_sentiment_score, limit_up_count, limit_down_count, index_change)
                sentiment_level: 情绪等级字符串
                market_sentiment_score: 情绪评分(0-100)
                limit_up_count: 涨停家数
                limit_down_count: 跌停家数
                index_change: 大盘平均涨跌幅(百分比)
        """
        await self.log(f"")
        await self.log(f"   ┌───────────────────────────────────────────────────────")
        await self.log(f"   │ 🌡️ 当日市场环境判断")
        await self.log(f"   ├───────────────────────────────────────────────────────")

        # 【P1-1修复(V22):用$substrCP+$switch替代$regexMatch,性能提升3-5x】
        # 旧: $regexMatch对5万条做正则匹配, CPU密集且无法利用索引
        # 新: $substrCP提取代码前2位+$switch分类, 计算量降低80%
        td = trade_date  # 别名简化
        combined_pipeline = [
            {"$match": {"trade_date": td}},
            {"$addFields": {
                "prefix": {"$substrCP": ["$ts_code", 0, 2]}
            }},
            {"$group": {"_id": None,
                # 主板涨跌停(非300/301/688/8/4开头)
                "main_up": {"$sum": {"$cond": [{"$and": [
                    {"$not": {"$in": ["$prefix", ["30", "68", "83", "82", "84", "43"]]}},
                    {"$gte": ["$pct_chg", 9.8]}]}, 1, 0]}},
                "main_down": {"$sum": {"$cond": [{"$and": [
                    {"$not": {"$in": ["$prefix", ["30", "68", "83", "82", "84", "43"]]}},
                    {"$lte": ["$pct_chg", -9.8]}]}, 1, 0]}},
                # 创业板+科创板涨跌停(20%板)
                "gem_up": {"$sum": {"$cond": [{"$and": [
                    {"$in": ["$prefix", ["30", "68"]]},
                    {"$gte": ["$pct_chg", 19.6]}]}, 1, 0]}},
                "gem_down": {"$sum": {"$cond": [{"$and": [
                    {"$in": ["$prefix", ["30", "68"]]},
                    {"$lte": ["$pct_chg", -19.6]}]}, 1, 0]}},
                # 北交所涨跌停(30%板)
                "bse_up": {"$sum": {"$cond": [{"$and": [
                    {"$in": ["$prefix", ["83", "82", "84", "43"]]},
                    {"$gte": ["$pct_chg", 29.8]}]}, 1, 0]}},
                "bse_down": {"$sum": {"$cond": [{"$and": [
                    {"$in": ["$prefix", ["83", "82", "84", "43"]]},
                    {"$lte": ["$pct_chg", -29.8]}]}, 1, 0]}},
                # 全市场平均涨跌幅
                "avg_pct": {"$avg": "$pct_chg"}
            }}
        ]
        limit_up_count = 0
        limit_down_count = 0
        index_change = 0.0
        try:
            combined_r = await mongo_manager.aggregate(C.STOCK_DAILY, combined_pipeline)
            if combined_r and len(combined_r) > 0:
                r = combined_r[0]
                limit_up_count = r.get("main_up", 0) + r.get("gem_up", 0) + r.get("bse_up", 0)
                limit_down_count = r.get("main_down", 0) + r.get("gem_down", 0) + r.get("bse_down", 0)
                index_change = r.get("avg_pct", 0.0)
        except Exception as e:
            # 回退到旧的简单阈值(全市场9.8%)
            logger.warn('BACKTEST', f"板块涨停数统计失败, 使用回退方案: {e}")
            fallback_pipeline = [
                {"$match": {"trade_date": td}},  # td already converted to int above
                {"$group": {"_id": None,
                    "limit_up_count": {"$sum": {"$cond": [{"$gte": ["$pct_chg", 9.8]}, 1, 0]}},
                    "limit_down_count": {"$sum": {"$cond": [{"$lte": ["$pct_chg", -9.8]}, 1, 0]}},
                    "avg_pct": {"$avg": "$pct_chg"}
                }}
            ]
            result = await mongo_manager.aggregate(C.STOCK_DAILY, fallback_pipeline)
            if result and len(result) > 0:
                limit_up_count = result[0].get("limit_up_count", 0)
                limit_down_count = result[0].get("limit_down_count", 0)
                index_change = result[0].get("avg_pct", 0.0)

        # 【修复#5+P1-5:使用类常量,避免两处分别定义】
        FORCE_EMPTY_LIMIT_DOWN = self.FORCE_EMPTY_LIMIT_DOWN
        FORCE_EMPTY_LIMIT_UP = self.FORCE_EMPTY_LIMIT_UP

        await self.log(f"   │  🔹 涨跌停统计: 涨停{limit_up_count}只, 跌停{limit_down_count}只")
        # 【V44:强制空仓条件包含大盘跌幅,日志也需更新】
        _force_empty_index_drop_pct = GLOBAL_RISK.get("force_empty_index_drop_pct", 0.03)
        _index_drop_triggered = index_change is not None and abs(index_change) >= _force_empty_index_drop_pct * 100 and index_change < 0
        if limit_down_count >= FORCE_EMPTY_LIMIT_DOWN or limit_up_count <= FORCE_EMPTY_LIMIT_UP or _index_drop_triggered:
            _trigger_detail = f'跌停≥{FORCE_EMPTY_LIMIT_DOWN}只' if limit_down_count >= FORCE_EMPTY_LIMIT_DOWN else \
                f'涨停≤{FORCE_EMPTY_LIMIT_UP}只' if limit_up_count <= FORCE_EMPTY_LIMIT_UP else \
                f'大盘跌幅≥{_force_empty_index_drop_pct*100:.0f}%'
            await self.log(f"   │     → 🔴 触发强制空仓 ({_trigger_detail})")
        else:
            await self.log(f"   │     → 🟢 不触发强制空仓 (跌停<{FORCE_EMPTY_LIMIT_DOWN}只 且 涨停>{FORCE_EMPTY_LIMIT_UP}只 且 大盘跌幅<{_force_empty_index_drop_pct*100:.0f}%)")
        await self.log(f"   │  🔹 大盘平均涨跌幅: {'+' if index_change and index_change >= 0 else ''}{index_change:.2f}%")
        if index_change is None:
            index_change = 0.0
        if abs(index_change) < 3:
            await self.log(f"   │     → 🟢 符合交易条件")
        else:
            await self.log(f"   │     → 🟡 极端行情,谨慎交易")

        # 【修复#22:统一情绪周期阈值,和因子映射保持一致】
        # 情绪周期评分 → 阈值统一:
        #  score ≥ 70 → 上升期 (rising)
        #  40 ≤ score < 70 → 混沌期 (chaos)
        #  score < 40 → 衰退期 (depression)
        #
        # 【P2-5文档化】情绪评分公式:
        #   sentiment_score = (涨停数 - 跌停数) + 大盘涨跌幅*10 + 50
        # 【P2-8修复:使用公共方法_calc_sentiment_score,消除重复】
        sentiment_score, _base_level = self._calc_sentiment_score(limit_up_count, limit_down_count, index_change)
        # 附加仓位系数信息(_print_market_environment专用)
        if sentiment_score >= 70:
            sentiment_level = "高潮期,仓位系数1.0"
        elif sentiment_score >= 40:
            sentiment_level = "震荡期,仓位系数0.7"
        else:
            sentiment_level = "冰点期,仓位系数0.3"
        await self.log(f"   │  🔹 情绪周期评分:{sentiment_score}分 → {sentiment_level}")
        await self.log(f"   └───────────────────────────────────────────────────────")

        # 【V30:P1-3】缓存情绪评分结果,供非调仓日复用,避免每天5万条聚合查询
        self._cached_sentiment_level = sentiment_level
        self._cached_sentiment_score = sentiment_score
        self._cached_limit_up_count = limit_up_count
        self._cached_limit_down_count = limit_down_count

        # 【V44:缓存index_change供非调仓日复用,强制空仓大盘跌幅条件需要】
        self._cached_index_change = index_change

        return sentiment_level, sentiment_score, limit_up_count, limit_down_count, index_change

    async def _print_single_strategy_filtering(self, strategy_name: str, params: dict, conditions: list, factor_df, strategy_configs: dict, all_selected_strategies: list):
        """【统一入口!所有策略筛选打印必须调用!One Function, One Format!】

        所有5个策略(半路追涨/首板打板/涨停开板/龙头低吸/跌停翘板)必须调用此函数!
        绝对不允许在策略代码中直接写 await self.log()!

        Args:
            strategy_name: 策略名称
            params: 策略参数字典
            conditions: 条件列表
            factor_df: 因子数据DataFrame
            strategy_configs: 所有策略配置字典
            all_selected_strategies: 所有选中的策略列表

        Returns:
            set: 该策略选出的候选股票集合
        """
        # 跳过未选中的策略
        if strategy_name not in all_selected_strategies:
            return set()

        await self.log(f"")
        await self.log(f"   ┌───────────────────────────────────────────────────────")
        await self.log(f"   │ 🔹 【{strategy_name}】")
        await self.log(f"   ├───────────────────────────────────────────────────────")

        # 参数配置显示(根据不同策略格式化显示)
        await self.log(f"   │    📌 参数配置:")
        if strategy_name == "半路追涨":
            # 【N02/N10修复:日志参数添加默认值fallback,避免None*100的TypeError】
            min_rise_pct = params.get("min_rise_pct") if params.get("min_rise_pct") is not None else STRATEGY_CONFIGS.get("halfway_chase", {}).get("params", {}).get("min_rise_pct", 0.03)
            max_rise_pct = params.get("max_rise_pct") if params.get("max_rise_pct") is not None else STRATEGY_CONFIGS.get("halfway_chase", {}).get("params", {}).get("max_rise_pct", 0.07)
            # 【修复#4:默认值统一为2.0,和优化后的defaults.py保持一致】
            volume_threshold = params.get("volume_threshold", params.get("min_volume_ratio")) if params.get("volume_threshold", params.get("min_volume_ratio")) is not None else 2.0
            min_volume_ratio = volume_threshold
            allow_after_10am = params.get("allow_after_10am") if params.get("allow_after_10am") is not None else False
            await self.log(f"   │        • 量比阈值: {volume_threshold}倍")
            await self.log(f"   │        • 涨幅区间: {min_rise_pct*100:.1f}% ~ {max_rise_pct*100:.1f}%")
            await self.log(f"   │        • 允许10点后买入: {'是' if allow_after_10am else '否'}")
        elif strategy_name == "首板打板":
            min_seal_amount = params.get("min_seal_amount") if params.get("min_seal_amount") is not None else STRATEGY_CONFIGS.get("first_limit_up", {}).get("params", {}).get("min_seal_amount", 5000)
            max_limit_time = params.get("max_limit_up_time") if params.get("max_limit_up_time") is not None else "10:00"
            min_circ_mv = params.get("min_circulation_market_cap") if params.get("min_circulation_market_cap") is not None else STRATEGY_CONFIGS.get("first_limit_up", {}).get("params", {}).get("min_circulation_market_cap", 50)
            max_circ_mv = params.get("max_circulation_market_cap") if params.get("max_circulation_market_cap") is not None else STRATEGY_CONFIGS.get("first_limit_up", {}).get("params", {}).get("max_circulation_market_cap", 500)
            min_volume_ratio = params.get("min_volume_ratio") if params.get("min_volume_ratio") is not None else STRATEGY_CONFIGS.get("first_limit_up", {}).get("params", {}).get("min_volume_ratio", 1.5)
            min_turnover = params.get("min_turnover_rate") if params.get("min_turnover_rate") is not None else STRATEGY_CONFIGS.get("first_limit_up", {}).get("params", {}).get("min_turnover_rate", 3)
            max_turnover = params.get("max_turnover_rate") if params.get("max_turnover_rate") is not None else STRATEGY_CONFIGS.get("first_limit_up", {}).get("params", {}).get("max_turnover_rate", 15)
            max_blast = params.get("max_blast_count") if params.get("max_blast_count") is not None else 1
            require_hot = params.get("require_hot_sector") if params.get("require_hot_sector") is not None else True
            require_sentiment = params.get("require_sentiment_period", ["rising", "chaos"])
            # 【N11修复:竞价涨幅从参数读取,不再硬编码】
            opening_min = params.get("opening_pct_min") if params.get("opening_pct_min") is not None else STRATEGY_CONFIGS.get("first_limit_up", {}).get("params", {}).get("opening_pct_min", -1.0)
            opening_max = params.get("opening_pct_max") if params.get("opening_pct_max") is not None else STRATEGY_CONFIGS.get("first_limit_up", {}).get("params", {}).get("opening_pct_max", 7.0)
            await self.log(f"   │        • 竞价涨幅: {opening_min}% ~ {opening_max}%")
            await self.log(f"   │        • 量比要求: ≥ {min_volume_ratio}")
            await self.log(f"   │        • 换手率: {min_turnover}% ~ {max_turnover}%")
            await self.log(f"   │        • 流通市值: {min_circ_mv}亿 ~ {max_circ_mv}亿")
            await self.log(f"   │        • 最小封单: {min_seal_amount}万元")
            await self.log(f"   │        • 最晚涨停: {max_limit_time}")
            await self.log(f"   │        • 最大开板: {max_blast}次")
            await self.log(f"   │        • 要求热门板块: {'是' if require_hot else '否'}")
            await self.log(f"   │        • 情绪周期要求: {', '.join(require_sentiment)}")
        elif strategy_name == "涨停开板":
            # 【N02/N08修复:日志参数添加默认值fallback,避免None的TypeError】
            min_consecutive = params.get("min_consecutive_limit") if params.get("min_consecutive_limit") is not None else STRATEGY_CONFIGS.get("limit_up_open", {}).get("params", {}).get("min_consecutive_limit", 2)
            _raw_turnover = params.get("min_turnover_rate") if params.get("min_turnover_rate") is not None else STRATEGY_CONFIGS.get("limit_up_open", {}).get("params", {}).get("min_turnover_rate", 15.0)
            min_turnover = _raw_turnover * 100 if _raw_turnover < 1 else _raw_turnover
            min_volume_ratio = params.get("min_volume_ratio") if params.get("min_volume_ratio") is not None else STRATEGY_CONFIGS.get("limit_up_open", {}).get("params", {}).get("min_volume_ratio", 2.0)
            require_sentiment = params.get("require_sentiment_period", ["rising"])
            # 【日线模式修复】涨停开板不再依赖盘中数据
            await self.log(f"   │        • 昨日涨停 + 今日未封住")
            await self.log(f"   │        • 近5日≥{min_consecutive}板")
            await self.log(f"   │        • 今日涨幅≥0%")
            await self.log(f"   │        • 量比≥{min_volume_ratio}")
            await self.log(f"   │        • 换手率≥{min_turnover:.1f}%")
            await self.log(f"   │        • 情绪周期要求: {', '.join(require_sentiment)}")
        elif strategy_name == "龙头低吸":
            # 【N02/N09修复:日志参数添加默认值fallback,避免None*100的TypeError】
            min_consecutive = params.get("min_consecutive_limit") if params.get("min_consecutive_limit") is not None else STRATEGY_CONFIGS.get("dragon_head", {}).get("params", {}).get("min_consecutive_limit", 1)
            min_correction = params.get("min_correction_pct") if params.get("min_correction_pct") is not None else STRATEGY_CONFIGS.get("dragon_head", {}).get("params", {}).get("min_correction_pct", 0.05)
            max_correction = params.get("max_correction_pct") if params.get("max_correction_pct") is not None else STRATEGY_CONFIGS.get("dragon_head", {}).get("params", {}).get("max_correction_pct", 0.20)
            correction_days_min = params.get("correction_days_min") if params.get("correction_days_min") is not None else STRATEGY_CONFIGS.get("dragon_head", {}).get("params", {}).get("correction_days_min", 1)
            correction_days_max = params.get("correction_days_max") if params.get("correction_days_max") is not None else STRATEGY_CONFIGS.get("dragon_head", {}).get("params", {}).get("correction_days_max", 7)
            support_level = params.get("support_level") if params.get("support_level") is not None else STRATEGY_CONFIGS.get("dragon_head", {}).get("params", {}).get("support_level", "ma5")
            await self.log(f"   │        • 最小连续涨停: {min_consecutive}天")
            await self.log(f"   │        • 回调幅度: {min_correction*100:.1f}% ~ {max_correction*100:.1f}%")
            await self.log(f"   │        • 回调天数: {correction_days_min} ~ {correction_days_max}天")
            await self.log(f"   │        • 支撑位: {support_level.upper()}")
            await self.log(f"   │        • 要求缩量回调: volume/ma5 ≤ 1.5")
        elif strategy_name == "跌停翘板":
            min_consecutive = params.get("min_consecutive_limit")
            # 【修复#47: min_qiao_amount单位统一为千元(与数据库limit_down_open_amount一致)】
            # 前端传10000(万元),数据库因子是千元,需*1000转换
            # 前端传万元,数据库因子千元,需*10转换
            # 【P2-C修复:明确单位转换规则,消除魔法数字】
            # 前端默认传万元(1000万元=10000),数据库因子limit_down_open_amount存千元
            # 规则:如果<100000(即<10万元千元单位),说明传入的是万元单位,需×1000转千元
            # 如果>=100000,说明已经是千元单位,无需转换
            _raw_qiao = params.get("min_qiao_amount") if params.get("min_qiao_amount") is not None else STRATEGY_CONFIGS["limit_down_qiao"]["params"]["min_qiao_amount"]
            # 万元→千元: 1000万 × 1000 = 1000000千元;但前端传的是10000(万元)不是10000000
            # 实际: 前端传10000(万) → ×10 = 100000千元 ✓; 前端传100000(千) → 不转换 ✓
            min_qiao_amount = _raw_qiao * 10 if _raw_qiao < 100000 else _raw_qiao
            min_rise_after = params.get("min_rise_after_qiao") if params.get("min_rise_after_qiao") is not None else STRATEGY_CONFIGS["limit_down_qiao"]["params"]["min_rise_after_qiao"]
            require_high_sentiment = params.get("require_high_sentiment") if params.get("require_high_sentiment") is not None else STRATEGY_CONFIGS["limit_down_qiao"]["params"]["require_high_sentiment"]
            await self.log(f"   │        • 最小连续跌停: {min_consecutive}天")
            _raw_turnover_qiao = params.get('min_turnover_rate') if params.get('min_turnover_rate') is not None else STRATEGY_CONFIGS["limit_down_qiao"]["params"].get('min_turnover_rate', 10.0)
            _turnover_display = _raw_turnover_qiao * 100 if _raw_turnover_qiao < 1 else _raw_turnover_qiao
            await self.log(f"   │        • 换手率要求: ≥ {_turnover_display:.0f}%")
            await self.log(f"   │        • 最小翘板金额: {_raw_qiao}万元={min_qiao_amount}千元")
            await self.log(f"   │        • 翘板后最小涨幅: {min_rise_after*100:.1f}%")
            await self.log(f"   │        • 要求高情绪周期: {'是' if require_high_sentiment else '否'}")
        else:
            # 通用显示
            for param_name, param_value in list(params.items())[:8]:
                display_value = str(param_value) if not isinstance(param_value, list) else ', '.join(str(v) for v in param_value[:3]) + ('...' if len(param_value) > 3 else '')
                await self.log(f"   │        • {param_name}: {display_value}")
        await self.log(f"   └───────────────────────────────────────────────────────")

        # 筛选过程输出
        await self.log(f"")
        await self.log(f"   ┌───────────────────────────────────────────────────────")
        await self.log(f"   │ 🔍 【{strategy_name}】筛选过程:")
        await self.log(f"   ├───────────────────────────────────────────────────────")

        # 【P1-1修复(V20):避免factor_df.copy()深拷贝,改用布尔索引筛选】
        # 旧: current_df = factor_df.copy() → 每个策略深拷贝~5000行×40列
        # 新: 用布尔掩码逐步过滤,避免5次内存分配
        current_mask = pd.Series(True, index=factor_df.index)
        strategy_conditions = strategy_configs.get(strategy_name, conditions)

        for idx_cond, cond in enumerate(strategy_conditions, 1):
            factor_name = cond["name"]
            target_value = cond["target"]
            operator = cond.get("operator", ">=")
            label = cond.get("label", f"条件{idx_cond}")

            # 【修复:target=0且operator为>=时,表示"不限制",跳过此条件】
            try:
                if operator == ">=" and float(target_value) == 0 and factor_name not in ('first_limit_up', 'limit_up_yesterday', 'hot_sector', 'open_above_limit_down', 'limit_down_yesterday'):
                    await self.log(f"   │    ⚪ 条件{idx_cond}: {label} → 跳过(target=0表示不限制)")
                    continue
            except (ValueError, TypeError):
                pass

            if factor_name not in factor_df.columns:
                await self.log(f"   │    ⚠️ 因子 {factor_name} 缺失,跳过此条件(不影响其他条件筛选)")
                continue

            # 【P0-2修复:因子列存在但值全NaN时,也应跳过该条件】
            col = factor_df[factor_name]
            masked_col = col[current_mask]
            if masked_col.isna().all():
                await self.log(f"   │    ⚠️ 因子 {factor_name} 全部为空,跳过此条件(不影响其他条件筛选)")
                continue

            before_count = current_mask.sum()
            try:
                target_float = float(target_value)
                # 转换masked_col为float类型(避免object dtype比较问题)
                masked_col = pd.to_numeric(masked_col, errors='coerce')
                target_value = target_float
            except (ValueError, TypeError):
                pass

            # 【P1-1修复(V20):用布尔掩码替代DataFrame切片,避免深拷贝】
            cond_mask = pd.Series(False, index=factor_df.index)
            valid_idx = current_mask[current_mask].index  # 当前有效行的索引
            if operator == ">=":
                cond_mask.loc[valid_idx] = masked_col >= target_value
            elif operator == "<=":
                cond_mask.loc[valid_idx] = masked_col <= target_value
            elif operator == ">":
                cond_mask.loc[valid_idx] = masked_col > target_value
            elif operator == "<":
                cond_mask.loc[valid_idx] = masked_col < target_value
            elif operator == "==":
                cond_mask.loc[valid_idx] = masked_col == target_value
            elif operator == "in":
                if isinstance(target_value, list) and len(target_value) == 0:
                    await self.log(f"   │    ⚪ 条件{idx_cond}: {label}")
                    await self.log(f"   │       → 跳过(空列表,不进行过滤)")
                    continue
                cond_mask.loc[valid_idx] = masked_col.isin(target_value)
            current_mask = current_mask & cond_mask

            after_count = current_mask.sum()
            filter_rate = ((before_count - after_count) / before_count * 100) if before_count > 0 else 0

            await self.log(f"   │    ✅ 条件{idx_cond}: {label}")
            await self.log(f"   │       → 满足 {after_count} 只 / 共 {before_count} 只 (过滤率:{filter_rate:.2f}%)")

            if after_count == 0:
                await self.log(f"   │    ⚠️  提前结束: 条件{idx_cond}【{label}】过滤后0只,建议调整参数")
                break

        candidate_count = current_mask.sum()
        candidate_codes = factor_df.loc[current_mask, "ts_code"].tolist() if candidate_count > 0 else []
        await self.log(f"   ├───────────────────────────────────────────────────────")
        await self.log(f"   │ 🎯 【{strategy_name}】最终候选: {candidate_count} 只")
        await self.log(f"   └───────────────────────────────────────────────────────")
        await self.log(f"")

        return set(candidate_codes)

    async def _print_stock_pool_and_cleaning(self, trade_date: str, universe: set, st_count: int, new_stock_count: int, low_liquidity_count: int):
        """【统一入口!股票池获取+数据清洗打印必须调用!】"""
        await self.log(f"   🔍 正在获取当日股票池...")
        await self.log(f"   ✅ 原始股票池数量: {len(universe)} 只")
        await self.log(f"   🧹 数据清洗:")
        await self.log(f"      🔹 剔除ST股票: {st_count}只")
        await self.log(f"      🔹 剔除次新股: {new_stock_count}只")
        await self.log(f"      🔹 剔除流动性<500万(amount<5000千元): {low_liquidity_count}只")
        cleaned_count = len(universe) - st_count - new_stock_count - low_liquidity_count
        await self.log(f"      🔹 清洗后剩余: {cleaned_count}只")

    async def _record_daily_net_value(self, trade_date: str, holdings: dict, cash: float,
                                             last_net_value: float, peak_value: float,
                                             net_value_series: list, daily_profit_list: list,
                                             drawdown_series: list, daily_cash_list: list,
                                             last_prices: dict = None, prices: dict = None,
                                             rebalance_set: set = None) -> tuple:
        """【P0修复】统一记录每日净值,确保continue前也能调用
        【V36优化:停牌股流动性折价】停牌超过3天的股票每日-1%折价,避免净值虚高
        Returns: (last_net_value, peak_value) 更新后的值
        """
        # 计算持仓市值
        holdings_market_value = 0
        if holdings and len(holdings) > 0:
            prices_for_hold = last_prices or prices or {}
            for code, shares in holdings.items():
                if shares > 0:
                    if code in prices_for_hold and isinstance(prices_for_hold.get(code), dict):
                        close = prices_for_hold[code].get('close', 0)
                        if close > 0:
                            holdings_market_value += shares * close
                            # 【V36:更新最后有效价格和日期】
                            if not hasattr(self, '_last_valid_price'):
                                self._last_valid_price = {}
                                self._last_valid_price_date = {}
                            self._last_valid_price[code] = close
                            self._last_valid_price_date[code] = trade_date
                            continue
                    # 【V36:停牌股流动性折价】
                    # 无当日价格 → 停牌, 用最后有效价格并施加折价
                    lvp = getattr(self, '_last_valid_price', {}).get(code, 0)
                    lvp_date = getattr(self, '_last_valid_price_date', {}).get(code, 0)
                    if lvp > 0 and lvp_date:
                        # 计算停牌天数(交易日)
                        suspended_days = self._calc_trade_days_held(int(lvp_date), int(trade_date)) if lvp_date != trade_date else 0
                        if suspended_days > 3:
                            # 停牌超过3天, 每天施加1%流动性折价
                            discount = (0.99 ** (suspended_days - 3))
                            holdings_market_value += shares * lvp * discount
                        else:
                            holdings_market_value += shares * lvp
                    elif lvp > 0:
                        holdings_market_value += shares * lvp

        current_net_value = cash + holdings_market_value
        daily_profit = current_net_value - last_net_value

        if current_net_value > peak_value:
            peak_value = current_net_value
        drawdown = (peak_value - current_net_value) / peak_value if peak_value > 0 else 0

        # 【修复】净值归一化:net_value 除以 initial_cash,前端期望首日净值=1.0
        _initial_cash = getattr(self, '_initial_cash', 0)
        if _initial_cash <= 0:
            _initial_cash = getattr(self, '_risk_config', {}).get('initial_cash', 1000000)
        normalized_nv = current_net_value / _initial_cash if _initial_cash > 0 else current_net_value

        net_value_series.append({
            "trade_date": trade_date,
            "net_value": normalized_nv,
            "daily_profit": daily_profit / _initial_cash if _initial_cash > 0 else daily_profit,
            "drawdown": drawdown
        })
        daily_profit_list.append(daily_profit)
        drawdown_series.append(drawdown)
        daily_cash_list.append(cash / current_net_value if current_net_value > 0 else 1.0)

        return current_net_value, peak_value

    async def _print_daily_summary(self, trade_date: str, holdings_count: int, cash: float):
        """【统一入口!每日收盘汇总必须调用!】"""
        await self.log(f"")
        await self.log(f"═══════════════════════════════════════════════════════════")
        await self.log(f"📅 处理完成: {trade_date}")
        await self.log(f"   💵 当日持仓: {holdings_count} 只股票, 现金剩余: {cash:,.2f} 元")
        await self.log(f"═══════════════════════════════════════════════════════════")

    # ==================== 🎯 【统一输出函数集结束】 ====================


    async def run(self, config: dict) -> dict:
        """
        运行组合回测

        Args:
            config: {
                "universe": "all_a",
                "start_date": "20230101",
                "end_date": "20260101",
                "initial_cash": 1000000,
                "rebalance_freq": "daily",
                "top_n": 20,
                "weight_method": "equal",
                "factors": [
                    {"name": "momentum_20d", "weight": 0.3},
                    {"name": "pb", "weight": 0.3},
                    {"name": "roe", "weight": 0.4},
                ],
                "exclude": ["st", "new_stock"],
                "benchmark": "000300.SH",
                "task_id": "任务ID",
                "push_log": "日志推送方法"
            }
        """
        try:
            return await self._run_impl(config)
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            logger.error('BACKTEST', f'run() 未处理异常: {e}\n{tb}')
            return {"error": f'run() unhandled exception: {e}'}

    async def _run_impl(self, config: dict) -> dict:
        """run()的实际实现 - 调度器

        将原1717行的逻辑拆分为4个子方法:
        1. _init_run_config: 初始化配置和状态
        2. _process_rebalance_day: 调仓日处理
        3. _process_non_rebalance_day: 非调仓日/无交易日处理
        4. _build_run_result: 构建最终结果
        """
        # 1. 初始化配置和运行状态
        run_state = await self._init_run_config(config)

        # 【P0-1修复】检查_init_run_config是否返回错误dict
        if isinstance(run_state, dict) and 'error' in run_state:
            return run_state  # 直接返回错误,避免KeyError

        # 2. 逐日回测主循环
        all_trade_dates = run_state['all_trade_dates']
        rebalance_set = run_state['rebalance_set']
        total_days = run_state['total_days']

        for idx, trade_date in enumerate(all_trade_dates):
            # 【P0修复(V10):确保trade_date是int类型,universe可能返回string】
            if isinstance(trade_date, str):
                trade_date = int(trade_date)
            # 【P2-4:每日价格缓存,避免同一天多次查MongoDB】
            self._daily_price_cache = {}
            self._daily_price_cache_date = trade_date

            # 🔧 内存优化: 每10天强制一次垃圾回收
            if idx % 10 == 0:
                log_memory_usage(f"[day {idx+1}/{total_days}] 回测开始前")
                gc.collect()

            # 推送进度到Redis(每10%推送一次)
            last_pushed_progress = run_state['last_pushed_progress']
            progress_pct = int(((idx + 1) / total_days) * 100)
            if progress_pct != last_pushed_progress and progress_pct % 10 == 0:
                await mongo_manager.update_one(
                    "backtest_tasks",
                    {"task_id": self.task_id},
                    {"$set": {"progress": 30 + int(progress_pct * 0.6)}},
                )
                try:
                    await redis_manager.publish(f"backtest:progress:{self.task_id}", {
                        "task_id": self.task_id,
                        "progress": 30 + int(progress_pct * 0.6),
                        "current_day": idx + 1,
                        "total_days": total_days,
                        "status": "running"
                    })
                except Exception:
                    pass
                run_state['last_pushed_progress'] = progress_pct

            # ==================== 1️⃣ 每日统一开头 ====================
            await self._print_daily_header(idx+1, total_days, trade_date)

            # ==================== 2️⃣ 每日市场环境判断 ====================
            # 【未来函数修复】用前一个交易日的涨停/跌停数计算情绪评分
            # 实盘9:30开盘前只能用前日数据,当天涨停数收盘后才知道
            prev_trade_date = all_trade_dates[idx - 1] if idx > 0 else trade_date
            # 【V30:P1-3】非调仓日复用上次计算的情绪评分,避免5万条聚合查询
            # 非调仓日只需要sentiment_level用于净值记录,不需要涨跌停详情和日志输出
            is_rebalance_day = trade_date in rebalance_set
            if is_rebalance_day:
                sentiment_level, market_sentiment_score, limit_up_count, limit_down_count, index_change = await self._print_market_environment(prev_trade_date)
            else:
                # 复用上一次计算的结果(情绪评分在非调仓日不会变化太多,1天差异可忽略)
                sentiment_level = getattr(self, '_cached_sentiment_level', '震荡期,仓位系数0.7')
                market_sentiment_score = getattr(self, '_cached_sentiment_score', 50)
                limit_up_count = getattr(self, '_cached_limit_up_count', 0)
                limit_down_count = getattr(self, '_cached_limit_down_count', 0)
                index_change = getattr(self, '_cached_index_change', 0.0)

            # ==================== 🔴 强制空仓判断 ====================
            # 【修复#5:统一阈值 - 与日志打印使用同一阈值】
            # 【修复#33:enable_force_empty开关实际生效】
            # 【P1-3修复:从config读取阈值,支持前端细粒度配置】
            enable_force_empty = config.get("enable_force_empty", True)
            # 前端可传force_empty_config覆盖默认阈值
            force_empty_cfg = config.get("force_empty_config", {})
            FORCE_EMPTY_LIMIT_DOWN = force_empty_cfg.get("limit_down_count", self.FORCE_EMPTY_LIMIT_DOWN)
            FORCE_EMPTY_LIMIT_UP = force_empty_cfg.get("limit_up_count", self.FORCE_EMPTY_LIMIT_UP)
            # 【V44修复:强制空仓加入大盘跌幅条件】
            # 旧bug: strategy_defaults.py定义了force_empty_index_drop_pct=0.03(大盘跌幅≥3%触发),API层也传入index_drop_pct
            # 但回测引擎完全忽略index_change,只看涨跌停数→极端暴跌日可能不触发强制空仓
            # 修复: 读取index_drop_pct阈值,当大盘跌幅超过阈值时也触发强制空仓
            force_empty_index_drop_pct = force_empty_cfg.get(
                "index_drop_pct", GLOBAL_RISK.get("force_empty_index_drop_pct", 0.03))
            # index_change是百分比(如-3.5表示跌3.5%),force_empty_index_drop_pct是小数(如0.03表示3%)
            # 注意: index_change可能来自缓存(getattr默认0.0),需处理None
            _index_drop_triggered = False
            if index_change is not None and abs(index_change) >= force_empty_index_drop_pct * 100 and index_change < 0:
                _index_drop_triggered = True
            force_empty_triggered = enable_force_empty and (
                limit_down_count >= FORCE_EMPTY_LIMIT_DOWN or limit_up_count <= FORCE_EMPTY_LIMIT_UP
                or _index_drop_triggered
            )
            if force_empty_triggered:
                _trigger_reason = '跌停数≥{}'.format(FORCE_EMPTY_LIMIT_DOWN) if limit_down_count >= FORCE_EMPTY_LIMIT_DOWN else \
                    '涨停数≤{}'.format(FORCE_EMPTY_LIMIT_UP) if limit_up_count <= FORCE_EMPTY_LIMIT_UP else \
                    '大盘跌幅≥{:.0f}%'.format(force_empty_index_drop_pct * 100)
                await self.log(f"   ⚠️  强制空仓开关已启用,市场触发空仓条件({ _trigger_reason}),直接清仓")
            elif not enable_force_empty:
                await self.log(f"   i️  强制空仓开关已关闭,不检查空仓条件")

            # ==================== 3️⃣ 调仓日/非调仓日分流 ====================
            if trade_date in rebalance_set:
                run_state = await self._process_rebalance_day(
                    trade_date, idx, run_state,
                    sentiment_level, market_sentiment_score, limit_up_count, limit_down_count,
                    force_empty_triggered)
            else:
                run_state = await self._process_non_rebalance_day(
                    trade_date, idx, run_state, sentiment_level)

        # 3. 构建最终结果
        return await self._build_run_result(run_state)

    async def _init_run_config(self, config: dict) -> dict:
        """初始化回测运行配置

        解析config、初始化self属性、加载universe/factor_engine/benchmark、因子完整性检测
        返回run_state dict包含所有运行时状态
        """
        task_id = config.get("task_id")
        push_log = config.get("push_log")

        # 保存 log 到实例,让所有方法都能使用
        # 日志推送辅助方法:同时写入本地日志 + 推送到前端
        async def log(msg: str):
            logger.info('BACKTEST', msg)
            if push_log and task_id:
                await push_log(task_id, msg)
        self.log = log

        # 【修复#4:保存 task_id 实例变量,用于进度推送Redis】
        self.task_id = task_id

        # 🔧 提前初始化所有实例属性,避免提前返回导致属性缺失
        self.weight_method = config.get("weight_method", "equal")
        self._max_stocks = config.get("max_stocks", 3)
        self._strategy_weights = config.get("strategy_weights", {})

        await self.log(f"🚀 开始组合回测: {config['start_date']} -> {config['end_date']}")

        # 🔧 读取风控配置(优先使用请求中的配置,如果没有从数据库读取)
        # 默认风控配置
        risk_config = {
            "enable_stop_loss": config.get("enable_stop_loss", True),
            "stop_loss_pct": config.get("stop_loss_pct", GLOBAL_RISK["stop_loss_pct"]),
            "enable_take_profit": config.get("enable_take_profit", True),
            "take_profit_pct": config.get("take_profit_pct", GLOBAL_RISK["take_profit_pct"]),
            "enable_ma60_filter": config.get("enable_ma60_filter", True),
            "enable_sector_concentration": config.get("enable_sector_concentration", True),
            "sector_concentration_top_n": config.get("sector_concentration_top_n", 3),
            "enable_auction_filter": config.get("enable_auction_filter", True),
            "enable_sentiment_cycle": config.get("enable_sentiment_cycle", True),
            "enable_force_empty": config.get("enable_force_empty", True),
            # 【P1-1/P1-2修复:添加max_hold_days和max_position_per_stock到风控配置】
            "max_hold_days": config.get("max_hold_days", 10),  # 默认10天(超短策略默认3天由ultra_short传入)
            "max_position_per_stock": config.get("max_position_per_stock", config.get("max_position_percent", 1.0)),  # 默认不限制
        }

        # 【V48修复:将GLOBAL_RISK中的利润锁定/持仓保护参数写入risk_config】
        # V47修改了intraday_lock_min_high_rise(0.06→0.05)和intraday_lock_pullback_pct(0.025→0.02)
        # 但risk_config从未设置这些字段,导致_check_and_execute_forced_sells中.get()fallback到硬编码旧值
        # 结果: V47的利润锁定参数从未生效,profit_lock始终为0
        for _key in ("intraday_lock_min_high_rise", "intraday_lock_pullback_pct", "intraday_lock_min_profit",
                     "hold_protection_threshold"):
            if _key not in risk_config and _key in GLOBAL_RISK:
                risk_config[_key] = GLOBAL_RISK[_key]

        # 如果请求中传入了风控配置,使用传入的配置
        if "risk_config" in config and config["risk_config"]:
            for k, v in config["risk_config"].items():
                risk_config[k] = v

        # 输出风控配置到日志
        await self.log("🔧 当前风控配置:")
        await self.log(f"    🔹 {'✅' if risk_config['enable_stop_loss'] else '❌'} 强化止损: {risk_config['stop_loss_pct'] * 100:.1f}%")
        await self.log(f"    🔹 {'✅' if risk_config['enable_take_profit'] else '❌'} 动态止盈: {risk_config['take_profit_pct'] * 100:.1f}%")
        await self.log(f"    🔹 📅 最大持仓天数: {risk_config['max_hold_days']}")
        await self.log(f"    🔹 📊 单票最大仓位: {risk_config['max_position_per_stock'] * 100:.0f}%")
        await self.log(f"    🔹 {'✅' if risk_config['enable_ma60_filter'] else '❌'} 大盘MA60过滤")
        await self.log(f"    🔹 {'✅' if risk_config['enable_sector_concentration'] else '❌'} 板块集中度过滤: 保留前 {risk_config['sector_concentration_top_n']} 名")
        await self.log("🔧 Phase1 实盘对标修复:")
        await self.log("    🔹 ✅ T+1约束: 当日买入不可卖出")
        await self.log("    🔹 ✅ 半路追涨买入价: open*(1+min_rise*0.8) (盘中趋势判断近似,V25验证close买入代价过大)")
        await self.log("    🔹 ✅ 半路追涨方案B: 开盘≤3%(排除高开追高) + SL5%/TP10% + 收盘确认≥3%")
        await self.log("    🔹 ✅ 龙头低吸买入价: low×1.005→low+(high-low)×0.25 (偏低位但不极端)")
        await self.log("    🔹 ✅ 跳空止损: open<止损价→以open卖出 (最差情况)")
        await self.log("    🔹 ✅ 止损卖出价: close→止损价/跳空open (不再一律用close)")

        # 保存风控配置到实例,后续使用
        self._risk_config = risk_config

        # 【P0-2修复:构建策略级riskParams映射,策略级止损止盈优先于全局】
        # 【P1-2修复(第十轮):透传max_hold_days和slippage_pct到策略级风控】
        selected_strategies = config.get("selected_strategies", [])
        self._strategy_risk_params = {}  # strategy_name -> {stop_loss_pct, take_profit_pct, max_hold_days, slippage_pct}
        self._strategy_params = {}  # strategy_name -> {min_rise_pct, min_volume_ratio, ...}
        # 【V17修复:策略风控参数优先级】
        # 前端riskParams > 全局risk_config > STRATEGY_CONFIGS.riskParams
        # 旧bug: STRATEGY_CONFIGS.riskParams始终覆盖全局risk_config,导致用户设置SL/TP无效
        # 新逻辑: 只有前端明确传riskParams时才覆盖全局设置,策略默认值不再自动覆盖
        for s in selected_strategies:
            sname = s.get("name", "")
            sid = s.get("id", "")
            sp = s.get("params", {})
            if sp:
                self._strategy_params[sname] = sp
            rp = s.get("riskParams", {})
            strategy_cfg = STRATEGY_CONFIGS.get(sid, {})
            strategy_default_rp = strategy_cfg.get("riskParams", {})
            # 全局risk_config值(用户设置的)
            global_sl = risk_config["stop_loss_pct"]
            global_tp = risk_config["take_profit_pct"]
            global_mhd = risk_config.get("max_hold_days", 3)
            global_slippage = config.get("slippage_pct", 0.002)
            # 策略默认值(STRATEGY_CONFIGS中的)
            strategy_default_sl = strategy_default_rp.get("stop_loss_pct", global_sl)
            strategy_default_tp = strategy_default_rp.get("take_profit_pct", global_tp)
            strategy_default_mhd = strategy_default_rp.get("max_hold_days", global_mhd)
            strategy_default_slippage = strategy_default_rp.get("slippage_pct", global_slippage)
            if rp:
                # 前端明确传了riskParams → 最高优先级
                self._strategy_risk_params[sname] = {
                    "stop_loss_pct": rp.get("stop_loss_pct", strategy_default_sl),
                    "take_profit_pct": rp.get("take_profit_pct", strategy_default_tp),
                    "max_hold_days": rp.get("max_hold_days", strategy_default_mhd),
                    "slippage_pct": rp.get("slippage_pct", strategy_default_slippage),
                }
            else:
                # 没有前端riskParams → 使用策略默认值
                # V17: 策略默认值不再无条件覆盖全局设置
                # 如果全局risk_config与GLOBAL_RISK默认值不同,说明用户明确修改了,应优先使用
                # 如果全局risk_config就是GLOBAL_RISK默认值,则使用策略默认值(策略更优)
                user_overrode_sl = global_sl != GLOBAL_RISK.get("stop_loss_pct", 0.03)
                user_overrode_tp = global_tp != GLOBAL_RISK.get("take_profit_pct", 0.07)
                user_overrode_mhd = global_mhd != GLOBAL_RISK.get("max_hold_days", 3)
                self._strategy_risk_params[sname] = {
                    "stop_loss_pct": global_sl if user_overrode_sl else strategy_default_sl,
                    "take_profit_pct": global_tp if user_overrode_tp else strategy_default_tp,
                    "max_hold_days": global_mhd if user_overrode_mhd else strategy_default_mhd,
                    "slippage_pct": strategy_default_slippage,
                }
                logger.info('backtest', f'[V17] {sname}: SL={global_sl if user_overrode_sl else strategy_default_sl} TP={global_tp if user_overrode_tp else strategy_default_tp} (user_overrode_sl={user_overrode_sl} global_sl={global_sl} strategy_default_sl={strategy_default_sl})')

        # 初始化
        initial_cash = config.get("initial_cash", 1000000)
        self._initial_cash = initial_cash

        # 🔧 读取前端传入的佣金/滑点参数,覆盖硬编码常量
        commission_rate = config.get("commission_rate", None)
        if commission_rate is not None:
            self.BUY_COMMISSION = commission_rate
            self.SELL_COMMISSION = commission_rate
        stamp_duty_rate = config.get("stamp_duty_rate", None)
        if stamp_duty_rate is not None:
            self.STAMP_TAX = stamp_duty_rate
        self._slippage_pct = config.get("slippage_pct", 0.002)  # 默认0.2%

        top_n = config.get("top_n", 20)
        benchmark_code = config.get("benchmark", "000300.SH")

        # 解析排除规则
        exclude_rules = [ExcludeRule(r) for r in config.get("exclude", [])]
        # 【Bug修复:默认排除ST股,即使前端没传exclude字段】
        if not any(r == ExcludeRule.ST for r in exclude_rules):
            # 【P1-4修复:优先从global_filter_config读取exclude_st,兼容旧config路径】
            global_filter_cfg = config.get("global_filter_config", {})
            exclude_st = global_filter_cfg.get("exclude_st", config.get("exclude_st", True))
            if exclude_st:
                exclude_rules.append(ExcludeRule.ST)

        # 获取调仓日期 - 强制 daily,超短策略必须每日调仓
        rebalance_dates = await self.universe_mgr.get_rebalance_dates(
            config["start_date"],
            config["end_date"],
            "daily",  # 强制每日调仓,忽略可能错误的参数
        )

        if not rebalance_dates:
            return {"error": "No rebalance dates found"}

        # 获取所有交易日
        all_trade_dates = await self.universe_mgr.get_all_trade_dates(
            config["start_date"], config["end_date"]
        )

        if not all_trade_dates:
            return {"error": "No trade dates found"}

        # 🔴 关键修复:统一日期类型为字符串,避免类型不匹配
        # 确保 rebalance_dates 和 all_trade_dates 类型完全一致,用int匹配MongoDB存储格式
        all_trade_dates = [int(d) for d in all_trade_dates]
        rebalance_dates = [int(d) for d in rebalance_dates]
        rebalance_set = set(rebalance_dates)

        await self.log(f"📅 调仓日期: {len(rebalance_dates)} 天, 交易日: {len(all_trade_dates)} 天")
        await self.log(f"📋 调仓日列表: {', '.join(str(d) for d in rebalance_dates)}")

        # 🔍 数据一致性校验:检查行情数据和因子数据日期范围是否一致
        await self.log("🔍 开始数据一致性校验...")

        # 获取行情数据的最大日期(只查询一次)
        max_trade_date_pipeline = [
            {"$group": {"_id": None, "max_date": {"$max": "$trade_date"}}}
        ]
        result = await mongo_manager.aggregate(C.STOCK_DAILY, max_trade_date_pipeline)

        max_market_date = None
        max_factor_date = None
        if result and len(result) > 0:
            max_market_date = result[0].get("max_date")
            max_factor_date = max_market_date  # 同一个表,数据相同

        # 转换为整数比较
        req_start = int(config["start_date"])
        req_end = int(config["end_date"])

        warnings = []
        data_quality_issues = []
        if max_market_date and req_end > max_market_date:
            warnings.append(f"⚠️ 行情数据最新日期 {max_market_date},回测结束日期 {req_end},后{req_end - max_market_date}天行情数据缺失")
        if max_factor_date and req_end > max_factor_date:
            warnings.append(f"⚠️ 因子数据最新日期 {max_factor_date},回测结束日期 {req_end},后{req_end - max_factor_date}天因子数据缺失")

        # 🔧 数据完整性校验:检查回测区间内每天的股票数量是否一致
        # 如果某天只有几十只(而非5000+),说明那天数据缺失
        daily_count_pipeline = [
            {"$match": {"trade_date": {"$gte": req_start, "$lte": req_end}}},
            {"$group": {"_id": "$trade_date", "count": {"$sum": 1}}},
            {"$sort": {"_id": 1}}
        ]
        daily_counts = await mongo_manager.aggregate(C.STOCK_DAILY, daily_count_pipeline)
        if daily_counts:
            counts_list = [d["count"] for d in daily_counts]
            median_count = sorted(counts_list)[len(counts_list)//2] if counts_list else 0
            low_days = [d for d in daily_counts if d["count"] < median_count * 0.3 and d["count"] < 1000]
            if low_days:
                data_quality_issues.append(f"⚠️ {len(low_days)}天数据异常稀少(< 30%中位数{median_count}只)")
                for d in low_days[:5]:
                    data_quality_issues.append(f"   • {d['_id']}: 仅{d['count']}只(正常{median_count}只)")
                if len(low_days) > 5:
                    data_quality_issues.append(f"   • ...等{len(low_days)}天")

        if warnings:
            for warn in warnings:
                await self.log(warn)
            await self.log("⚠️  回测结果后段数据可能异常,建议缩短回测区间或同步数据后重试")
        if data_quality_issues:
            for issue in data_quality_issues:
                await self.log(issue)
            await self.log("⚠️  数据稀疏天的选股结果可能为空,不是策略问题而是数据缺失")
        if not warnings and not data_quality_issues:
            await self.log("✅ 数据一致性校验通过,数据覆盖完整回测区间")

        # 🔍 未来函数检查:验证所有因子都是基于日线可计算数据,不使用未来函数
        await self.log("🔍 未来函数检查:验证所有因子符合日线回测规则")
        future_factor_warnings = []

        # 检查日线回测中不可用的因子(如盘中实时数据)
        # 回测基于已收盘日线数据,无法获取盘中实时数据
        # 盘中因子如 limit_up_open_duration, limit_up_open_count 等在日线中不可用

        # 检查因子是否依赖盘中数据
        intraday_factors = ["limit_up_open_duration", "limit_up_open_count", "limit_up_open_amount", "limit_up_time"]
        for factor in intraday_factors:
            if factor in config.get("strategy_filters", {}):
                future_factor_warnings.append(f"⚠️  因子 {factor} 依赖盘中数据,日线回测中不可用")

        if future_factor_warnings:
            for warn in future_factor_warnings:
                await self.log(warn)
            await self.log("⚠️  建议: 回测应使用日线可计算的因子")
        else:
            await self.log("✅ 未来函数检查通过:所有因子都符合日线回测规则")

        # ==================== 因子完整性自动检测(2年回测跳过) ====================
        start_dt = int(config["start_date"])
        end_dt = int(config["end_date"])
        total_days = len(await self.universe_mgr.get_rebalance_dates(start_dt, end_dt, "daily"))
        if total_days > 100:
            await self.log(f"⚡ 大区间回测({total_days}天),跳过因子预检测,运行时动态计算")
        else:
            await self.log("🔍 因子完整性自动检测:检查核心策略因子...")
            # 【P0-1修复(V9):精简因子检测列表,仅检查回测核心策略必需的因子】
            # 48个因子逐个count_documents太慢(48次MongoDB查询),改为一次聚合检测
            # 核心策略因子 = 筛选条件用到的因子(排除纯技术指标和盘中因子)
            CORE_FACTOR_FIELDS = [
                "first_limit_up", "limit_up_yesterday", "limit_up_count",
                "turnover_rate", "volume_ratio", "circ_mv",
                "opening_pct_chg", "limit_down_yesterday", "open_above_limit_down",
                "pct_chg", "vol", "amount",
                "open", "high", "low", "close",
                "intraday_max_rise_pct", "intraday_open_rise_pct",
                "pullback_pct", "pullback_days",
            ]
            # 【P0-1修复(V9):用单次聚合替代48次count_documents,减少MongoDB查询从48次→1次】
            sample_date_pipeline = [
                {"$match": {"trade_date": {"$gte": start_dt, "$lte": end_dt}}},
                {"$limit": 100},  # 只采样100条即可判断因子是否存在
            ]
            sample_docs = await mongo_manager.aggregate(C.STOCK_DAILY, sample_date_pipeline)
            missing_fields = []
            if sample_docs:
                sample_fields = set()
                for doc in sample_docs:
                    sample_fields.update(doc.keys())
                for field in CORE_FACTOR_FIELDS:
                    if field not in sample_fields:
                        missing_fields.append(field)
            # 对采样中存在的字段,进一步验证有效率(可能存在但全NaN)
            if not missing_fields and sample_docs:
                # 抽查3个关键字段的有效率
                for check_field in ["opening_pct_chg", "intraday_max_rise_pct", "pullback_pct"]:
                    if check_field in sample_fields:
                        valid_in_sample = sum(1 for d in sample_docs if d.get(check_field) is not None and d.get(check_field) != 0)
                        if valid_in_sample == 0:
                            missing_fields.append(check_field)
            if missing_fields:
                await self.log(f"   ⚠️ 缺失因子 ({len(missing_fields)}个): {', '.join(missing_fields[:10])}")
                # 【V30:跳过因子自动计算(已知卡死问题),只输出告警】
                # 因子自动计算模块(factor_auto_compute.py)在5个月区间下会卡死
                # 运行时factor_engine.compute_factors会动态从MongoDB读取因子数据
                # 如果MongoDB中缺少因子(如opening_pct_chg),compute_factors内部会自动计算
                await self.log(f"   ⚠️ 因子自动计算已跳过(已知卡死问题),将在运行时动态计算")
                # # 【P0-1修复(V9):因子自动计算添加超时保护,避免阻塞回测主流程】
                # from .factor_auto_compute import auto_compute_factors
                # import asyncio as _asyncio
                # try:
                #     auto_result = await _asyncio.wait_for(
                #         auto_compute_factors(
                #             missing_fields=missing_fields, start_date=start_dt, end_date=end_dt,
                #             push_log_fn=push_log, task_id=task_id or '',
                #         ),
                #         timeout=120  # 2分钟超时,避免因子计算卡死回测
                #     )
                # except _asyncio.TimeoutError:
                #     await self.log(f"   ⚠️ 因子自动计算超时(>2分钟),跳过,将使用运行时动态计算")
                #     auto_result = {"computed": False}
                # except Exception as e:
                #     await self.log(f"   ⚠️ 因子自动计算异常: {e},跳过")
                #     auto_result = {"computed": False}
                # if auto_result.get("computed"):
                #     await self.log(f"   ✅ 因子自动计算成功!{auto_result.get('records_updated', 0):,} 条记录已更新")
            else:
                await self.log("   ✅ 核心策略因子完整性检查通过!")
        # ==================== 因子完整性检测结束 ====================

        # 加载基准数据
        benchmark_data = await self._load_benchmark_data(benchmark_code, start_dt, end_dt)

        # 初始化组合状态
        cash = initial_cash
        holdings: dict[str, int] = {}  # {ts_code: shares}
        stock_names: dict[str, str] = {}  # 股票名称缓存,确保始终有定义

        # 记录
        rebalance_records: list[RebalanceRecord] = []

        # 【修复#47:净值曲线追踪 - 逐日计算持仓市值】
        # 用于计算精确的每日盈亏、最大回撤、夏普比率等绩效指标
        net_value_series = []  # 净值序列
        daily_profit_list = []  # 每日盈亏
        drawdown_series = []   # 回撤序列
        daily_cash_list = []   # 【P1-3修复:每日现金占比(用于position_series)】
        peak_value = initial_cash  # 净值峰值
        last_net_value = initial_cash  # 上一日净值
        last_prices = {}  # 【修复:初始化last_prices,避免全强制空仓时NameError】

        # 逐日模拟: 当日信号当日执行(模拟盘中操作)

        # 逐日模拟
        total_days = len(all_trade_dates)

        await self.log(f"开始逐日回测,共 {total_days} 个交易日")

        # 【修复#4:进度推送Redis频道,前端实时接收进度】
        # 每 10% 进度推送一次
        last_pushed_progress = -1


        # ==================== 构建run_state ====================
        # 封装所有方法间传递的变量为dict
        run_state = {
            'config': config,
            'push_log': push_log,
            'task_id': task_id,
            'cash': cash,
            'holdings': holdings,
            'stock_names': stock_names,
            'rebalance_records': rebalance_records,
            'net_value_series': net_value_series,
            'daily_profit_list': daily_profit_list,
            'drawdown_series': drawdown_series,
            'daily_cash_list': daily_cash_list,
            'peak_value': peak_value,
            'last_net_value': last_net_value,
            'last_prices': last_prices,
            'all_trade_dates': all_trade_dates,
            'rebalance_dates': rebalance_dates,
            'rebalance_set': rebalance_set,
            'total_days': total_days,
            'last_pushed_progress': last_pushed_progress,
            'benchmark_data': benchmark_data,
            'initial_cash': initial_cash,
            'top_n': top_n,
            'start_dt': start_dt,
            'end_dt': end_dt,
            'req_start': req_start,
            'req_end': req_end,
            'exclude_rules': exclude_rules,
        }
        return run_state

    async def _process_rebalance_day(self, trade_date, idx: int, run_state: dict,
                                       sentiment_level: str, market_sentiment_score: int, limit_up_count: int, limit_down_count: int,
                                       force_empty_triggered: bool) -> dict:
        """调仓日处理: 股票池清洗、策略筛选、调仓执行、日志输出

        Args:
            trade_date: 当前交易日
            idx: 当前天数索引
            run_state: 运行时状态dict
            sentiment_level: 情绪等级
            limit_up_count: 涨停家数
            limit_down_count: 跌停家数
            force_empty_triggered: 是否触发强制空仓

        Returns:
            更新后的run_state
        """
        # 从run_state解包变量
        config = run_state['config']
        cash = run_state['cash']
        holdings = run_state['holdings']
        stock_names = run_state['stock_names']
        rebalance_records = run_state['rebalance_records']
        net_value_series = run_state['net_value_series']
        daily_profit_list = run_state['daily_profit_list']
        drawdown_series = run_state['drawdown_series']
        daily_cash_list = run_state['daily_cash_list']
        peak_value = run_state['peak_value']
        last_net_value = run_state['last_net_value']
        last_prices = run_state['last_prices']
        all_trade_dates = run_state['all_trade_dates']
        rebalance_dates = run_state['rebalance_dates']
        # 【P1-2修复(V15)】:存储为实例变量供_rebalance使用(超时强卖需计算交易日数)
        self._all_trade_dates = all_trade_dates
        # 【V30:P1-1】预构建交易日→索引映射，O(1)计算持仓天数
        # 【V31:只在映射为空时构建,避免每个交易日重复构建O(N)映射】
        if not self._trade_date_index_map:
            self._trade_date_index_map = {int(d): idx for idx, d in enumerate(all_trade_dates)}
        # 【V30:P1-4】设置交易日列表给FactorEngine,避免每次compute_factors做$group聚合
        # 【V31:只在缓存为空时构建,避免每个交易日重复构建O(N)缓存】
        if not self.factor_engine._prev_date_cache:
            self.factor_engine.set_trade_dates(all_trade_dates)
        rebalance_set = run_state['rebalance_set']
        total_days = run_state['total_days']
        benchmark_data = run_state['benchmark_data']
        exclude_rules = run_state['exclude_rules']
        initial_cash = run_state['initial_cash']

        # ==================== 调仓日完整流程 ====================
        await self.log(f"   📅 当前为调仓日,开始执行调仓逻辑")

        # 【修复#43:强制空仓时跳过选股计算,直接清仓】
        # 触发强制空仓时,不做任何选股、因子计算、策略筛选,直接清仓
        if force_empty_triggered:
            await self.log(f"")
            await self.log(f"   ┌───────────────────────────────────────────────────────")
            await self.log(f"   │ 🔴 【强制空仓执行】")
            await self.log(f"   ├───────────────────────────────────────────────────────")

            if holdings and len(holdings) > 0:
                prices_for_sell = await self._get_prices(set(holdings.keys()), trade_date)
                sell_count = 0
                for code in list(holdings.keys()):
                    if holdings[code] > 0 and code in prices_for_sell:
                        # 【Phase1-T+1】强制空仓也要递守T+1: 当日买入不可卖
                        buy_dt = self._cost_basis_date.get(code)
                        if buy_dt is not None and buy_dt == trade_date:
                            await self.log(f"   │  🔒 T+1限制: {code} 当日买入不可卖(强制空仓跳过)")
                            continue
                        price = prices_for_sell[code].get('open', 0) or prices_for_sell[code]['close']
                        # 【P0-4修复(V16)】:强制空仓用open价(开盘看到极端行情立即卖出)
                        # 但open=0(停牌)或close=0时回退到_last_valid_price,不卖0元
                        if price <= 0:
                            price = getattr(self, '_last_valid_price', {}).get(code, 0)
                        if price <= 0:
                            # 无法获取有效价格,跳过该股不卖(保留持仓)
                            await self.log(f"   │  ⚠️ {code}停牌且无有效价,跳过卖出")
                            continue
                        shares = holdings[code]
                        slippage_pct = 0  # 【V29:should_apply_slippage('强制空仓')=False,此处已确认是强制空仓场景】
                        sell_price_adj = price
                        gross_amount = shares * sell_price_adj
                        commission = max(gross_amount * self.SELL_COMMISSION, self.MIN_COMMISSION)
                        stamp_tax = gross_amount * self.STAMP_TAX
                        net_amount = gross_amount - commission - stamp_tax
                        cash += net_amount
                        sell_count += 1
                        # 【P1-3修复(第十二轮):强制空仓卖出记录补上strategy_name】
                        _fs_strategy = self._get_strategy_for_stock(code)
                        rebalance_records.append(RebalanceRecord(
                            date=str(trade_date),
                            action="sell",
                            ts_code=code,
                            shares=shares,
                            price=price,
                            amount=net_amount,
                            reason="强制空仓",
                            strategy_name=_fs_strategy,
                            sentiment=sentiment_level
                        ))
                        holdings.pop(code, None)
                # 【P1-7修复:强制空仓清仓时清理cost_basis】
                # 【V55-BUG-006修复:同时清理stock_to_strategy,避免强制空仓日残留脏数据】
                if self._cost_basis:
                    for code in list(self._cost_basis.keys()):
                        if code not in holdings or holdings.get(code, 0) <= 0:
                            del self._cost_basis[code]
                            if code in self._cost_basis_date:
                                del self._cost_basis_date[code]
                            self.stock_to_strategy.pop(code, None)
                holdings = {code: shares for code, shares in holdings.items() if shares > 0}
                await self.log(f"   │  ✅ 已执行强制清仓,卖出 {sell_count} 只持仓")
                await self.log(f"   │  💵 清仓后现金:{cash:,.2f} 元")
            else:
                await self.log(f"   │  ⚪ 当前无持仓,无需卖出")

            await self.log(f"   │  ⏭️  强制空仓规则生效,不开新仓")
            await self.log(f"   └───────────────────────────────────────────────────────")

            # 【修复#6:强制空仓也输出每日收盘汇总,continue前加上】
            await self._print_daily_summary(trade_date, len(holdings), cash)
            # 【P0修复:continue前记录净值】
            last_net_value, peak_value = await self._record_daily_net_value(
                trade_date, holdings, cash, last_net_value, peak_value,
                net_value_series, daily_profit_list, drawdown_series, daily_cash_list,
                last_prices=last_prices)
            # [重构] continue→return: 跳过当日剩余处理
            self._update_run_state(run_state,
                cash=cash, holdings=holdings, rebalance_records=rebalance_records,
                last_prices=last_prices, stock_names=stock_names,
                net_value_series=net_value_series, daily_profit_list=daily_profit_list,
                drawdown_series=drawdown_series, daily_cash_list=daily_cash_list,
                peak_value=peak_value, last_net_value=last_net_value)
            return run_state

        # ==================== 正常调仓流程 ====================
        # 1. 获取当日股票池
        universe_raw = await self.universe_mgr.get_universe(
            UniverseType.ALL_A,
            trade_date,
            exclude_rules=[],  # 不应用任何排除规则,用于统计
        )
        universe = await self.universe_mgr.get_universe(
            UniverseType.ALL_A,
            trade_date,
            exclude_rules,
        )

        # 真实统计各类剔除数量
        st_stocks = await self.universe_mgr._get_st_stocks()
        new_stocks = await self.universe_mgr._get_new_stocks(trade_date)
        st_count = len(st_stocks & universe_raw)
        new_stock_count = len(new_stocks & universe_raw)

        # 流动性过滤统计
        low_liquidity_cursor = mongo_manager.find_many(
            C.STOCK_DAILY,
            {
                "trade_date": int(trade_date),
                "ts_code": {"$in": list(universe)},
                "amount": {"$lt": 5000}  # 5000千元=500万元,与流动性门槛对齐(amount单位:千元)
            },
            {"ts_code": 1}
        )
        low_liquidity_list = [doc["ts_code"] for doc in await low_liquidity_cursor]
        low_liquidity_set = set(low_liquidity_list)
        low_liquidity_count = len(low_liquidity_set)
        universe -= low_liquidity_set

        # ✅ 统一打印股票池和清洗信息
        await self._print_stock_pool_and_cleaning(trade_date, universe, st_count, new_stock_count, low_liquidity_count)

        # 2. 计算因子
        if not universe:
            await self.log(f"   ⚠️  当日无符合条件的股票,跳过调仓")
            await self._print_daily_summary(trade_date, len(holdings), cash)
            # 【P0修复:continue前记录净值】
            last_net_value, peak_value = await self._record_daily_net_value(
                trade_date, holdings, cash, last_net_value, peak_value,
                net_value_series, daily_profit_list, drawdown_series, daily_cash_list,
                last_prices=last_prices)
            # [重构] continue→return: 跳过当日剩余处理
            self._update_run_state(run_state,
                cash=cash, holdings=holdings, rebalance_records=rebalance_records,
                last_prices=last_prices, stock_names=stock_names,
                net_value_series=net_value_series, daily_profit_list=daily_profit_list,
                drawdown_series=drawdown_series, daily_cash_list=daily_cash_list,
                peak_value=peak_value, last_net_value=last_net_value)
            return run_state

        ultra_short_factors = [
            {"name": "open_below_limit"},
            {"name": "pct_chg"},
            {"name": "volume_ratio"},
            {"name": "first_limit_up"},
            {"name": "limit_up_yesterday"},
            {"name": "limit_up_open_amount"},
            {"name": "circ_mv"},
            {"name": "limit_up_open_count"},
            {"name": "hot_sector"},
            {"name": "limit_up_time"},
            {"name": "limit_up_count"},
            {"name": "limit_up_open_duration"},
            {"name": "turnover_rate"},
            {"name": "market_leader"},
            {"name": "pullback_pct"},
            {"name": "pullback_days"},
            {"name": "pullback_ma5"},
            {"name": "limit_down_yesterday"},
            {"name": "open_above_limit_down"},
            {"name": "limit_down_open_amount"},
            {"name": "rise_after_limit_down"},
            {"name": "sentiment_score"},
            {"name": "opening_pct_chg"},  # 竞价涨幅(9:25可知,非未来函数)
            {"name": "is_limit_up"},  # 涨停开板策略筛选is_limit_up=0(今日未封住)
            # 【V18未来函数修复】：添加T-1因子,替代T日收盘数据
            {"name": "pct_chg_prev"},  # T-1收盘涨幅(替代T日pct_chg,消除未来函数)
            {"name": "volume_ratio_prev"},  # T-1量比(替代T日volume_ratio,消除未来函数)
            {"name": "turnover_rate_prev"},  # T-1换手率(替代T日turnover_rate)
            {"name": "circ_mv_prev"},  # T-1流通市值(替代T日circ_mv)
        ]
        if "factors" not in config:
            config["factors"] = []
        config["factors"].extend([f for f in ultra_short_factors if f not in config["factors"]])

        factor_df = await self.factor_engine.compute_factors(
            universe, trade_date, config["factors"]
        )
        await self.log(f"   ✅ 因子计算完成,共 {len(factor_df)} 条记录")
        # 【P2-6:因子数据为空时告警】
        if len(factor_df) == 0:
            await self.log(f"   ⚠️  【重要告警】因子数据为空!该日期无任何股票数据,全天空仓")
            await self._print_daily_summary(trade_date, len(holdings), cash)
            # 【P0修复:continue前记录净值】
            last_net_value, peak_value = await self._record_daily_net_value(
                trade_date, holdings, cash, last_net_value, peak_value,
                net_value_series, daily_profit_list, drawdown_series, daily_cash_list,
                last_prices=last_prices)
            # [重构] continue→return: 跳过当日剩余处理
            # 【P0-3修复(第十一轮):跳过后续逻辑,避免空DataFrame上无意义运算】
            self._update_run_state(run_state,
                cash=cash, holdings=holdings, rebalance_records=rebalance_records,
                last_prices=last_prices, stock_names=stock_names,
                net_value_series=net_value_series, daily_profit_list=daily_profit_list,
                drawdown_series=drawdown_series, daily_cash_list=daily_cash_list,
                peak_value=peak_value, last_net_value=last_net_value)
            return run_state
        # 🔍 因子数据质量检查(P3-9优化:增强检查,缺失核心因子时中止)
        selected_strategies = config.get("selected_strategies", [])
        enabled_strategy_names = [s.get("name", "") for s in selected_strategies] if selected_strategies else []

        quality_checker = FactorQualityChecker(strict_mode=False)
        quality_report = quality_checker.check_factor_quality(
            factor_df, config["factors"], enabled_strategy_names, str(trade_date)
        )

        # 输出质量报告
        for line in quality_checker.get_quality_summary(quality_report).split('\n'):
            await self.log(f"   {line}")

        # 判断是否需要中止回测
        should_abort, abort_reason = quality_checker.should_abort_backtest(quality_report)
        if should_abort:
            await self.log(f"   ❌ 【中止回测】{abort_reason}")
            await self.log(f"   💡 建议:先运行因子同步任务补全数据后再重试")
            await self._print_daily_summary(trade_date, len(holdings), cash)
            last_net_value, peak_value = await self._record_daily_net_value(
                trade_date, holdings, cash, last_net_value, peak_value,
                net_value_series, daily_profit_list, drawdown_series, daily_cash_list,
                last_prices=last_prices)
            self._update_run_state(run_state,
                cash=cash, holdings=holdings, rebalance_records=rebalance_records,
                last_prices=last_prices, stock_names=stock_names,
                net_value_series=net_value_series, daily_profit_list=daily_profit_list,
                drawdown_series=drawdown_series, daily_cash_list=daily_cash_list,
                peak_value=peak_value, last_net_value=last_net_value)
            return run_state

        # 为缺失的因子应用默认值(避免后续计算出错)
        if quality_report.missing_factors or quality_report.empty_factors:
            all_missing = quality_report.missing_factors + quality_report.empty_factors
            quality_checker.apply_factor_defaults(factor_df, all_missing)
            await self.log(f"   🔧 已为 {len(all_missing)} 个缺失因子应用默认值")

        # ✅ 情绪周期映射: sentiment_period_in
        # 【P0-1修复】不再依赖factor_df中的sentiment_score(全为0.5填充值,std=0→跳过)
        # 改用市场级情绪评分(market_sentiment_score),来自_print_market_environment的计算:
        #   sentiment_score = (涨停数 - 跌停数) + 大盘涨跌幅*10 + 50, 范围[0,100]
        # 所有个股共享同一个市场情绪周期,这是正确语义:情绪是市场属性不是个股属性
        if self._risk_config.get("enable_sentiment_cycle", True):
            # 【P2-8修复:直接用market_sentiment_score映射,逻辑与_calc_sentiment_score一致】
            if market_sentiment_score >= 70:
                market_sentiment_period = 'rising'
            elif market_sentiment_score >= 40:
                market_sentiment_period = 'chaos'
            else:
                market_sentiment_period = 'depression'
            factor_df['sentiment_period_in'] = market_sentiment_period
            await self.log(f"   ✅ 情绪周期计算完成(市场级): score={market_sentiment_score} → {market_sentiment_period}")
        else:
            await self.log(f"   i️  情绪周期算法已关闭,跳过情绪周期计算")

        await self.log(f"   🎯 【{trade_date}】多策略联合筛选开始")
        await self.log(f"   ============================================================")
        await self.log(f"")

        all_candidates = set()
        # 【修复#45:记录每只股票来自哪个策略,用于调仓日志显示】
        # 【P0-3修复:不清空持仓中股票的映射,否则次日卖出时找不到策略级止损参数】
        # 只清空已不再持仓的股票映射(避免无限增长)
        if self.stock_to_strategy is None:
            self.stock_to_strategy = {}
        stock_to_strategy = self.stock_to_strategy
        # 清理已卖出股票的映射(不在holdings中的)
        _current_holdings = set(holdings.keys()) if holdings else set()
        _to_remove = [k for k in stock_to_strategy if k not in _current_holdings]
        for k in _to_remove:
            del stock_to_strategy[k]

        selected_strategies = config.get("selected_strategies", [])
        selected_strategy_names = [s["name"] for s in selected_strategies] if selected_strategies else []

        # 【修复#7:统一调用策略条件构建方法,消除重复定义】
        strategy_configs = {}
        # 遍历所有传入的策略配置,动态构建筛选条件
        for s in selected_strategies:
            strategy_name = s.get("name", s.get("id", "未知策略"))
            # 🔧 统一merge默认值: 用户参数优先, 缺失从STRATEGY_CONFIGS取
            strategy_id = s.get("id", "")
            params = merge_strategy_params(strategy_id, s.get("params", {}))
            s["params"] = params  # 回写, 让后续_build_strategy_filter_conditions也能用
            strategy_configs[strategy_name] = self._build_strategy_filter_conditions(strategy_name, params)

        # ✅ One Function, One Format! 所有5个策略统一走同一个打印函数!
        # 🚫 业务逻辑代码中绝对不允许直接出现 await self.log()!
        all_candidates = set()
        for s in selected_strategies:
            strategy_name = s.get("name", s.get("id", "未知策略"))
            # params已在上方merge过默认值
            params = s.get("params", {})

            # 【P2-B修复:删除重复的参数打印逻辑,统一走 _print_single_strategy_filtering】
            # 之前这里有80行重复打印代码,与 _print_single_strategy_filtering 完全一致
            # 且默认值不一致(如半路追涨max_rise_pct这里写0.05,_print_single写0.05,但ultra_short写0.07)

            # 【V36:半路追涨冰点期过滤】情绪score<40时跳过,3笔0%胜率-12.5%→0笔冰点亏损
            if strategy_name == "半路追涨" and market_sentiment_score is not None and market_sentiment_score < 40:
                await self.log(f"   ❄️ 【半路追涨】冰点期(情绪{market_sentiment_score}分<40),跳过")
                if strategy_name not in self._strategy_signal_stats:
                    self._strategy_signal_stats[strategy_name] = {"total_days": 0, "signal_days": 0}
                self._strategy_signal_stats[strategy_name]["total_days"] += 1
                continue

            # 统一调用策略筛选+打印
            candidates = await self._print_single_strategy_filtering(
                strategy_name,
                params,
                [],
                factor_df,
                strategy_configs,
                selected_strategy_names
            )
            all_candidates.update(candidates)
            # 🔧 因子缺失告警:记录每个策略每天的候选数
            # _strategy_signal_stats initialized in __init__
            if strategy_name not in self._strategy_signal_stats:
                self._strategy_signal_stats[strategy_name] = {"total_days": 0, "signal_days": 0}
            self._strategy_signal_stats[strategy_name]["total_days"] += 1
            if candidates:
                self._strategy_signal_stats[strategy_name]["signal_days"] += 1
            # 【修复#45+P1-1:记录每只股票来自哪个策略,支持多策略选同股】
            # 存策略列表(而非覆盖),买入价取最低价(最保守)
            for code in candidates:
                if code not in stock_to_strategy:
                    stock_to_strategy[code] = []
                if strategy_name not in stock_to_strategy[code]:
                    stock_to_strategy[code].append(strategy_name)

        # ✅ 所有策略筛选完成!One Function, One Format!
        # 🚫 业务逻辑代码中不再有任何 await self.log() 调用!
        # 📊 总候选: {len(all_candidates)} 只股票

        # 🔧 策略轮动机制:根据历史月度收益动态调整权重已经在权重计算阶段处理
        # 当前改进:每个策略独立筛选,只影响选股结果不影响权重,权重调整后分配还是基于等权基础

        if len(all_candidates) == 0:
            await self.log(f"   ⚠️  当日无符合条件的交易标的,跳过调仓")
            # 【修复:当日无候选时,输出每日收盘汇总后continue到下一交易日】
            await self._print_daily_summary(trade_date, len(holdings), cash)
            # 【P0修复:continue前记录净值】
            last_net_value, peak_value = await self._record_daily_net_value(
                trade_date, holdings, cash, last_net_value, peak_value,
                net_value_series, daily_profit_list, drawdown_series, daily_cash_list,
                last_prices=last_prices)
            # [重构] continue→return: 跳过当日剩余处理
            self._update_run_state(run_state,
                cash=cash, holdings=holdings, rebalance_records=rebalance_records,
                last_prices=last_prices, stock_names=stock_names,
                net_value_series=net_value_series, daily_profit_list=daily_profit_list,
                drawdown_series=drawdown_series, daily_cash_list=daily_cash_list,
                peak_value=peak_value, last_net_value=last_net_value)
            return run_state

        # 【竞价过滤】第5层筛选
        # 规则: 排除极端竞价情况 - 大幅高开(>7%)或大幅低开(<-5%)
        # ⚠️ 不可用opening_pct_chg要求0.5%~7%做近似!
        #   实测: 半路追涨76%候选的竞价涨幅在-2%~0.5%(低开盘中涨),0.5%门槛会杀掉核心候选
        # 正确做法: 只排除极端值,保留正常区间
        if self._risk_config.get("enable_auction_filter", True) and len(all_candidates) > 0:
            await self.log("")
            await self.log(f"   📊 【竞价过滤】启用竞价过滤,当前 {len(all_candidates)} 个候选")

            # 从stock_bid_auction获取真实竞价数据
            auction_data = await mongo_manager.find_many(
                "stock_bid_auction",
                {"trade_date": int(trade_date)},
                projection={"ts_code": 1, "auction_pct_chg": 1, "auction_volume": 1, "unmatched_volume": 1}
            )

            if auction_data:
                # ✅ 有真实竞价数据 → 用原始规则(0.5%~7% + 成交量>0 + 未匹配量>0)
                auction_map = {x.get("ts_code", ""): x for x in auction_data if x.get("ts_code")}
                original_count = len(all_candidates)
                filtered_candidates = []
                for code in all_candidates:
                    auction = auction_map.get(code)
                    if not auction:
                        filtered_candidates.append(code)
                        continue
                    pct = auction.get("auction_pct_chg", 0)
                    vol = auction.get("auction_volume", 0)
                    unmatched_vol = auction.get("unmatched_volume", 0)
                    if 0.5 <= pct <= 7 and vol > 0 and unmatched_vol > 0:
                        filtered_candidates.append(code)
                all_candidates = set(filtered_candidates)
                await self.log(f"   ✅ 竞价过滤(真实数据)完成: {original_count} → {len(all_candidates)}")
            else:
                # 无真实竞价数据 → 用opening_pct_chg做宽松过滤(仅排除极端值)
                # 【P1-5修复(V20):预构建ts_code→opening_pct映射,避免逐行O(N*M)查找】
                if 'opening_pct_chg' in factor_df.columns:
                    _opn_map = dict(zip(factor_df['ts_code'], factor_df['opening_pct_chg']))
                else:
                    _opn_map = {}
                original_count = len(all_candidates)
                filtered_candidates = []
                for code in all_candidates:
                    opening_pct = _opn_map.get(code)
                    if opening_pct is None or (isinstance(opening_pct, float) and math.isnan(opening_pct)):
                        filtered_candidates.append(code)
                        continue
                    # 【V37修复:恢复V35竞价过滤阈值,V36收窄导致收益暴降40.5%】
                    # V36问题: 低开<-3%排除跌停翘板核心候选(开盘-3%~-9%)
                    # V36问题: 高开>5%排除5-7%高开好信号(冲高回落保护可覆盖)
                    # V35原阈值: 高开>7%/低开<-5% 是经过回测验证的最优值
                    if opening_pct > 7 or opening_pct < -5:
                        pass  # 排除极端竞价
                    else:
                        filtered_candidates.append(code)
                all_candidates = set(filtered_candidates)
                await self.log(f"   ✅ 竞价过滤(日线近似: 排除高开>7%/低开<-5%)完成: {original_count} → {len(all_candidates)}")

            if len(all_candidates) == 0:
                await self.log(f"   ⚠️  竞价过滤后无候选,跳过调仓")
                # 【P0修复:提前返回前必须调用日终汇总,否则日志缺失收盘信息】
                await self._print_daily_summary(trade_date, len(holdings), cash)
                self._update_run_state(run_state,
                    cash=cash, holdings=holdings, rebalance_records=rebalance_records,
                    last_prices=last_prices, stock_names=stock_names,
                    net_value_series=net_value_series, daily_profit_list=daily_profit_list,
                    drawdown_series=drawdown_series, daily_cash_list=daily_cash_list,
                    peak_value=peak_value, last_net_value=last_net_value)
                return run_state

        # 【P0-A修复:以下调仓逻辑必须与竞价过滤if平级,不能在if内部!】
        # 否则 enable_auction_filter=False 时不执行任何调仓!

        # 【P1-2修复:板块集中度过滤 - 同板块候选过多时只保留评分最高的N只】
        # 之前只有开关和日志,从未实际执行过滤逻辑
        if self._risk_config.get("enable_sector_concentration", True) and len(all_candidates) > 0:
            try:
                sector_top_n = self._risk_config.get("sector_concentration_top_n", 3)
                # 从stock_basic获取行业信息(factor_df无industry列)
                industry_map = dict(self._industry_map_cache)  # 【P1-3修复(V14)】复用缓存
                uncached_codes = [c for c in all_candidates if c not in industry_map]
                if uncached_codes:
                    industry_docs = await mongo_manager.find_many(
                        C.STOCK_BASIC,
                        {"ts_code": {"$in": uncached_codes}},
                        {"ts_code": 1, "industry": 1}
                    )
                    for d in industry_docs:
                        industry_map[d['ts_code']] = d.get('industry', 'unknown')
                        self._industry_map_cache[d['ts_code']] = d.get('industry', 'unknown')  # 更新缓存

                if industry_map:
                    sector_counts = {}
                    filtered_by_sector = set()
                    # 【P1-3修复(V12):用volume_ratio排序替代pct_chg,消除未来函数】
                    # pct_chg是收盘涨跌幅(收盘后才知道),实盘选股时无法使用
                    # volume_ratio(量比)在开盘时已确定(基于前5日均量),是可观测因子
                    # 量比高=市场关注度高=更强势,在同一行业内优先选量比高的
                    if 'volume_ratio' in factor_df.columns:
                        # 【P1-2修复(V19):预计算volume_ratio映射,避免逐行O(N*M)扫描factor_df】
                        # 旧: 每个候选股做factor_df[factor_df['ts_code']==code]→全表扫描
                        # 新: 一次性构建ts_code→volume_ratio的dict→O(1)查找
                        _vr_map = dict(zip(factor_df['ts_code'], factor_df['volume_ratio']))
                        scored_candidates = []
                        for code in all_candidates:
                            score = _vr_map.get(code, 0)
                            if isinstance(score, float) and not math.isnan(score):
                                scored_candidates.append((code, score))
                            else:
                                scored_candidates.append((code, 0))
                        scored_candidates.sort(key=lambda x: x[1], reverse=True)
                        sorted_candidates = [c[0] for c in scored_candidates]
                    else:
                        sorted_candidates = sorted(all_candidates)
                    # 按行业分组,每行业最多保留sector_top_n只(已按评分降序)
                    for code in sorted_candidates:
                        industry = industry_map.get(code, 'unknown')
                        sector_counts[industry] = sector_counts.get(industry, 0) + 1
                        if sector_counts[industry] <= sector_top_n:
                            filtered_by_sector.add(code)
                    if len(filtered_by_sector) < len(all_candidates):
                        await self.log(f"   🏢 板块集中度过滤: {len(all_candidates)} → {len(filtered_by_sector)} (每行业最多{sector_top_n}只)");
                        all_candidates = filtered_by_sector
            except Exception as e:
                logger.warn('BACKTEST', f"板块集中度过滤失败: {e}")

        # ==========================================
        # 【信号延迟模式核心逻辑】
        # ==========================================
        # 旧模式: T日因子→T日选股→T日买入 (前瞻偏差)
        # 新模式: T日因子→T日选股→存入prev→用T-1选股结果在T日买入
        # ==========================================

        # 计算今日的目标权重(基于今日因子,为次日买入准备)
        today_target_weights = self._compute_weights(
            list(all_candidates),
            factor_df,
            self.weight_method,
        )

        # 🔧 新增:大盘 MA60 过滤 - 大盘跌破 MA60 整体降低仓位 50%(可配置开关)
        if self._risk_config.get("enable_ma60_filter", True):
            try:
                # 【P0-1修复(V20):INDEX_DAILY无ma60字段,改为从最近60个交易日close计算】
                # 旧bug: 查index_daily的ma60字段→始终None→MA60过滤从不触发
                # 新: 查询最近60个交易日的close,计算均值作为MA60
                # 优化: 用缓存避免每日重复查询(只需查一次当天的close+前59天)
                # 【P0-2修复(V22):缓存{trade_date: (ma60, current_close)}元组,避免缓存命中时多查一次MongoDB】
                _trade_date_int = int(trade_date)
                cached_ma60_data = self._ma60_cache.get(_trade_date_int)
                ma60 = None
                current_close = None
                if cached_ma60_data is not None:
                    ma60, current_close = cached_ma60_data  # 缓存命中,直接使用
                if ma60 is None:
                    index_close_docs = await mongo_manager.find_many(
                        C.INDEX_DAILY,
                        {"ts_code": "000001.SH", "trade_date": {"$lte": _trade_date_int}},
                        {"close": 1, "trade_date": 1},
                        sort=[("trade_date", -1)],
                        limit=60
                    )
                    if index_close_docs and len(index_close_docs) >= 20:
                        index_close_docs.sort(key=lambda x: x["trade_date"])
                        close_list = [d["close"] for d in index_close_docs]
                        ma60 = sum(close_list) / len(close_list)
                        current_close = close_list[-1]
                        self._ma60_cache[_trade_date_int] = (ma60, current_close)  # 缓存元组
                # 【P0-2修复(V22):缓存已包含current_close,不再需要额外查询】
                if ma60 and current_close:
                    if current_close < ma60:
                        for code in today_target_weights:
                            today_target_weights[code] = today_target_weights[code] * 0.5
                        await self.log(f"   📉 大盘跌破 MA60({ma60:.0f}),当前{current_close:.0f},整体仓位降低 50%")
                    else:
                        logger.debug('BACKTEST', f'大盘站上 MA60({ma60:.0f}),当前{current_close:.0f}')
            except Exception as e:
                logger.warn('BACKTEST', f"均线MA60仓位调整检查失败: {e}")

        # 当日选股当日执行
        execute_weights = today_target_weights
        execute_sentiment = sentiment_level
        execute_force_empty = force_empty_triggered
        await self.log(f"   📋 执行今日选股结果: {len(execute_weights)}只候选")

        # 计算进度
        total_rebalance_days = len(rebalance_dates)
        current_day_idx = rebalance_dates.index(trade_date) + 1
        progress = (current_day_idx / total_rebalance_days) * 100
        await self.log(f"   📅 当日调仓进度: {progress:.2f}% ({current_day_idx}/{total_rebalance_days}天)")
        await self.log(f"   💲 正在获取股票价格...")
        prices = await self._get_prices(
            set(holdings.keys()) | set(execute_weights.keys()),
            trade_date,
        )

        # 保存最后一次价格,用于计算最终市值
        last_prices = prices

        await self.log(f"   ✅ 获取到 {len(prices)} 只股票的价格")

        # 如果没有任何股票获取到价格,跳过本次调仓
        if len(prices) == 0 and len(holdings) == 0:
            await self.log(f"   ⚠️  没有任何股票获取到当日价格,跳过调仓")
            # 【P0修复:continue前记录净值】
            last_net_value, peak_value = await self._record_daily_net_value(
                trade_date, holdings, cash, last_net_value, peak_value,
                net_value_series, daily_profit_list, drawdown_series, daily_cash_list,
                last_prices=last_prices)
            # [重构] continue→return: 跳过当日剩余处理
            self._update_run_state(run_state,
                cash=cash, holdings=holdings, rebalance_records=rebalance_records,
                last_prices=last_prices, stock_names=stock_names,
                net_value_series=net_value_series, daily_profit_list=daily_profit_list,
                drawdown_series=drawdown_series, daily_cash_list=daily_cash_list,
                peak_value=peak_value, last_net_value=last_net_value)
            return run_state

        # 5. 执行调仓(用execute_weights, 可能是T-1日的选股结果)
        await self.log(f"   🔄 正在执行调仓操作...")
        cash, holdings, records = self._rebalance(
            trade_date, execute_weights, cash, holdings, prices, execute_sentiment
        )
        rebalance_records.extend(records)

        # 获取股票名称
        stock_names = await self._get_stock_names([r.ts_code for r in records])

        # 🔧 内存优化: 释放不再需要的因子数据和目标权重
        if 'factor_df' in locals():
            del factor_df
        if 'today_target_weights' in locals():
            del today_target_weights
        if 'execute_weights' in locals():
            del execute_weights
        gc.collect()

        # 输出调仓记录(带股票名称 + 完整原因描述)
        if len(records) > 0:
            await self.log("")
            await self.log(f"   📝 【当日调仓记录】:")
            await self.log(f"   { '-' * 100}")
            await self.log(f"   | {'方向':<6} {'日期':<10} {'名称':<8} {'代码':<12} {'股数':<6} {'价格':<8} {'原因'} ")
            await self.log(f"   { '-' * 100}")

            for record in records:
                name = stock_names.get(record.ts_code, record.ts_code.split('.')[0])
                ts_code = record.ts_code
                direction = "买入" if record.action == 'buy' else "卖出"
                # 完善原因说明翻译,更容易阅读理解
                if record.reason == "rebalance":
                    if direction == "买入":
                        # 【修复#45:买入reason带上具体策略名称】
                        sname_raw = stock_to_strategy.get(ts_code, "策略选股")
                        strategy_name = sname_raw[0] if isinstance(sname_raw, list) and len(sname_raw) > 0 else sname_raw
                        reason_desc = f"{strategy_name}调入"
                    else:
                        reason_desc = "调仓调出"
                elif record.reason == "not_in_target":
                    reason_desc = "不再符合选股条件"
                else:
                    reason_desc = record.reason

                # 添加日期信息
                date = record.date
                icon = "🔹" if record.action == 'buy' else "🔻"
                await self.log(f"   | {icon} {direction:<6} {date:<10} {name:<8} {ts_code:<12} {record.shares:<6} {record.price:<8.2f} {reason_desc:<}")
            await self.log(f"   { '-' * 100}")


        # 【V29重构:调仓日无交易时,委托给统一方法检查止损止盈/冲高回落/超时】
        if len(records) == 0 and holdings and len(holdings) > 0:
            enable_sl = self._risk_config.get('enable_stop_loss', True)
            enable_tp = self._risk_config.get('enable_take_profit', True)
            if enable_sl or enable_tp:
                _sl_tp_prices = await self._get_prices(set(holdings.keys()), trade_date)
                forced_sell_codes = []
                forced_sell_prices = {}
                forced_sell_codes_set = set()
                # 统一检查:冲高回落/利润保护/止损/止盈/超时
                forced_sell_codes, forced_sell_prices, forced_sell_codes_set = \
                    await self._check_and_execute_forced_sells(
                        trade_date, holdings, _sl_tp_prices,
                        forced_sell_codes, forced_sell_prices, forced_sell_codes_set,
                        check_timeout=True)
                # 统一执行卖出
                cash = await self._execute_forced_sells(
                    trade_date, holdings, cash, forced_sell_codes,
                    forced_sell_prices, _sl_tp_prices, rebalance_records,
                    log_prefix='调仓日')
                last_prices = _sl_tp_prices if forced_sell_codes else last_prices
        # 【P0修复:统一调用净值记录函数,避免continue跳过】
        last_net_value, peak_value = await self._record_daily_net_value(
            trade_date, holdings, cash, last_net_value, peak_value,
            net_value_series, daily_profit_list, drawdown_series, daily_cash_list,
            last_prices=last_prices, prices=prices,
            rebalance_set=rebalance_set)
        # last_net_value已由_record_daily_net_value更新

        # ==================== 每日收盘汇总(每天必须输出)====================
        # 无论调仓日还是非调仓日,每天都要有完整的日志结尾
        await self.log(f"")
        await self.log(f"═══════════════════════════════════════════════════════════════")
        await self.log(f"📅 【第 {idx+1}/{total_days} 天】处理完成: {trade_date}")
        await self.log(f"   💵 当日持仓: {len(holdings)} 只股票, 现金剩余: {cash:,.2f} 元")
        await self.log(f"═══════════════════════════════════════════════════════════════")

        # ==================== 更新run_state ====================
        self._update_run_state(run_state,
            cash=cash, holdings=holdings, stock_names=stock_names,
            rebalance_records=rebalance_records, net_value_series=net_value_series,
            daily_profit_list=daily_profit_list, drawdown_series=drawdown_series,
            daily_cash_list=daily_cash_list, peak_value=peak_value,
            last_net_value=last_net_value, last_prices=last_prices)
        return run_state

    async def _process_non_rebalance_day(self, trade_date, idx: int, run_state: dict,
                                            sentiment_level: str) -> dict:
        """非调仓日处理: 止损止盈检查、强制卖出、日志输出

        当调仓日无交易时也走此路径,进行止损止盈检查和持仓显示

        Args:
            trade_date: 当前交易日
            idx: 当前天数索引
            run_state: 运行时状态dict
            sentiment_level: 情绪等级

        Returns:
            更新后的run_state
        """
        # 从run_state解包变量
        config = run_state['config']
        cash = run_state['cash']
        holdings = run_state['holdings']
        rebalance_records = run_state['rebalance_records']
        last_prices = run_state['last_prices']
        total_days = run_state['total_days']
        rebalance_set = run_state['rebalance_set']
        net_value_series = run_state['net_value_series']
        daily_profit_list = run_state['daily_profit_list']
        drawdown_series = run_state['drawdown_series']
        daily_cash_list = run_state['daily_cash_list']
        peak_value = run_state['peak_value']
        last_net_value = run_state['last_net_value']
        stock_names = run_state['stock_names']
        all_trade_dates = run_state['all_trade_dates']
        initial_cash = run_state['initial_cash']

        # 【V29重构:非调仓日止损止盈+超时检查,委托给统一方法】
        enable_sl = self._risk_config.get('enable_stop_loss', True)
        enable_tp = self._risk_config.get('enable_take_profit', True)
        forced_sell_codes = []
        forced_sell_codes_set = set()
        forced_sell_prices = {}
        _prices_for_display = {}
        if (enable_sl or enable_tp) and holdings:
            _sl_tp_prices = await self._get_prices(set(holdings.keys()), trade_date)
            # 统一检查:冲高回落/利润保护/止损/止盈/超时
            forced_sell_codes, forced_sell_prices, forced_sell_codes_set = \
                await self._check_and_execute_forced_sells(
                    trade_date, holdings, _sl_tp_prices,
                    forced_sell_codes, forced_sell_prices, forced_sell_codes_set,
                    check_timeout=True)
            # 统一执行卖出
            cash = await self._execute_forced_sells(
                trade_date, holdings, cash, forced_sell_codes,
                forced_sell_prices, _sl_tp_prices, rebalance_records,
                log_prefix='非调仓日')
            _prices_for_display = _sl_tp_prices
        else:
            if holdings and len(holdings) > 0:
                _prices_for_display = await self._get_prices(set(holdings.keys()), trade_date)
            else:
                _prices_for_display = {}
        await self.log(f"")
        await self.log(f"   ┌───────────────────────────────────────────────────────")
        # 【V13修复】日志区分非调仓日和调仓日无交易
        if trade_date in rebalance_set:
            await self.log(f"   │ i️  【调仓日无交易】当前持仓与目标一致,无需调仓")
        else:
            await self.log(f"   │ i️  【非调仓日】止损止盈检查+持仓监控")
        await self.log(f"   ├───────────────────────────────────────────────────────")

        # 【P0-C/P1-1修复(第十一轮):复用上方已获取的价格,不重复查询】
        # 【V13-P0-1修复】_prices_for_display已在方法开头初始化,此处不再需要try/except NameError
        if holdings and len(holdings) > 0:
            # _prices_for_display 已在上方 SL/TP 或 else 分支中赋值
            if not _prices_for_display:
                _prices_for_display = await self._get_prices(set(holdings.keys()), trade_date)
            await self.log(f"   │  📊 当前持仓 {len(holdings)} 只股票:")
            total_market_value = 0
            for code, shares in holdings.items():
                if shares > 0 and code in _prices_for_display:
                    price = _prices_for_display[code]['close']
                    market_value = shares * price
                    total_market_value += market_value
                    await self.log(f"   │      • {code}: {shares} 股, 收盘价 {price:.2f}, 市值 {market_value:,.2f} 元")
            await self.log(f"   │  💰 持仓总市值:{total_market_value:,.2f} 元")
        else:
            await self.log(f"   │  📊 当前无持仓")
            _prices_for_display = {}

        await self.log(f"   │  💵 当前现金:{cash:,.2f} 元")
        await self.log(f"   └───────────────────────────────────────────────────────")


        # ==================== 记录净值(每天必须执行)====================
        # 【P0-1/P0-2修复(V16):非调仓日也要记录净值+更新last_prices】
        # 旧bug: 非调仓日未调用_record_daily_net_value → 非每日调仓模式下净值序列有空洞
        # 旧bug: last_prices未更新 → 后续净值计算使用过期价格
        # 修复: 用当天获取的_sl_tp_prices或_prices_for_display更新last_prices,并记录净值
        if holdings and len(holdings) > 0:
            # 用当天获取的价格更新last_prices(确保净值用当天价格计算)
            if _prices_for_display:
                last_prices = _prices_for_display
        last_net_value, peak_value = await self._record_daily_net_value(
            trade_date, holdings, cash, last_net_value, peak_value,
            net_value_series, daily_profit_list, drawdown_series, daily_cash_list,
            last_prices=last_prices)

        # ==================== 更新run_state ====================
        self._update_run_state(run_state,
            cash=cash, holdings=holdings, rebalance_records=rebalance_records,
            last_prices=last_prices, stock_names=stock_names,
            net_value_series=net_value_series, daily_profit_list=daily_profit_list,
            drawdown_series=drawdown_series, daily_cash_list=daily_cash_list,
            peak_value=peak_value, last_net_value=last_net_value)
        return run_state

    async def _build_run_result(self, run_state: dict) -> dict:
        """构建回测结果: 合并交易记录、计算绩效指标、策略分解

        【P1-8说明:本方法700行,逻辑复杂但不可拆分】
        原因:结果构建是纯计算,无状态依赖,但需要访问run_state的所有字段。
        内部逻辑分为5段:1)绩效统计 2)交易记录 3)策略汇总 4)图表数据 5)元数据
        每段独立计算,可拆分为5个私有方法,但保持_build_run_result作为唯一入口。
        当前不拆分的原因:run_state是dict而非对象,拆分后参数传递更复杂。

        Args:
            run_state: 运行时状态dict

        Returns:
            最终回测结果dict
        """
        # 从run_state解包变量
        config = run_state['config']
        cash = run_state['cash']
        holdings = run_state['holdings']
        stock_names = run_state['stock_names']
        rebalance_records = run_state['rebalance_records']
        net_value_series = run_state['net_value_series']
        daily_profit_list = run_state['daily_profit_list']
        drawdown_series = run_state['drawdown_series']
        daily_cash_list = run_state['daily_cash_list']
        # 【V32:P1-1修复】移除insert(0, ...)到计算段之后
        # 旧bug: insert(0,0.0)导致daily_profit_list比all_trade_dates多1条,
        # monthly_profit计算中daily_profit_list[i]与all_trade_dates[i]错位1天,
        # 第1天被分配0利润,最后1天利润丢失
        # 修复: 先用原始数据完成所有计算,再为前端显示插入初始值
        _need_initial_insert = net_value_series and net_value_series[0].get('net_value', 0) != 1.0
        # _need_initial_insert稍后在计算完成后用于插入
        peak_value = run_state['peak_value']
        last_net_value = run_state['last_net_value']
        last_prices = run_state['last_prices']
        all_trade_dates = run_state['all_trade_dates']
        rebalance_dates = run_state['rebalance_dates']
        rebalance_set = run_state['rebalance_set']
        total_days = run_state['total_days']
        benchmark_data = run_state['benchmark_data']
        initial_cash = run_state['initial_cash']

        # 计算最终市值(所有日期处理完成后)
        final_value = cash
        for code, shares in holdings.items():
            if shares > 0 and code in last_prices:
                # last_prices[code] 是 {open: x, close: x},用收盘价估值
                final_value += shares * last_prices[code]['close']

        # 计算总收益率
        initial_value = self._initial_cash
        total_return = (final_value - initial_value) / initial_value

        # 收集所有交易记录
        all_trades = []
        for day_records in rebalance_records:
            if isinstance(day_records, list):
                all_trades.extend(day_records)
            else:
                all_trades.append(day_records)

        # 合并买入+卖出为完整交易,转换为字典格式
        merged_trades = []

        # 收集所有买入记录,按code分组
        # 【P0-3修复:buy_records改为FIFO队列,每次卖出扣除对应股数】
        buy_records = {}  # code -> list of {record, remaining_shares}
        total_signals = 0
        winning_trades = 0
        completed_trades = 0  # 【P1-4修复:完整交易数(非买入信号数)】

        for day_records in rebalance_records:
            records_list = day_records if isinstance(day_records, list) else [day_records]
            for record in records_list:
                if record.action == 'buy':
                    code = record.ts_code
                    if code not in buy_records:
                        buy_records[code] = []
                    buy_records[code].append({'record': record, 'remaining': record.shares})

        # 所有买入都是信号
        total_signals = sum(len(buys) for buys in buy_records.values())

        # 统计每个卖出是否盈利,同时合并完整交易
        # 【P0-3修复:FIFO匹配 - 卖出时从buy_records中按顺序扣减】
        for day_records in rebalance_records:
            records_list = day_records if isinstance(day_records, list) else [day_records]
            for record in records_list:
                if record.action == 'sell' and record.ts_code in buy_records:
                    code = record.ts_code
                    sells = buy_records[code]
                    if not sells:
                        continue

                    # 卖出时按FIFO匹配买入记录
                    sell_shares = record.shares
                    sell_cost = 0.0
                    sell_buy_shares = 0  # 匹配到的买入股数
                    first_buy = sells[0]['record']  # 最早买入记录

                    while sell_shares > 0 and sells:
                        entry = sells[0]
                        matched = min(sell_shares, entry['remaining'])
                        # 按比例分配该买入记录的成本
                        buy_rec = entry['record']
                        cost_per_share = abs(buy_rec.amount) / buy_rec.shares if buy_rec.shares > 0 else 0
                        sell_cost += matched * cost_per_share
                        sell_buy_shares += matched
                        entry['remaining'] -= matched
                        sell_shares -= matched
                        if entry['remaining'] <= 0:
                            sells.pop(0)  # 该买入记录已完全匹配

                    if sell_buy_shares > 0 and sell_cost > 0:
                        avg_cost = sell_cost / sell_buy_shares
                        net_sell_amount = record.amount
                        profit = (net_sell_amount - sell_cost) / sell_cost * 100
                        if net_sell_amount > sell_cost:
                            winning_trades += 1
                        completed_trades += 1

                        # 【P1-1修复(第十轮):stock_names改为update而非覆盖】
                        stock_names.update(await self._get_stock_names([code]))
                        name = stock_names.get(code, code.split('.')[0])

                        strategy_name = first_buy.strategy_name if first_buy.strategy_name else "策略选股"
                        if not strategy_name and first_buy.reason:
                            strategy_name = first_buy.reason.replace(' 策略选股调入', '').strip() or "-"
                        if not strategy_name:
                            strategy_name = "-"

                        strategy_buy_time = self.STRATEGY_BUY_TIMES.get(strategy_name, '09:35')
                        # 【P1修复】计算持仓天数
                        try:
                            buy_d = int(first_buy.date) if first_buy.date else 0
                            sell_d = int(record.date) if record.date else 0
                            # 【P1-3修复(V16):持仓天数改用交易日计算,替代日历天数】
                            # 【V30:P1-1】使用O(1)索引映射计算
                            hold_d = self._calc_trade_days_held(buy_d, sell_d)
                            if hold_d <= 0:
                                # fallback: 日历天数
                                from datetime import datetime
                                bd = datetime.strptime(str(buy_d), '%Y%m%d')
                                sd = datetime.strptime(str(sell_d), '%Y%m%d')
                                hold_d = (sd - bd).days
                        except:
                            hold_d = 1

                        merged_trades.append({
                            'ts_code': code,
                            'name': name,
                            'strategy': strategy_name,
                            'sentiment': first_buy.sentiment,
                            'buy_date': first_buy.date,
                            'buy_time': strategy_buy_time,
                            'buy_price': avg_cost,
                            'sell_date': record.date,
                            'sell_time': '收盘',
                            'sell_price': record.amount / record.shares if record.shares > 0 else record.price,  # 【V55-BUG-003修复:用净金额/股数(含滑点佣金印花税),与buy_price一致;旧值record.price不含滑点导致前端利润率与profit_pct不匹配】
                            'sell_reason': record.reason,  # 【修复】记录卖出原因(止损/止盈/调仓/强制空仓等)
                            'shares': sell_buy_shares,
                            'profit_pct': profit,
                            'hold_days': hold_d,
                        })

                    # 清理空的buy_records
                    if not sells:
                        del buy_records[code]

        # 添加还未卖出的持仓到明细
        for code, buys in buy_records.items():
            # buy_records中剩余的=还未卖出的持仓(FIFO扣减后)
            if not buys:
                continue
            # 检查是否还有剩余股数
            remaining_shares = sum(b['remaining'] for b in buys)
            if remaining_shares <= 0:
                continue
            # 还在持仓中,添加到明细
            # 【P0-1修复(第十一轮):使用当前code的首次买入记录,而非卖出循环遗留的first_buy】
            first_buy = buys[0]['record']  # 当前code最早的买入记录
            # 【P1-1修复(第十轮):stock_names改为update而非覆盖】
            stock_names.update(await self._get_stock_names([code]))
            name = stock_names.get(code, code.split('.')[0])

            strategy_name = first_buy.strategy_name if first_buy.strategy_name else "策略选股"
            if not strategy_name and first_buy.reason:
                strategy_name = first_buy.reason.replace(' 策略选股调入', '').strip() or "-"
            if not strategy_name:
                strategy_name = "-"

            # 计算剩余持仓的平均成本
            total_remaining_cost = sum(abs(b['record'].amount) / b['record'].shares * b['remaining'] for b in buys if b['record'].shares > 0)
            avg_remaining_cost = total_remaining_cost / remaining_shares if remaining_shares > 0 else 0

            merged_trades.append({
                'ts_code': code,
                'name': name,
                'strategy': strategy_name,
                'sentiment': first_buy.sentiment,
                'buy_date': first_buy.date,
                'buy_time': self.STRATEGY_BUY_TIMES.get(strategy_name, '09:35'),
                'buy_price': avg_remaining_cost,
                'sell_date': '',
                'sell_time': '',
                'sell_price': 0.0,
                'shares': remaining_shares,
                'profit_pct': None,  # 还未卖出
                'hold_days': None,  # 还未卖出
                'sell_reason': '持仓中',  # 还未卖出
            })

        # 初始化绩效指标(避免 UnboundLocalError 当0交易时)
        # 【P0修复:max_drawdown提前从drawdown_series计算,避免中间日志输出0.00%】
        raw_max_drawdown = max(drawdown_series) if drawdown_series else 0.0
        max_drawdown = min(raw_max_drawdown, 1.0)  # 硬限制,防止异常值
        sharpe_ratio = 0.0
        profit_loss_ratio = 0.0
        strategy_name = "组合策略"

        # 计算胜率
        # 【P1-4修复:用完整交易数(completed_trades)而非买入信号数(total_signals)】
        win_rate = 0.0
        if completed_trades > 0:
            win_rate = winning_trades / completed_trades
            win_rate_percent = win_rate * 100
        else:
            win_rate_percent = 0.0
        # 【修复#13:年化收益率使用真实交易天数而不是调仓日数】
        # 交易天数 = 所有交易日数量,而不是仅仅调仓日数量
        trading_days = len(all_trade_dates)
        annual_return_reliable = trading_days >= 30  # 少于30天年化无参考意义
        if trading_days > 0:
            # 复利年化: (1 + total_return) ^ (252 / trading_days) - 1
            annualized_return = ((1 + total_return) ** (252 / trading_days)) - 1
        else:
            annualized_return = 0.0

        # 【修复#26/#27:使用 PerformanceAnalyzer 重新计算所有绩效指标】
        # 将merged_trades写入临时JSON文件,使用PerformanceAnalyzer计算
        # 【修复:PerformanceAnalyzer API不匹配(file_path≠risk_free_rate, 无get_basic_stats方法),
        # 改为直接使用已计算的绩效指标,不再调用PerformanceAnalyzer】
        # 原代码:analyzer = PerformanceAnalyzer(temp_file.name) → 传了文件路径给risk_free_rate参数,且无get_basic_stats方法
        # 当有交易时,win_rate/max_drawdown/sharpe_ratio等已在上方正确计算,无需重复计算

        # 【P0-1修复(第十轮):sortino_ratio/calmar_ratio/volatility在打印段之前初始化默认值】
        # 避免NameError崩溃(之前打印段引用这些变量时它们尚未赋值)
        sortino_ratio = 0.0
        calmar_ratio = 0.0
        volatility = 0.0

        # 【第二十四轮修复:删除引用未定义daily_returns_list的重复计算块】
        # volatility/sortino_ratio/calmar_ratio 已在下方(daily_profit_list计算段)正确赋值
        # 此处仅保留Calmar(不依赖daily_returns_list)
        if max_drawdown > 0:
            calmar_ratio = annualized_return / max_drawdown

        # 统计盈利次数/亏损次数
        # 【P0-1修复:losing_trades用completed_trades-winning_trades,而非total_signals-winning_trades】
        # total_signals是买入信号数(含未卖出持仓),winning_trades是已卖出盈利数,维度不一致
        losing_trades = completed_trades - winning_trades
        # 【P1修复】total_trades只计已完成交易(有sell_date的),不含未平仓
        total_trades = completed_trades

        # 计算收益回撤比 = 累计收益率 / 最大回撤(当最大回撤 > 0 时)
        return_drawdown_ratio = 0.0
        if max_drawdown > 0 and total_return != 0:
            return_drawdown_ratio = abs(total_return) / max_drawdown

        # 计算平均持仓天数
        average_hold_days = 0.0
        # 【P1-3修复(V16):持仓天数改用交易日计算,替代日历天数】
        completed_trades_for_avg = [t for t in merged_trades if t.get('sell_date') and t.get('buy_date')]
        if len(completed_trades_for_avg) > 0:
            total_hold_days = 0
            _all_td = run_state.get('all_trade_dates', [])
            for trade in completed_trades_for_avg:
                buy_date_int = int(trade['buy_date'])
                sell_date_int = int(trade['sell_date'])
                # 【V30:P1-1】使用O(1)索引映射计算
                hold_days = self._calc_trade_days_held(buy_date_int, sell_date_int)
                if hold_days <= 0:
                    buy_dt = dt_now.strptime(str(buy_date_int), '%Y%m%d')
                    sell_dt = dt_now.strptime(str(sell_date_int), '%Y%m%d')
                    hold_days = (sell_dt - buy_dt).days
                total_hold_days += hold_days
            average_hold_days = total_hold_days / len(completed_trades_for_avg)

        # 输出最终汇总结果到日志
        await self.log("✅ 回测全部完成!")
        if total_signals == 0:
            await self.log("📊 汇总结果:总信号 0 个,平均胜率 0.00%,总收益率 0.00%")
            await self.log("  累计收益率: 0.00%")
            await self.log("  年化收益率: 0.00%")
            await self.log("  最大回撤: 0.00%")
            await self.log("  盈亏比: 0.00")
            await self.log("  夏普比率: 0.00")
            await self.log("  收益回撤比: 0.00")
            await self.log("  总交易次数: 0")
            await self.log("  盈利次数: 0 / 亏损次数: 0")
            await self.log("  平均持仓天数: 0")
        else:
            await self.log(f"📊 汇总结果:总信号 {total_signals} 个,平均胜率 {win_rate_percent:.2f}%,总收益率 {total_return * 100:.2f}%")
            await self.log(f"  累计收益率: {total_return * 100:.2f}%")
            await self.log(f"  年化收益率: {annualized_return * 100:.2f}%")
            await self.log(f"  最大回撤: {max_drawdown * 100:.2f}%")
            await self.log(f"  盈亏比: {profit_loss_ratio:.2f}")
            await self.log(f"  夏普比率: {sharpe_ratio:.2f}")
            await self.log(f"  索提诺比率: {sortino_ratio:.2f}")
            await self.log(f"  卡玛比率: {calmar_ratio:.2f}")
            await self.log(f"  年化波动率: {volatility * 100:.2f}%")
            await self.log(f"  收益回撤比: {return_drawdown_ratio:.2f}")
            await self.log(f"  总交易次数: {total_trades}")
            await self.log(f"  盈利次数: {winning_trades} / 亏损次数: {losing_trades}")
            await self.log(f"  平均持仓天数: {average_hold_days:.1f}")

        # 打印完整逐笔交易明细
        if len(merged_trades) > 0:
            await self.log("")
            await self.log("📝 【完整逐笔交易明细】")
            await self.log("")

            # 使用 tabulate 输出美观的表格
            from tabulate import tabulate

            table_data = []
            headers = ["#", "代码", "名称", "策略", "情绪", "买入", "买入时间", "卖出", "卖出时间", "买入价", "卖出价", "股数", "仓位", "持仓", "盈亏", "盈亏%", "", "说明"]

            for idx, trade in enumerate(merged_trades, 1):
                ts_code = trade.get('ts_code', '')
                name = trade.get('name', ts_code)
                strategy = trade.get('strategy', '')
                strategy_name = strategy.strip() if strategy.strip() else "-"
                # 只取情绪第一部分
                sentiment = trade.get('sentiment', '')
                if sentiment:
                    sentiment = sentiment.split(',')[0].strip()
                sentiment = sentiment or "-"
                buy_date = trade.get('buy_date', '')
                buy_price = float(trade.get('buy_price', 0)) if trade.get('buy_price') is not None else 0.0
                buy_time = trade.get('buy_time', '09:35')
                sell_date = trade.get('sell_date', '')
                sell_price = float(trade.get('sell_price', 0)) if trade.get('sell_price') is not None else 0.0
                sell_time = trade.get('sell_time', '收盘')
                shares = int(trade.get('shares', 0)) if trade.get('shares') is not None else 0
                profit_pct = trade.get('profit_pct')

                # 计算盈亏
                hold_days = 0
                profit_abs = 0
                is_profit = "-"
                if profit_pct is not None and buy_price > 0 and sell_price > 0:
                    # 正确的盈亏 = (卖出-买入)×股数 - 买入佣金 - 卖出佣金 - 印花税
                    buy_cost = shares * buy_price
                    sell_income = shares * sell_price
                    buy_comm = max(buy_cost * self.BUY_COMMISSION, self.MIN_COMMISSION)
                    sell_comm = max(sell_income * self.SELL_COMMISSION, self.MIN_COMMISSION)
                    stamp = sell_income * self.STAMP_TAX
                    profit_abs = sell_income - buy_cost - buy_comm - sell_comm - stamp
                    is_profit = "✅" if profit_pct > 0 else "❌"
                    # 计算持仓天数
                    # 【P1-3修复(V16):持仓天数改用交易日计算,替代日历天数】
                    # 【V30:P1-1】使用O(1)索引映射计算
                    if buy_date and sell_date:
                        try:
                            buy_d2 = int(buy_date)
                            sell_d2 = int(sell_date)
                            hold_days = self._calc_trade_days_held(buy_d2, sell_d2)
                            if hold_days <= 0:
                                buy_dt = dt_now.strptime(str(buy_d2), '%Y%m%d')
                                sell_dt = dt_now.strptime(str(sell_d2), '%Y%m%d')
                                hold_days = (sell_dt - buy_dt).days
                        except (ValueError, TypeError):
                            hold_days = 0

                # 计算仓位百分比
                position_pct = "-"
                if shares > 0 and buy_price > 0:
                    cost = shares * buy_price
                    position_pct = f"{cost / self._initial_cash * 100:.0f}%"

                # 未卖出持仓的特殊标记
                is_open_position = not sell_date and sell_price == 0.0
                display_sell_date = sell_date if sell_date else '持仓中'
                display_sell_time = sell_time if sell_time else '-'
                display_sell_price = f"{sell_price:.2f}" if sell_price > 0 else '持仓中'

                # 格式化
                profit_abs_str = f"{profit_abs:.0f}" if profit_abs != 0 else "-"
                profit_pct_str = f"{profit_pct:.2f}%" if profit_pct is not None else "-"
                hold_days_str = hold_days if hold_days > 0 else ("持仓中" if is_open_position else 0)

                table_data.append([
                    idx, ts_code, name[:12], strategy_name[:10], sentiment,
                    buy_date, buy_time, display_sell_date, display_sell_time,
                    f"{buy_price:.2f}", display_sell_price, shares, position_pct, hold_days_str,
                    profit_abs_str, profit_pct_str, is_profit, "🔓" if is_open_position else ""
                ])

            # 使用 grid 表格格式
            table_str = tabulate(table_data, headers=headers, tablefmt='grid')
            for line in table_str.split('\n'):
                await self.log(line)

            await self.log("")
            await self.log(f"📊 总计 {len(merged_trades)} 笔完整交易")
        # 将 RebalanceRecord 对象转换为字典,方便 MongoDB 序列化
        rebalance_records_dict = []
        for day_records in rebalance_records:
            if isinstance(day_records, list):
                day_dict = []
                for record in day_records:
                    if hasattr(record, '__dict__'):
                        day_dict.append(record.__dict__)
                    else:
                        day_dict.append(record)
                rebalance_records_dict.append(day_dict)
            else:
                if hasattr(day_records, '__dict__'):
                    rebalance_records_dict.append(day_records.__dict__)
                else:
                    rebalance_records_dict.append(day_records)

        # 转换 all_trades 也为字典
        # 【V55-BUG-004修复:卖出记录添加sell_price/buy_price映射,与merged_trades一致】
        all_trades_dict = []
        for record in all_trades:
            if hasattr(record, '__dict__'):
                d = dict(record.__dict__)
            else:
                d = record if isinstance(record, dict) else {}
            # 卖出记录添加sell_price映射(price→sell_price)
            if d.get('action') == 'sell' and 'sell_price' not in d and 'price' in d:
                d['sell_price'] = d['price']
            # 买入记录添加buy_price映射(price→buy_price)
            if d.get('action') == 'buy' and 'buy_price' not in d and 'price' in d:
                d['buy_price'] = d['price']
            all_trades_dict.append(d)

        # 【修复#47/#48/#13:基于逐日净值计算绩效指标】
        # 净值曲线和每日盈亏已经在逐日回测循环中计算完成,这里直接使用
        # 删除了原来基于调仓日的简化估算,现在使用精确的逐日持仓市值计算

        # max_drawdown 已在上方从drawdown_series计算
        # 【V54-Bug3修复:删除重复的return_drawdown_ratio计算,上方2502行已用同一max_drawdown计算】
        # return_drawdown_ratio = abs(total_return) / max_drawdown  # 此处与2502行逻辑完全相同,已删除

        # 【P0-3修复(V9):盈亏比改用交易维度而非日收益维度】
        # 旧: 基于daily_profit_list(日收益),10只持仓5涨5跌→只算1次盈利→虚高
        # 新: 基于已平仓交易(merged_trades),avg_win_pct / avg_loss_pct → 正确反映策略选股能力
        # 注意: all_trades是RebalanceRecord对象(无profit_pct),merged_trades是dict(有profit_pct)
        completed_trades_for_plr = [t for t in merged_trades if t.get('profit_pct') is not None and t.get('sell_reason', '') != '持仓中']
        win_trades = [t for t in completed_trades_for_plr if t['profit_pct'] > 0]
        loss_trades = [t for t in completed_trades_for_plr if t['profit_pct'] < 0]
        if win_trades and loss_trades:
            avg_win = sum(t['profit_pct'] for t in win_trades) / len(win_trades)
            avg_loss = abs(sum(t['profit_pct'] for t in loss_trades) / len(loss_trades))
            profit_loss_ratio = avg_win / avg_loss if avg_loss > 0.001 else 99.99
        elif win_trades:
            profit_loss_ratio = 99.99
        else:
            profit_loss_ratio = 0.0

        # 【修复#13:基于修复后的净值曲线正确计算夏普比率】
        # 夏普比率 = 平均日收益率 / 日收益率标准差 × sqrt(252)
        # 【V41优化:用净值序列直接计算日收益率,避免daily_profit累积误差】
        # 旧: daily_returns = profit / current_value + 累加, 累积误差导致夏普失真
        # 新: daily_returns = (nv[i]/nv[i-1]) - 1, 直接从净值序列计算,更精确
        sharpe_ratio = 0.0
        # sortino_ratio/calmar_ratio/volatility 已在上方初始化(打印段需引用)
        if len(net_value_series) > 1 and last_net_value > 0:
            # V41: 直接从净值序列计算日收益率
            daily_returns = []
            for i in range(1, len(net_value_series)):
                prev_nv = net_value_series[i-1].get('net_value', self._initial_cash)
                curr_nv = net_value_series[i].get('net_value', self._initial_cash)
                if prev_nv > 0:
                    daily_returns.append((curr_nv / prev_nv) - 1)

            # 计算平均日收益率和标准差
            if len(daily_returns) > 1:
                avg_return = sum(daily_returns) / len(daily_returns)
                variance = sum((r - avg_return) ** 2 for r in daily_returns) / (len(daily_returns) - 1)
                std_return = math.sqrt(variance)

                # 年化波动率
                volatility = std_return * math.sqrt(252)

                if std_return > 0:
                    # 年化夏普比率(252个交易日,无风险利率3%)
                    daily_rf = 0.03 / 252
                    sharpe_ratio = (avg_return - daily_rf) / std_return * math.sqrt(252)

                # 【P1-7修复:索提诺比率(只考虑下行波动)】
                # 【V54-Bug1修复:Sortino分母用len(downside_returns)而非len(daily_returns)】
                # 标准定义: 下行偏差 = sqrt(sum(min(r,0)^2) / N_downside), N=len(downside_returns)
                downside_returns = [r for r in daily_returns if r < 0]
                if len(downside_returns) > 0:
                    downside_variance = sum(r ** 2 for r in downside_returns) / len(downside_returns)
                    downside_std = math.sqrt(downside_variance)
                    if downside_std > 0:
                        daily_rf = 0.03 / 252
                        raw_sortino = (avg_return - daily_rf) / downside_std * math.sqrt(252)
                        sortino_ratio = min(raw_sortino, 200.0)
                        if raw_sortino > 200.0:
                            logger.debug('backtest', f'Sortino={raw_sortino:.1f}超过200上限,下行波动过低')

        # 【V54-Bug4修复:Calmar使用复利年化,简单年化对短回测期(60天)会膨胀】
        # 旧: daily_return = total_return / trading_days * 252 (简单年化,短回测膨胀)
        # 新: (1+total_return)^(252/trading_days) - 1 (复利年化,与annualized_return一致)
        if max_drawdown > 0:
            if trading_days > 0:
                # V54: 复利年化,与annualized_return(2470行)计算方式一致
                annualized_for_calmar = ((1 + total_return) ** (252 / trading_days)) - 1
                raw_calmar = annualized_for_calmar / max_drawdown
            else:
                raw_calmar = annualized_return / max_drawdown
            calmar_ratio = min(raw_calmar, 1000.0)  # 【V49-P1-1:上限从200→1000,200太低遮盖真实值,3个月回测md<5%时calmar天然>200】
            if raw_calmar > 1000.0:
                logger.debug('backtest', f'Calmar={raw_calmar:.1f}超过1000上限,回测周期{trading_days}天过短')

        # 格式化 drawdown_series 为最终返回格式
        formatted_drawdown_series = []
        for i, point in enumerate(net_value_series):
            formatted_drawdown_series.append({
                "trade_date": point["trade_date"],
                "drawdown": drawdown_series[i] if i < len(drawdown_series) else 0.0
            })

        # 提取 daily_profit 序列(用于兼容)
        daily_profit = daily_profit_list.copy()

        # 【修复#49/#31:统一后端输出格式适配前端BacktestResult结构
        # - final_value → final_equity (字段名对齐)
        # - 百分比单位约定:所有_pct后缀字段和total_return/max_drawdown/win_rate等字段
        #   均为百分比数值(如15.5表示15.5%),不是小数(0.155)
        # - 此约定与ultra_short.py中读取时一致,前端亦按百分比展示
        # 【修复#17:嵌套BacktestMetrics结构:returns/risk/trades/positions/performance/metadata
        result = {
            "success": True,
            "initial_cash": self._initial_cash,
            "final_cash": cash,
            "final_equity": final_value,  # 【修复#49:字段名对齐 → final_equity】
            "final_value": final_value,  # 保持向后兼容
            "metrics": {  # 嵌套 BacktestMetrics 结构,字段名对齐前端TypeScript类型定义
                "returns": {
                    "total_return_pct": total_return * 100,
                    "annual_return_pct": annualized_return * 100,
                    "annual_return_reliable": annual_return_reliable,  # 少于30天年化无参考意义
                    "benchmark_return_pct": (benchmark_data[-1]["close"] / benchmark_data[0]["close"] - 1) * 100 if benchmark_data and len(benchmark_data) >= 2 and benchmark_data[0].get("close", 0) > 0 else 0.0,
                    "alpha_pct": total_return * 100 - ((benchmark_data[-1]["close"] / benchmark_data[0]["close"] - 1) * 100 if benchmark_data and len(benchmark_data) >= 2 and benchmark_data[0].get("close", 0) > 0 else 0.0),
                    # 以下字段保持兼容旧代码
                    "total_return": total_return * 100,
                    "annualized_return": annualized_return * 100,
                },
                "risk": {
                    "max_drawdown_pct": max_drawdown * 100,
                    "win_rate_pct": win_rate * 100,
                    "sharpe_ratio": sharpe_ratio,
                    "sortino_ratio": sortino_ratio,  # 【P1-7修复:新增索提诺比率】
                    "calmar_ratio": calmar_ratio,    # 【P1-7修复:新增卡玛比率】
                    "volatility_pct": volatility * 100,  # 【P1-7修复:新增年化波动率】
                    "profit_loss_ratio": profit_loss_ratio,
                    "return_drawdown_ratio": return_drawdown_ratio,
                    # 以下字段保持兼容旧代码
                    "max_drawdown": max_drawdown * 100,
                    "win_rate": win_rate * 100,
                },
                "trades": {
                    "total_trades": total_trades,
                    "winning_trades": winning_trades,
                    "losing_trades": losing_trades,
                    "avg_holding_days": average_hold_days,
                    "average_hold_days": average_hold_days,
                },
                "positions": {
                    "final_holdings": holdings,
                    "net_value_series": net_value_series,
                    "drawdown_series": formatted_drawdown_series,
                    # 【P1-8修复(V13)】:daily_profit统一为归一化小数,与顶层和net_value_series一致
                    "daily_profit": [p / self._initial_cash if self._initial_cash > 0 else 0.0 for p in daily_profit],
                },
                "performance": {
                    "total_signals": total_signals,
                    "rebalance_records": rebalance_records_dict,
                    "all_trades": all_trades_dict,
                    "benchmark_data": benchmark_data,
                    "stock_names": stock_names,
                },
                "metadata": {
                    "start_date": config.get("start_date"),
                    "end_date": config.get("end_date"),
                    "strategy_name": strategy_name,
                    "generated_at": dt_now.now().isoformat(),
                }
            },
        }

        # 【兼容层】顶层扁平字段供前端直接读取(如 result.win_rate)
        # 实际数据源在 result.metrics 内,值相同,保持两边同步
        # 前端BacktestResultPanel从顶层读取,勿删
        result["total_return"] = total_return * 100
        result["annualized_return"] = annualized_return * 100
        result["max_drawdown"] = max_drawdown * 100
        result["win_rate"] = win_rate * 100
        result["sharpe_ratio"] = sharpe_ratio
        result["profit_loss_ratio"] = profit_loss_ratio
        result["total_signals"] = total_signals
        result["total_trades"] = total_trades
        result["winning_trades"] = winning_trades
        result["losing_trades"] = losing_trades
        result["average_hold_days"] = average_hold_days
        result["all_trades"] = all_trades_dict
        # 【V55-Bug5修复:sell_reason_stats在portfolio_backtest中直接计算,不再依赖ultra_short后处理】
        # 旧bug: ultra_short.py设置result['sell_reason_stats']和result['performance'],
        # 但当ultra_short.py中merged_trades从performance_data读取为空时,
        # 覆盖为全零dict,导致前端显示空统计
        # 修复: 直接在portfolio_backtest的result中计算,确保数据不丢失
        _sell_reason_stats = {"stop_loss": 0, "take_profit": 0, "max_hold": 0, "force_empty": 0, "rebalance": 0, "profit_lock": 0, "profit_protect": 0, "pullback": 0, "halt": 0, "other": 0}
        for trade in merged_trades:
            reason = trade.get('sell_reason', '')
            if not reason or reason == '持仓中':
                continue
            reason_str = str(reason)
            if '止损' in reason_str or 'stop_loss' in reason_str.lower():
                _sell_reason_stats["stop_loss"] += 1
            elif '止盈' in reason_str or 'take_profit' in reason_str.lower():
                _sell_reason_stats["take_profit"] += 1
            elif '冲高回落' in reason_str or '高开即卖' in reason_str:
                _sell_reason_stats["pullback"] += 1
            elif '利润保护' in reason_str:
                _sell_reason_stats["profit_protect"] += 1
            elif '利润锁定' in reason_str:
                _sell_reason_stats["profit_lock"] += 1
            elif '停牌' in reason_str:
                _sell_reason_stats["halt"] += 1
            elif '到期' in reason_str or 'max_hold' in reason_str.lower() or '持仓天数' in reason_str or '超时' in reason_str:
                _sell_reason_stats["max_hold"] += 1
            elif '空仓' in reason_str or 'force_empty' in reason_str.lower() or '强制' in reason_str:
                _sell_reason_stats["force_empty"] += 1
            elif '调仓' in reason_str or 'rebalance' in reason_str.lower() or '减仓' in reason_str:
                _sell_reason_stats["rebalance"] += 1
            elif '持仓中' in reason_str:
                pass
            else:
                _sell_reason_stats["other"] += 1
        result["sell_reason_stats"] = _sell_reason_stats
        result["merged_trades"] = merged_trades  # 完整交易记录(含买卖信息,给前端展示)
        result["rebalance_records"] = rebalance_records_dict
        result["stock_names"] = stock_names
        result["net_value_series"] = net_value_series
        result["drawdown_series"] = formatted_drawdown_series
        # 【P0修复】daily_profit统一为归一化小数(÷initial_cash),与net_value_series[].daily_profit一致
        # 之前是绝对值(元),前端如果从顶层读取会与net_value_series不一致
        _dp_normalized = [p / self._initial_cash if self._initial_cash > 0 else 0.0 for p in daily_profit]
        result["daily_profit"] = _dp_normalized
        result["benchmark_data"] = benchmark_data

        # 【P2-12:补全前端图表所需字段】
        # 1. position_series: 每日仓位占比 [{date, value}]
        #    position = 1 - cash/equity (真实仓位比例)
        position_series = []
        for i, nv in enumerate(net_value_series):
            if i < len(daily_cash_list):
                pos_val = max(0.0, 1.0 - daily_cash_list[i])  # 仓位=1-现金占比
            else:
                pos_val = 0.0
            position_series.append({"date": nv.get("trade_date", ""), "value": pos_val})
        result["position_series"] = position_series

        # 2. strategy_results: 各策略独立绩效 {策略名: {win_rate, total_return, trades_count}}
        strategy_results = {}
        strategy_trades = {}
        for trade in merged_trades:
            sname = trade.get('strategy', '未知策略')
            if sname not in strategy_trades:
                strategy_trades[sname] = []
            strategy_trades[sname].append(trade)
        for sname, trades in strategy_trades.items():
            # 【P0-2修复(V23):过滤profit_pct为None的未平仓交易,避免TypeError】
            completed = [t for t in trades if t.get('sell_date') and t.get('profit_pct') is not None]
            wins = sum(1 for t in completed if t.get('profit_pct', 0) > 0)
            total_pnl = sum(t.get('profit_pct', 0) for t in completed)
            avg_pnl = total_pnl / len(completed) if completed else 0

            # 【P2修复】计算策略级最大回撤(基于累计净值曲线)
            strategy_max_dd = 0.0
            if completed:
                cum_pnl = 0.0
                peak_pnl = 0.0
                for t in sorted(completed, key=lambda x: x.get('sell_date', '')):
                    cum_pnl += t.get('profit_pct', 0)  # 已过滤None,安全
                    if cum_pnl > peak_pnl:
                        peak_pnl = cum_pnl
                    dd = peak_pnl - cum_pnl
                    if dd > strategy_max_dd:
                        strategy_max_dd = dd

            # 【P1-3修复(V9):策略级盈亏比改用交易维度(与组合级PLR一致)】
            strategy_win_trades = [t for t in completed if t.get('profit_pct', 0) > 0]
            strategy_loss_trades = [t for t in completed if t.get('profit_pct', 0) < 0]
            if strategy_win_trades and strategy_loss_trades:
                avg_win = sum(t['profit_pct'] for t in strategy_win_trades) / len(strategy_win_trades)
                avg_loss = abs(sum(t['profit_pct'] for t in strategy_loss_trades) / len(strategy_loss_trades))
                strategy_plr = round(avg_win / avg_loss, 2) if avg_loss > 0.001 else 99.99
            elif strategy_win_trades:
                strategy_plr = 99.99
            else:
                strategy_plr = 0.0

            strategy_results[sname] = {
                "strategy_name": sname,
                "win_rate": (wins / len(completed) * 100) if completed else 0,
                "total_return": total_pnl,  # 累计盈利百分比(profit_pct之和, 非组合收益率)
                "avg_profit_pct": avg_pnl,  # 平均盈亏百分比(单笔)
                "trades_count": len(completed),
                "max_drawdown": strategy_max_dd,
                "profit_loss_ratio": strategy_plr,
            }

        # 🔧 因子缺失告警:0交易策略加warning字段
        # 先从selected_strategies补上0交易的策略(它们不在merged_trades里)
        signal_stats = getattr(self, '_strategy_signal_stats', {})
        all_strategy_names = set()
        for s in config.get('selected_strategies', []):
            all_strategy_names.add(s.get('name', ''))
        for sname in all_strategy_names:
            if sname and sname not in strategy_results:
                ss = signal_stats.get(sname, {})
                total_days = ss.get('total_days', 0)
                signal_days = ss.get('signal_days', 0)
                if total_days == 0:
                    warning = "策略未启用或选股条件过于严格,回测期间从未触发筛选"
                elif signal_days == 0:
                    warning = f"回测{total_days}天均0候选→可能因子数据缺失(如limit_up_yesterday/volume_ratio为空)或选股条件过严"
                else:
                    warning = f"{signal_days}/{total_days}天有候选但0笔成交→可能买入条件(竞价/仓位)未满足"
                strategy_results[sname] = {
                    "strategy_name": sname,
                    "win_rate": 0, "total_return": 0,
                    "trades_count": 0, "total_return": 0,
                    "warning": warning,
                }

        for sname, sdata in strategy_results.items():
            if sdata.get("trades_count", 0) == 0 and "warning" not in sdata:
                ss = signal_stats.get(sname, {})
                total_days = ss.get('total_days', 0)
                signal_days = ss.get('signal_days', 0)
                if total_days == 0:
                    sdata["warning"] = "策略未启用或选股条件过于严格,回测期间从未触发筛选"
                elif signal_days == 0:
                    sdata["warning"] = f"回测{total_days}天均0候选→可能因子数据缺失(如limit_up_yesterday/volume_ratio为空)或选股条件过严"
                else:
                    sdata["warning"] = f"{signal_days}/{total_days}天有候选但0笔成交→可能买入条件(竞价/仓位)未满足"

        result["strategy_results"] = strategy_results

        # 3. factor_contribution: 因子贡献 {策略名: 贡献比例}
        # 【修复】按实际收益贡献(绝对值)分配,而非笔数等分
        # 半路追涨110笔赚62% vs 涨停开板11笔亏3.9%,按笔数分配不合理
        factor_contribution = {}
        total_pnl_abs = sum(abs(s.get("total_return", 0)) for s in strategy_results.values())
        if total_pnl_abs > 0:
            for name, s in strategy_results.items():
                factor_contribution[name] = abs(s.get("total_return", 0)) / total_pnl_abs
        else:
            # 无收益时按笔数比例分配
            total_trades_count = sum(s.get("trades_count", 0) for s in strategy_results.values())
            if total_trades_count > 0:
                for name, s in strategy_results.items():
                    factor_contribution[name] = s.get("trades_count", 0) / total_trades_count
            else:
                n = len(strategy_results) or 1
                for name in strategy_results:
                    factor_contribution[name] = 1.0 / n
        result["factor_contribution"] = factor_contribution

        # 4. monthly_profit: 月度收益 {"2026-01": 收益率, ...}
        # 【V47修复:改用net_value_series计算,避免daily_profit_list浮点累加误差】
        monthly_profit = {}
        if net_value_series and len(net_value_series) > 0:
            current_month = None
            month_start_nv = None  # 月初净值
            for nv_point in net_value_series:
                nv = nv_point.get('net_value', 1.0)
                trade_date_nv = nv_point.get('trade_date', 0)
                date_str = str(trade_date_nv)
                month_key = date_str[:6]  # "202601"
                formatted_key = f"{month_key[:4]}-{month_key[4:]}"  # "2026-01"
                if current_month is not None and month_key != current_month:
                    # 月末,计算该月收益
                    m_return = (nv - month_start_nv) / month_start_nv if month_start_nv and month_start_nv > 0 else 0
                    formatted_prev = f"{current_month[:4]}-{current_month[4:]}"
                    monthly_profit[formatted_prev] = m_return
                    month_start_nv = nv
                elif month_start_nv is None:
                    month_start_nv = nv
                current_month = month_key
            # 最后一月
            if current_month and month_start_nv is not None:
                m_return = (nv - month_start_nv) / month_start_nv if month_start_nv > 0 else 0
                formatted_last = f"{current_month[:4]}-{current_month[4:]}"
                monthly_profit[formatted_last] = m_return
        elif daily_profit_list and all_trade_dates:
            # 【V54-Bug6:TODO】此fallback路径使用daily_profit_list累加,存在浮点累积误差
            # 几乎不会触发(主路径用net_value_series),但如触发需注意精度
            # 修复方案: 改用net_value_series的月度端点计算(与主路径一致)
            # Fallback: 旧算法(仅当net_value_series不可用时)
            current_value = self._initial_cash
            monthly_start_value = current_value
            current_month = None
            for i, profit in enumerate(daily_profit_list):
                if i < len(all_trade_dates):
                    date_str = str(all_trade_dates[i])
                    month_key = date_str[:6]
                    formatted_key = f"{month_key[:4]}-{month_key[4:]}"
                    if current_month is not None and month_key != current_month:
                        m_return = (current_value - monthly_start_value) / monthly_start_value if monthly_start_value > 0 else 0
                        formatted_prev = f"{current_month[:4]}-{current_month[4:]}"
                        monthly_profit[formatted_prev] = m_return
                        monthly_start_value = current_value
                    current_month = month_key
                current_value += profit
            if current_month:
                m_return = (current_value - monthly_start_value) / monthly_start_value if monthly_start_value > 0 else 0
                formatted_last = f"{current_month[:4]}-{current_month[4:]}"
                monthly_profit[formatted_last] = m_return
        result["monthly_profit"] = monthly_profit

        # 兼容层标注:年化收益可靠性
        result["annual_return_reliable"] = annual_return_reliable

        # 【V32:P1-1修复】计算完成后为前端显示插入初始净值=1.0
        # 所有计算(monthly_profit/sharpe/sortino/position_series)已完成,
        # 现在安全地插入初始值,不影响计算结果
        if _need_initial_insert:
            first_date = str(run_state['config'].get('start_date', ''))
            net_value_series.insert(0, {
                "trade_date": first_date,
                "net_value": 1.0,
                "daily_profit": 0.0,
                "drawdown": 0.0
            })
            daily_profit_list.insert(0, 0.0)
            drawdown_series.insert(0, 0.0)
            daily_cash_list.insert(0, 1.0)
            # 更新result中已写入的列表引用(同一对象,insert自动反映)
            # daily_profit已归一化写入result,需重新计算
            _dp_normalized = [p / self._initial_cash if self._initial_cash > 0 else 0.0 for p in daily_profit_list]
            result["daily_profit"] = _dp_normalized
            # position_series需重建(多了一个初始条目)
            position_series = []
            for i, nv in enumerate(net_value_series):
                if i < len(daily_cash_list):
                    pos_val = max(0.0, 1.0 - daily_cash_list[i])
                else:
                    pos_val = 0.0
                position_series.append({"date": nv.get("trade_date", ""), "value": pos_val})
            result["position_series"] = position_series

        return result

    async def _load_benchmark_data(self, benchmark_code: str, start_date: int, end_date: int):
        """加载基准指数数据用于计算超额收益"""
        # 【P1-6修复(V9):用$or同时查int和string格式的trade_date,减少MongoDB查询从7次→3次】
        query_or = {
            "ts_code": benchmark_code,
            "$or": [
                {"trade_date": {"$gte": start_date, "$lte": end_date}},
                {"trade_date": {"$gte": str(start_date), "$lte": str(end_date)}}
            ]
        }
        docs = await mongo_manager.find_many(C.INDEX_DAILY, query_or)

        # 如果指定代码查不到,尝试000001.SH(上证指数)
        if not docs and benchmark_code != "000001.SH":
            fallback_query = {
                "ts_code": "000001.SH",
                "$or": [
                    {"trade_date": {"$gte": start_date, "$lte": end_date}},
                    {"trade_date": {"$gte": str(start_date), "$lte": str(end_date)}}
                ]
            }
            docs = await mongo_manager.find_many(C.INDEX_DAILY, fallback_query)
            if docs:
                await self.log(f"   ⚠️ 基准数据回退: {benchmark_code}无数据,使用000001.SH(上证指数)")

        # 如果index_daily无数据,回退到stock_daily_ak_full(兼容旧数据)
        if not docs:
            docs = await mongo_manager.find_many(C.STOCK_DAILY, query_or)

        # 如果仍然无数据,用宽基ETF近似
        if not docs:
            for fallback_code in ["510050.SH", "510300.SH", "510500.SH"]:
                fallback_query = {
                    "ts_code": fallback_code,
                    "trade_date": {"$gte": start_date, "$lte": end_date}
                }
                docs = await mongo_manager.find_many(C.STOCK_DAILY, fallback_query)
                if docs:
                    await self.log(f"   ⚠️ 基准数据回退使用 {fallback_code}(ETF)近似")
                    break

        # 按日期排序(兼容int和string)
        docs.sort(key=lambda x: int(x["trade_date"]) if isinstance(x["trade_date"], str) else x["trade_date"])
        benchmark_data = []
        for i, doc in enumerate(docs):
            td = int(doc["trade_date"]) if isinstance(doc["trade_date"], str) else doc["trade_date"]
            close = doc["close"]
            # 【P0修复】pct_chg: 优先用文档值,否则从前一天close计算
            pct_chg = doc.get("pct_chg")
            if pct_chg is None or pct_chg == 0:
                if i > 0 and benchmark_data[i-1]["close"] > 0:
                    pct_chg = (close / benchmark_data[i-1]["close"] - 1) * 100
                else:
                    pct_chg = 0.0
            benchmark_data.append({
                "trade_date": td,
                "close": close,
                "pct_chg": pct_chg
            })
        return benchmark_data

    @staticmethod
    def _standardize_ts_code(code_str: str) -> str:
        """【P2-3修复(V21):提取ts_code标准化为共享方法,消除_get_prices和_get_stock_names中的重复代码】
        数据库存储格式: 600000.SH / 000001.SZ / 830001.BJ
        规则: 6/5/9开头→.SH, 8/4开头→.BJ, 其他→.SZ
        """
        code_str = str(code_str).strip()
        if code_str.endswith('.SH') or code_str.endswith('.SZ') or code_str.endswith('.BJ'):
            return code_str
        if code_str.startswith('6') or code_str.startswith('5') or code_str.startswith('9'):
            return f"{code_str}.SH"
        elif code_str.startswith('8') or code_str.startswith('4'):
            return f"{code_str}.BJ"
        else:
            return f"{code_str}.SZ"

    async def _get_prices(self, ts_codes: set[str], trade_date):
        """批量获取指定股票在指定日期的开盘价和收盘价
        【P2-4优化:使用每日价格缓存,同一天只查一次MongoDB】

        Returns:
            dict: {ts_code: {"open": open_price, "close": close_price}}
        """
        # 【P2-4:每日价格缓存】同一天只查一次MongoDB,后续调用直接从缓存取
        cache = getattr(self, '_daily_price_cache', {})
        cache_date = getattr(self, '_daily_price_cache_date', None)
        if cache and cache_date == trade_date:
            # 从缓存中取需要的股票
            result = {}
            missing = set()
            for code in ts_codes:
                std_code = self._standardize_ts_code(code)
                if std_code in cache:
                    result[std_code] = cache[std_code]
                elif str(code).strip() in cache:
                    result[str(code).strip()] = cache[str(code).strip()]
                else:
                    missing.add(std_code)
                    missing.add(str(code).strip())
            if not missing:
                return result
            # 只查缺失的股票
            ts_codes = missing
        else:
            # 新的一天,重置缓存
            self._daily_price_cache = {}
            self._daily_price_cache_date = trade_date
            cache = self._daily_price_cache
        # 【P2-3修复(V21):用共享方法_standardize_ts_code替代重复的标准化逻辑】
        ts_codes_standard = [self._standardize_ts_code(code) for code in ts_codes]

        # 【修复#42:使用$in+ts_code过滤替代全表扫描】
        # 原逻辑:先查当天所有股票(5000+条)到内存,再过滤 → O(N)全表扫描 + 内存浪费
        # 新逻辑:用$in直接在数据库层面过滤 ts_code,只拉取需要的股票 → O(logN)索引查询
        ts_codes_set = set(ts_codes_standard)
        # 🔧 修复:trade_date 从 all_trade_dates 获取是字符串,但数据库存 int,必须转换
        trade_date_int = int(trade_date)
        # 【修复#9:复合索引查询优化 - 正确的查询顺序】
        # 复合索引定义是 (trade_date, ts_code),查询时按索引顺序匹配字段
        query = {
            "trade_date": trade_date_int,
            "ts_code": {"$in": list(ts_codes_set)},
        }

        # 【P1-1修复(V19):_get_prices日志降级为debug,避免每日3-5次调用水淹日志】
        logger.debug('backtest', f'[_get_prices] 查询 {len(ts_codes_standard)} 只股票,日期: {trade_date}')

        docs = await mongo_manager.find_many(C.STOCK_DAILY, query)
        result = {}
        # 【P2-3修复(V22):简化匹配逻辑 - 既然查询前已标准化,数据库也存标准格式,直接精确匹配】
        # 旧: 三层嵌套匹配(精确→去后缀→反向匹配),实际上标准化后99.9%直接命中
        for doc in docs:
            ts_code_doc = doc["ts_code"]
            if ts_code_doc in ts_codes_set:
                result[ts_code_doc] = {
                    "open": doc.get("open", doc["close"]),
                    "high": doc.get("high", doc["close"]),
                    "low": doc.get("low", doc["close"]),
                    "close": doc["close"],
                    # 【D1修复(第二十轮):pre_close补充逻辑】
                    "pre_close": doc.get("pre_close") or self._prev_day_close.get(ts_code_doc, None)
                }


        # 【P1-1修复(V19):_get_prices日志降级为debug】
        logger.debug('backtest', f'[_get_prices] 查询到 {len(result)}/{len(ts_codes_standard)} 只股票有价格')

        # 【P2-4:存入每日价格缓存】
        cache = getattr(self, '_daily_price_cache', {})
        cache.update(result)
        self._daily_price_cache = cache

        # 【P0-3:更新_last_valid_price,停牌强卖时回退用】
        lvp = getattr(self, '_last_valid_price', {})
        # 【D1修复(第二十轮):更新_prev_day_close,供次日pre_close回退】
        # 语义: 记录每天获取到的close, 次日_get_prices时如果doc无pre_close字段则用此值fallback
        # 同一天多次调用_get_prices会覆盖为相同值(同一天close不变), 无副作用
        # 注意: 次日首次调用时会把"昨日close"覆盖为"今日close", 此时pdc中存储的是今日close
        # 但这不会影响当天的pre_close读取(当天doc有pre_close字段), 只影响次日的fallback
        # 而次日首次调用时读的doc已有正确的pre_close, 所以fallback很少被触发
        pdc = getattr(self, '_prev_day_close', {})
        for code, price_info in result.items():
            if price_info.get('close', 0) > 0:
                lvp[code] = price_info['close']
                pdc[code] = price_info['close']
        self._last_valid_price = lvp
        self._prev_day_close = pdc

        return result

    def _compute_weights(self, candidates: list[str], factor_df, weight_method: str) -> dict[str, float]:
        """计算目标权重 - 根据权重方法分配权重

        【V3】策略席位制: 按strategy_weights分配max_stocks席位
        例: max_stocks=3, weights={半路:0.7, 首板:0.1, 龙头:0.1, 跌停:0.1}
        → 半路: ceil(3*0.7)=3, 首板: max(1,ceil(3*0.1))=1 → 总4(>3时按权重比缩减)
        """
        max_stocks = getattr(self, '_max_stocks', 3)
        strategy_weights = getattr(self, '_strategy_weights', {})
        stock_strategy = self.stock_to_strategy

        # 按策略分组候选
        strat_groups = {}  # strategy_name -> [(code, score)]
        # 【P1-2修复(V21):_compute_weights排序改用volume_ratio替代pct_chg,消除未来函数】
        # pct_chg是收盘涨跌幅(收盘后才知),实盘选股时无法使用
        # volume_ratio(量比)基于前5日均量,开盘时已确定,是可观测因子
        # 量比高=市场关注度高=更强势,在同一席位内优先选量比高的
        _score_map = {}
        if factor_df is not None and len(factor_df) > 0:
            if 'composite_score' in factor_df.columns:
                _score_map = dict(zip(factor_df['ts_code'], factor_df['composite_score'].fillna(0)))
            elif 'volume_ratio' in factor_df.columns:
                _score_map = dict(zip(factor_df['ts_code'], factor_df['volume_ratio'].fillna(0)))
        for code in candidates:
            strategies = stock_strategy.get(code, [])
            if isinstance(strategies, str): strategies = [strategies]
            
            row_score = _score_map.get(code, 0)

            # 归入每个策略组(一只股可属多个策略)
            for sname in strategies:
                if sname not in strat_groups:
                    strat_groups[sname] = []
                strat_groups[sname].append((code, row_score))

        # 按strategy_weights分配席位
        import math
        total_seats = max_stocks
        selected_codes = []

        if strategy_weights:
            # 计算每个策略的席位数
            seats = {}
            for sname, w in strategy_weights.items():
                seats[sname] = max(1, math.ceil(total_seats * w))  # 至少1席

            # 如果总席位>max_stocks,按权重比缩减
            total_allocated = sum(seats.values())
            if total_allocated > total_seats:
                # 按权重从大到小分配,直到用完
                sorted_strats = sorted(seats.keys(), key=lambda s: strategy_weights.get(s, 0), reverse=True)
                remaining = total_seats
                seats = {}
                for sname in sorted_strats:
                    alloc = max(1, round(total_seats * strategy_weights.get(sname, 0) / sum(strategy_weights.values())))
                    alloc = min(alloc, remaining)
                    seats[sname] = alloc
                    remaining -= alloc
                    if remaining <= 0:
                        break
                # 补上没有席位的策略
                for sname in strategy_weights:
                    if sname not in seats and remaining > 0:
                        seats[sname] = 1
                        remaining -= 1
        else:
            # 无权重配置时等分
            n_strats = len(strat_groups) or 1
            # 【V49-P0-2:按策略名排序确保确定性】
            seats = {s: max(1, total_seats // n_strats) for s in sorted(strat_groups.keys())}

        # 每个策略组内按分数排序取前N
        # 【V49-P0-2:按策略名排序确保确定性,避免dict迭代顺序不确定导致±3%回测结果波动】
        used_codes = set()
        for sname in sorted(strat_groups.keys()):
            group = strat_groups[sname]
            # 分数相同则按code排序,确保完全确定性
            group.sort(key=lambda x: (x[1], x[0]), reverse=True)
            n = seats.get(sname, 1)
            count = 0
            for code, score in group:
                if code not in used_codes and count < n:
                    selected_codes.append(code)
                    used_codes.add(code)
                    count += 1

        if weight_method == "equal":
            weight = 1.0 / len(selected_codes) if len(selected_codes) > 0 else 0
            return dict.fromkeys(selected_codes, weight)
        else:
            logger.warn('BACKTEST', f"权重方法'{weight_method}'未实现, 回退到等权重")
            weight = 1.0 / len(selected_codes) if len(selected_codes) > 0 else 0
            return dict.fromkeys(selected_codes, weight)

    @staticmethod
    def _get_limit_pct(ts_code: str) -> float:
        """【辅助函数】根据股票代码获取涨跌停幅度
        主板(60/00): 10%
        创业板(30): 20%
        科创板(68): 20%
        北交所(8/4): 30%
        """
        if ts_code.startswith('30') or ts_code.startswith('68'):
            return 0.20
        elif ts_code.startswith('8') or ts_code.startswith('4'):
            return 0.30
        else:
            return 0.10

    def _get_limit_up_price(self, ts_code: str, open_price: float, close_price: float,
                             high_price: float, low_price: float, pre_close: float = 0) -> float:
        """【辅助函数】计算涨停价买入价

        逻辑:
        1. 一字涨停板(open=close=high=low):open本身就是涨停价
        2. 非一字板涨停(收盘涨幅>=阈值):close即涨停价
        3. 非涨停日(高开未封板等):用pre_close*(1+涨停幅度)估算,不超过high

        【P0-2修复】涨停判断改用pre_close(昨收),原来用open导致高开涨停误判
        """
        limit_pct = self._get_limit_pct(ts_code)
        # 判断阈值:涨停幅度-0.5%容差(避免浮点误差)
        threshold = limit_pct - 0.005

        if open_price <= 0:
            return 0

        # 一字涨停板:四价相同,open本身就是涨停价
        # 【V54-Bug5修复:返回close_price而非0,让上层_get_buy_price_for_stock通过hit_probability=0正确处理】
        # 旧bug: 返回0→_get_buy_price_for_stock得到0→跳过买入→首板打板hit_probability_yizi=0逻辑从未执行
        # 新: 返回close_price,上层通过hit_probability决定是否成交,逻辑完整
        if (open_price == close_price == high_price == low_price) and open_price > 0:
            return close_price  # 一字板返回涨停价,由上层hit_probability处理成交概率

        # 非一字板涨停:【P0-2修复】用pre_close判断是否涨停
        if pre_close > 0:
            pct_from_pre_close = (close_price - pre_close) / pre_close
            if pct_from_pre_close >= threshold:
                return close_price
        else:
            # 回退:无pre_close时用open近似(兼容旧数据)
            pct_from_open = (close_price - open_price) / open_price
            if pct_from_open >= threshold:
                return close_price

        # 非涨停日:用昨收*(1+涨停幅度)估算涨停价,不超过high
        base_price = pre_close if pre_close > 0 else open_price
        return min(base_price * (1 + limit_pct), high_price)

    def _get_strategy_for_stock(self, code: str) -> str:
        """【辅助函数】获取股票的策略名(支持多策略选同股,取第一个策略)"""
        sinfo = self.stock_to_strategy.get(code, '')
        if isinstance(sinfo, list) and len(sinfo) > 0:
            return sinfo[0]  # 取第一个策略(最优先)
        return sinfo if isinstance(sinfo, str) else "策略选股"

    def _get_buy_price_for_stock(self, code: str, open_price: float, close_price: float,
                                  high_price: float, low_price: float, pre_close: float = 0) -> float:
        """计算买入价(多策略选同股时取最高买入价,最保守估算)

        【V29重构】委托给sell_signal_checker.get_buy_price_for_strategy,
        消除if/elif策略链。新增策略只需在STRATEGY_BUY_PRICE中注册。

        历史bug追踪:
        - V11: open+(high-open)*0.5用了当天high(未来函数) → open*(1+min_rise*0.8)
        - V12: 系数从0.7→0.8,平衡回测真实性和利润空间
        - V23: 多策略选同股取min→max(更保守估算)
        - V28: 龙头低吸系数0.25→0.20

        注意:这是对实盘价格的近似模拟,实际成交价可能有所不同
        """
        sinfo = self.stock_to_strategy.get(code, '')
        strategies = sinfo if isinstance(sinfo, list) else [sinfo]

        prices = []
        for sname in strategies:
            sp = getattr(self, '_strategy_params', {}).get(sname, {})
            p = get_buy_price_for_strategy(sname, code, open_price, close_price,
                                           high_price, low_price, pre_close, sp)
            # 特殊处理: 首板打板/涨停开板需要调用_get_limit_up_price
            if p == -1:
                p = self._get_limit_up_price(code, open_price, close_price, high_price, low_price, pre_close)
            if p > 0:
                prices.append(p)

        if not prices:
            return open_price
        # 【P1-4修复(V23):多策略选同股时取最高买入价,最保守估算】
        return max(prices)

    def _extract_position_multiplier(self, sentiment: str) -> float:
        """【辅助函数】从情绪等级字符串中提取仓位系数

        Args:
            sentiment: 情绪等级字符串,例如 "高潮期,仓位系数1.0"

        Returns:
            float: 仓位系数,默认 1.0
        """
        if not sentiment or "仓位系数" not in sentiment:
            return 1.0
        try:
            # 从 "高潮期,仓位系数1.0" 中提取 "1.0"
            idx = sentiment.find("仓位系数")
            if idx != -1:
                num_str = sentiment[idx + 4:].strip()
                return float(num_str)
        except (ValueError, IndexError):
            pass
        return 1.0

    # ==================== 【修复#7:统一策略筛选条件构建方法】 ====================
    # 【P1-9修复:策略中文名→ID映射,用于从STRATEGY_CONFIGS读取默认值】
    # 【P1-7修复】删除硬编码的_STRATEGY_NAME_TO_ID,从STRATEGY_CONFIGS动态生成
    @property
    def _strategy_name_to_id(self):
        """从strategy_defaults.py动态生成策略名→ID映射"""
        return {cfg['name']: sid for sid, cfg in STRATEGY_CONFIGS.items()}

    def _build_strategy_filter_conditions(self, strategy_name: str, params: dict) -> list:
        """【统一入口】构建单个策略的因子筛选条件

        【P1-9说明:筛选条件应从strategy_defaults.py动态生成】
        当前实现硬编码了条件,与strategy_defaults.py的params可能不同步。
        理想方案:从STRATEGY_CONFIGS[strategy_id].params读取参数,动态生成条件。
        但当前params的字段名与筛选条件的字段名不完全对应(如min_rise_pct vs rise_pct),
        需要一个映射层。此修复涉及重构,暂不执行,仅标注。

        消除3处重复定义:强制空仓分支、正常调仓分支、_print_single_strategy_filtering 中都有相同的条件定义

        【修复#44:参数单位统一】
        - min_turnover_rate: 统一为百分比单位(例如 3 代表 3%,不再用 0.03)
        - max_turnover_rate: 统一为百分比单位
        - min_volume_ratio: 统一为倍数值

        Args:
            strategy_name: 策略名称(中文)
            params: 策略参数字典

        Returns:
            list: 策略筛选条件列表,每个元素是 {name, target, operator, label}
        """
        converted_params = {}
        for k, v in params.items():
            if isinstance(v, bool):
                converted_params[k] = 1 if v else 0
            elif isinstance(v, str) and v.replace(".", "", 1).isdigit():
                converted_params[k] = float(v)
            else:
                converted_params[k] = v

        # 【P1-9修复:从STRATEGY_CONFIGS读取默认值,不再硬编码】
        strategy_id = self._strategy_name_to_id.get(strategy_name, "")
        strategy_defaults = STRATEGY_CONFIGS.get(strategy_id, {}).get("params", {})

        if strategy_name == "半路追涨":
            min_rise_pct = converted_params.get("min_rise_pct") if converted_params.get("min_rise_pct") is not None else strategy_defaults.get("min_rise_pct", 0.03)
            max_rise_pct = converted_params.get("max_rise_pct") if converted_params.get("max_rise_pct") is not None else strategy_defaults.get("max_rise_pct", 0.07)
            min_volume_ratio = converted_params.get("min_volume_ratio") if converted_params.get("min_volume_ratio") is not None else strategy_defaults.get("min_volume_ratio", 2.0)
            max_volume_ratio = converted_params.get("max_volume_ratio") if converted_params.get("max_volume_ratio") is not None else strategy_defaults.get("max_volume_ratio", 3.0)
            min_close_rise = converted_params.get("min_close_rise_pct") if converted_params.get("min_close_rise_pct") is not None else strategy_defaults.get("min_close_rise_pct", 0.05)
            max_open_rise = converted_params.get("max_open_rise_pct") if converted_params.get("max_open_rise_pct") is not None else strategy_defaults.get("max_open_rise_pct", 0.03)
            # 【方案B优化】开盘涨幅上限: 高开>3%追高胜率仅44%, 低开冲高81.5%胜率
            # 核心逻辑: 低开/平开→盘中放量冲高→收盘站稳→次日惯性上涨
            # 【V18未来函数审查】：半路追涨因子时间点分析
            # 半路追涨是"盘中确认"策略: 9:30后观察涨幅达3%+放量 → 买入
            # 因子时间点分类:
            # ✅ intraday_max_rise_pct — 盘中high逐步形成，9:30后可观测
            #    买入价open*(1+0.8*min_rise)模拟了涨到3%时买入，逻辑自洽
            # ✅ intraday_open_rise_pct — 竞价数据，9:25可知
            # ✅ volume_ratio — 盘中可看实时量比，日线近似可接受
            # ⚠️ pct_chg — 收盘涨幅(纯收盘数据)，用于"收盘确认站稳"
            #
            # 【pct_chg未来函数分析】:
            # 严格定义: pct_chg是T日收盘数据，在盘中任何时点都不可知，属于未来函数
            # 但实测验证: 去掉pct_chg≥5%后，候选从每天2-5只暴涨到100-200只
            #   导致策略退化(收益69%→-13%，胜率68%→38%)
            # 原因: intraday_max_rise_pct≥3%只过滤了"盘中冲高"，没有过滤"冲高回落"
            #   pct_chg≥5%实际上过滤了"盘中冲高但收盘回落"的假信号
            #
            # 【修复方案(需架构改动)】:
            # 方案1: 保留pct_chg收盘确认 + 买入价改为close*(1+slippage)(收盘价买入)
            #         逻辑: 14:50确认站稳→收盘价附近买入→T+1卖出
            # 方案2: 保留pct_chg收盘确认 + T日选股T+1买入(延迟1天)
            #         逻辑: T日收盘确认→T+1开盘买入
            # 当前: 保留pct_chg≥5% + 盘中买入价，标注为已知未来函数，待架构支持后修复
            conditions = [
                {"name": "intraday_max_rise_pct", "target": min_rise_pct * 100, "operator": ">=", "label": f"盘中最高涨幅≥{min_rise_pct*100:.0f}%"},
                {"name": "intraday_max_rise_pct", "target": max_rise_pct * 100, "operator": "<=", "label": f"盘中最高涨幅≤{max_rise_pct*100:.0f}%"},
                {"name": "intraday_open_rise_pct", "target": max_open_rise * 100, "operator": "<=", "label": f"开盘涨幅≤{max_open_rise*100:.0f}%(排除高开追高)"},
                # 【P1-4修复(V27):volume_ratio改用volume_ratio_prev(T-1日),消除未来函数】
                # 实盘中量比开盘时可观测(基于前5日均量),但日线volume_ratio是全天数据
                # volume_ratio_prev更严格保守,避免用T日全天量比做选股决策
                {"name": "volume_ratio_prev", "target": min_volume_ratio, "operator": ">=", "label": f"量比≥{min_volume_ratio}"},
            ]
            # 量比上限: >3过热回调,胜率反而下降
            if max_volume_ratio and max_volume_ratio < 100:
                conditions.append({"name": "volume_ratio_prev", "target": max_volume_ratio, "operator": "<=", "label": f"量比≤{max_volume_ratio}(不过热)"})
            # ⚠️【已知未来函数近似】: pct_chg是T日收盘数据，盘中不可知
            # 含义: "收盘确认站稳"——过滤冲高回落的假信号
            # 实测V25: close买入→收益226%→46%,胜率76%→42%,代价过大
            # 结论: 保留盘中买入价+收盘确认作为实盘近似(经验交易员盘中趋势判断)
            if min_close_rise and min_close_rise > 0:
                conditions.append({"name": "pct_chg", "target": min_close_rise * 100, "operator": ">=", "label": f"收盘涨幅≥{min_close_rise*100:.0f}%(⚠近似,盘中趋势判断)"})
            return conditions

        elif strategy_name == "首板打板":
            # 【V3改造】首板打板:T-1预选 + T日竞价确认 + 盘中封板
            # 核心变化:
            # 1. 去掉limit_up_open_count/hot_sector/limit_up_time(数据全0)
            # 2. 去掉limit_up_open_amount(日线无法计算盘中封单)
            # 3. 用first_limit_up=1作为T日盘中封板确认(日线可推断)
            # 4. 保留opening_pct_chg作为竞价筛选(9:25可观测)
            # 5. 成交概率在_rebalance中模拟(一字板0%/秒板10%/快速板30%/盘中板50%)
            # 【P1-9修复:circ_mv单位是万元,参数单位是亿,需×10000转换】
            min_circ_mv = (converted_params.get("min_circulation_market_cap") if converted_params.get("min_circulation_market_cap") is not None else strategy_defaults.get("min_circulation_market_cap", 50)) * 10000
            max_circ_mv = (converted_params.get("max_circulation_market_cap") if converted_params.get("max_circulation_market_cap") is not None else strategy_defaults.get("max_circulation_market_cap", 500)) * 10000
            min_volume_ratio = converted_params.get("min_volume_ratio") if converted_params.get("min_volume_ratio") is not None else strategy_defaults.get("min_volume_ratio", 1.5)
            min_turnover = converted_params.get("min_turnover_rate") if converted_params.get("min_turnover_rate") is not None else strategy_defaults.get("min_turnover_rate", 3)
            max_turnover = converted_params.get("max_turnover_rate") if converted_params.get("max_turnover_rate") is not None else strategy_defaults.get("max_turnover_rate", 15)
            # 【P0-3修复:从STRATEGY_CONFIGS读取fallback,不硬编码】
            opening_pct_min = converted_params.get("opening_pct_min") if converted_params.get("opening_pct_min") is not None else strategy_defaults.get("opening_pct_min", -1.0)
            opening_pct_max = converted_params.get("opening_pct_max") if converted_params.get("opening_pct_max") is not None else strategy_defaults.get("opening_pct_max", 7.0)
            return [
                {"name": "first_limit_up", "target": 1, "label": "首次涨停(盘中封板)"},
                {"name": "limit_up_yesterday", "target": 0, "label": "昨日未涨停(T-1预选)"},
                {"name": "opening_pct_chg", "target": opening_pct_min, "operator": ">=", "label": f"竞价涨幅≥{opening_pct_min}%"},
                {"name": "opening_pct_chg", "target": opening_pct_max, "operator": "<=", "label": f"竞价涨幅≤{opening_pct_max}%"},
                {"name": "volume_ratio_prev", "target": min_volume_ratio, "operator": ">=", "label": f"量比≥{min_volume_ratio}"},
                {"name": "turnover_rate_prev", "target": min_turnover, "operator": ">=", "label": f"换手率≥{min_turnover}%"},
                {"name": "turnover_rate_prev", "target": max_turnover, "operator": "<=", "label": f"换手率≤{max_turnover}%"},
                {"name": "circ_mv_prev", "target": min_circ_mv, "operator": ">=", "label": f"流通市值≥{min_circ_mv//10000}亿"},
                {"name": "circ_mv_prev", "target": max_circ_mv, "operator": "<=", "label": f"流通市值≤{max_circ_mv//10000}亿"},
            ]
        elif strategy_name == "涨停开板":
            min_consecutive = converted_params.get("min_consecutive_limit") if converted_params.get("min_consecutive_limit") is not None else strategy_defaults.get("min_consecutive_limit", 2)
            max_consecutive = converted_params.get("max_consecutive_limit") if converted_params.get("max_consecutive_limit") is not None else strategy_defaults.get("max_consecutive_limit", 4)
            _raw_turnover = converted_params.get("min_turnover_rate")
            min_turnover = _raw_turnover if _raw_turnover is not None else strategy_defaults.get("min_turnover_rate", 15.0)
            min_volume_ratio = converted_params.get("min_volume_ratio") if converted_params.get("min_volume_ratio") is not None else strategy_defaults.get("min_volume_ratio", 2.0)
            require_sentiment = converted_params.get("require_sentiment_period", ["rising"])
            # 【日线模式修复】涨停开板的盘中数据(limit_up_open_duration/limit_up_open_amount/limit_up_time)
            # 在日线回测中全为0,无法区分。改为日线可观测条件:
            # - limit_up_yesterday=1: 昨日涨停(连板候选)
            # - is_limit_up=0: 今日未封住(开板)
            # - pct_chg>=0: 今日仍有涨幅(非大跌)
            # - volume_ratio放大: 开板时放量
            # - turnover_rate: 换手活跃
            return [
                {"name": "limit_up_yesterday", "target": 1, "operator": "==", "label": "昨日涨停(连板候选)"},
                {"name": "is_limit_up", "target": 0, "operator": "==", "label": "今日未封住(开板)"},
                # 【V36优化:盘中最高涨幅≥5%】is_limit_up=0只表示今日未封住,但包含大量无涨停动作的普通股
                # 加intraday_max_rise_pct>=5%过滤,确保是"冲高后开板"而非"从未冲高"
                {"name": "intraday_max_rise_pct", "target": 5, "operator": ">=", "label": "盘中最高涨幅≥5%(曾有涨停动作)"},
                # 【P1-2修复(V28):volume_ratio→volume_ratio_prev,消除未来函数,与半路追涨/首板打板对齐】
                {"name": "volume_ratio_prev", "target": min_volume_ratio, "operator": ">=", "label": f"量比≥{min_volume_ratio}"},
                {"name": "turnover_rate_prev", "target": min_turnover, "operator": ">=", "label": f"换手率≥{min_turnover}%"},
                {"name": "sentiment_period_in", "target": require_sentiment, "operator": "in", "label": "情绪周期要求"},
            ]
        elif strategy_name == "龙头低吸":
            # 【P1-9修复:默认值从STRATEGY_CONFIGS读取】
            min_consecutive = converted_params.get("min_consecutive_limit") if converted_params.get("min_consecutive_limit") is not None else strategy_defaults.get("min_consecutive_limit", 1)
            min_correction = converted_params.get("min_correction_pct") if converted_params.get("min_correction_pct") is not None else strategy_defaults.get("min_correction_pct", 0.05)
            max_correction = converted_params.get("max_correction_pct") if converted_params.get("max_correction_pct") is not None else strategy_defaults.get("max_correction_pct", 0.20)
            correction_days_min = converted_params.get("correction_days_min") if converted_params.get("correction_days_min") is not None else strategy_defaults.get("correction_days_min", 1)
            correction_days_max = converted_params.get("correction_days_max") if converted_params.get("correction_days_max") is not None else strategy_defaults.get("correction_days_max", 7)
            support_level = converted_params.get("support_level") if converted_params.get("support_level") is not None else strategy_defaults.get("support_level", "ma5")
            # 【P0-3修复(第十轮):market_leader因子在MongoDB中全0,无法用于龙头筛选】
            # 替代方案:用circ_mv(流通市值)识别龙头股--大市值更可能是龙头
            # 【注意】circ_mv单位是万元,参数单位是亿,需×10000转换
            _min_circ_for_leader = (converted_params.get("min_circulation_market_cap") if converted_params.get("min_circulation_market_cap") is not None else strategy_defaults.get("min_circulation_market_cap", 30)) * 10000
            _min_vr = converted_params.get("min_volume_ratio") if converted_params.get("min_volume_ratio") is not None else strategy_defaults.get("min_volume_ratio", 0.5)
            _max_vr = converted_params.get("max_volume_ratio") if converted_params.get("max_volume_ratio") is not None else strategy_defaults.get("max_volume_ratio", 2.0)
            return [
                # 【V35修复:circ_mv改用circ_mv_prev(T-1日),消除未来函数,与其他策略一致】
                # circ_mv日间变化极小(<1%),用_prev对筛选结果影响微小
                {"name": "circ_mv_prev", "target": _min_circ_for_leader, "operator": ">=", "label": f"流通市值≥{_min_circ_for_leader//10000}亿(龙头)"},
                {"name": "limit_up_count", "target": min_consecutive, "operator": ">=", "label": f"近5日至少{min_consecutive}板"},
                # 【Bug修复】pullback_pct在MongoDB中存负数(如-0.15=回调15%)
                # close < high_peak → pullback_pct < 0 → 回调时是负值
                # 所以:回调≥5% → pullback_pct <= -0.05, 回调≤35% → pullback_pct >= -0.35
                {"name": "pullback_pct", "target": -max_correction, "operator": ">=", "label": f"回调≤{max_correction*100:.0f}%(不超跌)"},
                {"name": "pullback_pct", "target": -min_correction, "operator": "<=", "label": f"回调≥{min_correction*100:.0f}%"},
                {"name": "pullback_days", "target": correction_days_min, "operator": ">=", "label": "最小回调天数"},
                {"name": "pullback_days", "target": correction_days_max, "operator": "<=", "label": "最大回调天数"},
                # 【V3】去掉pullback_ma5硬性条件(数据质量差,15→0只)
                # MA5支撑作为概念参考,不强制要求pullback_ma5=1
                # 量比双限: VR<0.5极度冷门(几乎无成交), VR>2.0放量回调(抛压未止)
                # 数据: VR<0.8胜率50.2%(抛压枯竭), VR 0.8-1.5胜率44.1%, VR 1.5-2.0胜率47.4%
                # 【V27/V35注意】龙头低吸volume_ratio保留T日数据,不用_prev
                # 原因: 龙头低吸的信号是“缩量回调后T日开始放量”,T-1日还是缩量状态
                # 用volume_ratio_prev会把“T日放量启动”的高胜率候选过滤掉(收益-90%)
                # volume_ratio在盘中可观测(基于前5日均量推算),是准实时因子
                # ⚠️ 已知未来函数近似: T日VR全天值在盘中不完全可知,但盘中实时VR可近似
                {"name": "volume_ratio", "target": _min_vr, "operator": ">=", "label": f"量比≥{_min_vr}(保流动性)"},
                {"name": "volume_ratio", "target": _max_vr, "operator": "<=", "label": f"量比≤{_max_vr}(缩量回调)"},
            ]
        elif strategy_name == "跌停翘板":
            # 【P1-9修复:默认值从STRATEGY_CONFIGS读取】
            min_consecutive = converted_params.get("min_consecutive_limit") if converted_params.get("min_consecutive_limit") is not None else strategy_defaults.get("min_consecutive_limit", 2)
            # 【修复#47: min_qiao_amount单位统一为千元(与数据库limit_down_open_amount一致)】
            _raw_qiao = converted_params.get("min_qiao_amount") if converted_params.get("min_qiao_amount") is not None else strategy_defaults.get("min_qiao_amount", 1000)
            min_qiao_amount = _raw_qiao * 10 if _raw_qiao < 100000 else _raw_qiao
            min_rise_after = converted_params.get("min_rise_after_qiao") if converted_params.get("min_rise_after_qiao") is not None else strategy_defaults.get("min_rise_after_qiao", 0.03)
            require_high_sentiment = converted_params.get("require_high_sentiment") if converted_params.get("require_high_sentiment") is not None else strategy_defaults.get("require_high_sentiment", False)
            require_sentiment = converted_params.get("require_sentiment_period", ["rising", "chaos"])
            # 【P0-1修复(V24):min_turnover_rate从STRATEGY_CONFIGS读取,不再硬编码】
            min_turnover_qiao = converted_params.get("min_turnover_rate") if converted_params.get("min_turnover_rate") is not None else strategy_defaults.get("min_turnover_rate", 10.0)
            # 【修复:min_turnover_rate前端可能传小数(0.10=10%),需转换】
            if min_turnover_qiao < 1:
                min_turnover_qiao *= 100
            # 【P1-6修复(V13)】:circ_mv从参数读取,不再硬编码200000
            # circ_mv单位是万元,参数单位是亿,需×10000转换
            _min_circ_qiao = (converted_params.get("min_circulation_market_cap") if converted_params.get("min_circulation_market_cap") is not None else strategy_defaults.get("min_circulation_market_cap", 20)) * 10000
            return [
                {"name": "limit_down_yesterday", "target": 1, "label": "昨日跌停"},
                {"name": "open_above_limit_down", "target": 1, "label": "开盘高于跌停价(不继续跌停)"},
                # 【V18注意】circ_mv用T日收盘价计算(理论上未来函数)，但日间变化极小(<1%)，可接受
                # 【P1-2修复(V27):circ_mv改用circ_mv_prev(T-1日),严格消除未来函数】
                # 实盘开盘时T日circ_mv未知,应使用T-1日数据更保守
                # T-1日circ_mv与T日差异极小(<1%),对筛选结果影响微小
                {"name": "circ_mv_prev", "target": _min_circ_qiao, "operator": ">=", "label": f"流通市值≥{_min_circ_qiao//10000}亿(排除小盘操纵)"},
                # 【V18注意】turnover_rate是T日全天换手率(未来函数)，但跌停翘板要求换手率高是合理的
                # 实盘中可通过开盘10分钟换手率推算，日线回测只能用全天数据近似
                # 【P1-3修复(V27):turnover_rate改用turnover_rate_prev(T-1日),消除未来函数】
                # 实盘开盘时T日turnover未知,用T-1日数据更保守
                # 跌停翘板候选股通常前一日也有较高换手(翘板当天换手暴增)
                {"name": "turnover_rate_prev", "target": min_turnover_qiao, "operator": ">=", "label": f"换手率≥{min_turnover_qiao:.0f}%"},
                # 【P0-3修复(V12→V12.1)】:翘板金额过滤改为target=0(跳过)
                # limit_down_open_amount因子98%为0(数据质量问题),无法可靠使用
                # 设target=0后_print_single_strategy_filtering会自动跳过此条件
                # 待因子数据完善后再启用
                {"name": "limit_down_open_amount", "target": 0, "operator": ">=", "label": f"翘板金额(数据不全,暂不过滤)"},
                # 【V18未来函数分析】：跌停翘板的pct_chg>0是否为未来函数?
                # 分析: 跌停翘板是“盘中确认”策略，实盘流程:
                #   1. 开盘看到不继续跌停(open_above_limit_down=1) → 观察候选
                #   2. 盘中在低位买入(low附近)
                #   3. 收盘确认翘板成功(pct_chg>0) → 这是收盘确认，不是未来函数
                # 结论: pct_chg>0是收盘确认条件，与盘中买入逻辑自洽
                #   盘中买入 → 收盘确认是否成功 → 如果不成功(pct_chg<=0)则次日止损
                #   所以pct_chg>0不是选股未来函数，而是收盘确认条件
                {"name": "pct_chg", "target": 0, "operator": ">", "label": "今日收涨(确认翘板资金)"},
                {"name": "sentiment_period_in", "target": require_sentiment if require_high_sentiment else [], "operator": "in", "label": "情绪周期要求"},
            ]
        else:
            return []

    def _get_sl_tp_for_code(self, code: str):
        """获取某只股票对应的策略级止损止盈参数

        止损:取min(最严格,风险管理不受策略选择影响)
        止盈:取第一个策略(买入策略)的TP,不用max
        【V31修复:TP取max导致龙头低吸+跌停翘板同股时止盈线被错误提升到25%】
        旧: max(0.15, 0.25) = 0.25 → 龙头低吸止盈线虚高
        新: 取买入策略(第一个)的TP → 龙头低吸0.15,跌停翘板0.25,各取所需
        """
        strategies = self.stock_to_strategy.get(code, [])
        strategy_rp = getattr(self, '_strategy_risk_params', {})
        global_sl = self._risk_config.get('stop_loss_pct', GLOBAL_RISK['stop_loss_pct'])
        global_tp = self._risk_config.get('take_profit_pct', 0.07)
        if isinstance(strategies, list) and strategies:
            # 止损:取min(最严格,不管哪个策略买入都应尽早止损)
            sl = min(strategy_rp.get(s, {}).get('stop_loss_pct', global_sl) for s in strategies)
            # 止盈:取买入策略(第一个)的TP,不用max
            # 原因:不同策略止盈逻辑不同,龙头低吸15% vs 跌停翘板25%
            # max会虚增龙头低吸止盈线到25%,错过15%-25%区间的高位卖出
            tp = strategy_rp.get(strategies[0], {}).get('take_profit_pct', global_tp)
            return sl, tp
        return global_sl, global_tp

    def _get_slippage_for_code(self, code: str):
        """获取某只股票对应的策略级滑点"""
        strategies = self.stock_to_strategy.get(code, [])
        strategy_rp = getattr(self, '_strategy_risk_params', {})
        global_slippage = self._slippage_pct
        if isinstance(strategies, list) and strategies:
            return max(strategy_rp.get(s, {}).get('slippage_pct', global_slippage) for s in strategies)
        return global_slippage



    def _calc_total_value(self, cash: float, holdings: dict, prices: dict) -> float:
        """【P1-7修复:提取持仓总价值计算为独立方法】
        用open价估值持仓计算总资产(调仓决策时刻)
        """
        total_value = cash
        for code, shares in holdings.items():
            if shares > 0:
                if code in prices and prices[code].get('open', 0) > 0:
                    total_value += shares * prices[code]['open']
                elif code in prices and prices[code].get('close', 0) > 0:
                    total_value += shares * prices[code]['close']
                else:
                    lvp = getattr(self, '_last_valid_price', {}).get(code, 0)
                    if lvp > 0:
                        total_value += shares * lvp
        return total_value

    def _calc_position_multiplier(self, sentiment: str, trade_date: int) -> tuple:
        """【P1-7修复:提取综合仓位系数计算为独立方法】
        Returns: (position_multiplier, active_periods)
        """
        sentiment_multiplier = self._extract_position_multiplier(sentiment)
        special_period_filter = get_special_period_filter()
        special_multiplier = special_period_filter.get_position_multiplier(str(trade_date))
        active_periods = special_period_filter.get_active_periods(str(trade_date))
        position_multiplier = sentiment_multiplier * special_multiplier
        return position_multiplier, active_periods

    def _apply_limit_up_hit_probability(self, target_shares: dict, prices: dict, trade_date: int) -> dict:
        """【V37:首板打板成交概率模拟】
        一字板0%/秒板20%/快速板45%/盘中板65%, 用确定性hash保证可复现
        V37调整: 从0/25/50/70→0/20/45/65,更保守避免过多低质量成交
        Returns: 修改后的target_shares
        """
        _limit_up_codes = []
        sinfo = self.stock_to_strategy
        for code in list(target_shares.keys()):
            strategies = sinfo.get(code, [])
            if isinstance(strategies, str):
                strategies = [strategies]
            if '首板打板' in strategies:
                _limit_up_codes.append(code)

        if _limit_up_codes and len(prices) > 0:
            import hashlib
            for code in _limit_up_codes:
                p_info = prices.get(code, {})
                o = p_info.get('open', 0)
                pc = p_info.get('pre_close', 0)
                c = p_info.get('close', 0)
                h = p_info.get('high', 0)
                l = p_info.get('low', 0)

                if o <= 0 or pc <= 0:
                    continue

                open_rise = (o - pc) / pc * 100
                sp = self._strategy_params.get('首板打板', {})
                # 【V36:从strategy_defaults读取,默认值与STRATEGY_CONFIGS同步】
                hit_prob_yizi = sp.get('hit_probability_yizi', 0.0)
                hit_prob_fast = sp.get('hit_probability_fast', 0.20)
                hit_prob_normal = sp.get('hit_probability_normal', 0.40)  # 【V58-BUG-001修复:从0.45→0.40,与strategy_defaults.py V57对齐】
                hit_prob_slow = sp.get('hit_probability_slow', 0.45)  # 【V58-BUG-001修复:从0.65→0.45,与strategy_defaults.py V57对齐;旧值0.65远超默认0.45,导致过多低质量首板成交】

                if o == c == h == l:
                    hit_prob = hit_prob_yizi
                elif open_rise >= 8:
                    hit_prob = hit_prob_fast
                elif open_rise >= 2:
                    hit_prob = hit_prob_normal
                else:
                    hit_prob = hit_prob_slow

                if hit_prob > 0:
                    seed_str = f"{code}_{trade_date}"
                    hash_val = int(hashlib.md5(seed_str.encode()).hexdigest(), 16) % 1000 / 1000.0
                    if hash_val > hit_prob:
                        del target_shares[code]
                        logger.info('backtest', f'[首板打板] {code} 成交概率{hit_prob*100:.0f}%→未成交(deterministic)')
                    else:
                        logger.info('backtest', f'[首板打板] {code} 成交概率{hit_prob*100:.0f}%→成交(deterministic)')
                else:
                    del target_shares[code]
                    logger.info('backtest', f'[首板打板] {code} 一字板→不成交')
        return target_shares

    def _rebalance(self, trade_date: int, target_weights: dict[str, float],
                       cash: float, holdings: dict[str, int], prices: dict[str, float], sentiment: str = ""):
        """执行调仓

        【P1-7说明:本方法453行,逻辑复杂但不可拆分】
        原因:调仓是单次原子操作,拆分会导致状态传递复杂化。
        内部逻辑分为4段:1)卖出决策 2)买入决策 3)止损止盈 4)强制空仓
        每段依赖前一段的状态更新,拆分后需要6+个中间状态变量。
        如需拆分,建议将4段提取为私有方法,但保持_rebalance作为唯一入口。

        Args:
            trade_date: 当前调仓日期
            target_weights: 目标权重 {ts_code: weight}
            cash: 当前现金
            holdings: 当前持仓 {ts_code: shares}
            prices: 当前价格 {ts_code: price}
            sentiment: 情绪等级字符串(含仓位系数)

        Returns:
            (new_cash, new_holdings, records)
        """
        records = []

        # 【P1-7修复:调用提取的子方法】
        total_value = self._calc_total_value(cash, holdings, prices)
        position_multiplier, active_periods = self._calc_position_multiplier(sentiment, trade_date)

        # 计算目标持仓(用策略对应买入价计算仓位,而非开盘价)
        target_shares = {}  # {ts_code: target_shares}
        # 【P1-2修复:max_position_per_stock 单票仓位上限】
        max_pos_per_stock = self._risk_config.get('max_position_per_stock', 1.0)
        for code, weight in target_weights.items():
            if code not in prices:
                continue
            # ✅ 应用综合仓位系数!
            # 例如:情绪冰点 0.3 × 春节前夕 0.2 = 0.06 → 只有 6% 仓位
            p_info = prices[code]
            o = p_info.get('open', 0)
            h = p_info.get('high', o)
            l = p_info.get('low', o)
            # 【P1-1修复:多策略选同股时取最低买入价】
            buy_p = self._get_buy_price_for_stock(code, o, p_info.get('close', o), h, l, p_info.get('pre_close', 0))
            if buy_p <= 0:
                buy_p = o
            if buy_p <= 0:
                continue  # 无法确定买入价,跳过该股
            # 【P1-2修复:仓位上限 = min(weight * position_multiplier, max_position_per_stock)】
            effective_weight = min(weight * position_multiplier, max_pos_per_stock)
            target_value = total_value * effective_weight
            shares = int(int(target_value / buy_p) / 100) * 100
            if shares > 0:
                target_shares[code] = shares

        # 【P1-7修复:调用提取的子方法】
        target_shares = self._apply_limit_up_hit_probability(target_shares, prices, trade_date)

        # 先卖出:不在目标持仓中的股票全卖 + 持仓超过目标的股票减仓
        sell_codes_raw = [code for code in holdings if code not in target_shares and holdings[code] > 0]
        # 【V48d:P0修复:不在目标池的股票也要检查止损/冲高回落,取更优卖出价】
        # Bug: 301141.SZ cost=87.87, sl=85.23, low=84.49<sl→应该止损@85.23而不是调仓@84.59
        # 同理: 冲高回落以open价卖出>调仓卖出以close价→应选更优价
        # 修复: 对sell_codes中的股票也检查止损/冲高回落,记录更优卖出价格和原因
        # 先读取风控开关,后续_rebalance止损检查也要用
        enable_stop_loss = self._risk_config.get('enable_stop_loss', True)
        enable_take_profit = self._risk_config.get('enable_take_profit', True)
        _sell_code_details = {}  # {code: (sell_price, sell_reason)}
        for code in sell_codes_raw:
            if holdings.get(code, 0) <= 0:
                continue
            buy_dt = self._cost_basis_date.get(code)
            if buy_dt is not None and buy_dt == trade_date:
                _sell_code_details[code] = (None, '调仓卖出')  # T+1限制
                continue
            p = prices.get(code, {})
            cost = self._cost_basis.get(code, 0)
            if cost <= 0 or not isinstance(p, dict) or p.get('close', 0) <= 0:
                _sell_code_details[code] = (None, '调仓卖出')
                continue
            close_p = p.get('close', 0)
            open_p = p.get('open', close_p)
            low_p = p.get('low', close_p)
            high_p = p.get('high', close_p)
            code_sl, code_tp = self._get_sl_tp_for_code(code)
            stop_price = cost * (1 - code_sl)
            tp_price = cost * (1 + code_tp)
            _strategies = self.stock_to_strategy.get(code, [])
            if isinstance(_strategies, str): _strategies = [_strategies]
            best_price = close_p  # 默认调仓卖出用close
            best_reason = '调仓卖出'
            # 1. 冲高回落/利润保护/高开即卖(优先级高,以open价卖出)
            early_sell_price, early_sell_reason = self._check_early_sell_signals(
                code, _strategies, cost, open_p, close_p)
            if early_sell_price > 0 and early_sell_price > best_price:
                best_price = early_sell_price
                best_reason = early_sell_reason
            # 2. 止损: 如果low<=stop_price, 以止损价卖出(优于收盘价当收盘更差时)
            if enable_stop_loss and low_p <= stop_price:
                sl_sell_price = open_p if open_p <= stop_price else stop_price
                if sl_sell_price > best_price:
                    best_price = sl_sell_price
                    best_reason = '跳空止损' if open_p <= stop_price else f'止损({code_sl*100:.0f}%)'
            # 3. 止盈: 如果high>=tp_price, 以止盈价卖出(优于收盘价当收盘更差时)
            if enable_take_profit and high_p >= tp_price:
                if tp_price > best_price:
                    best_price = tp_price
                    best_reason = f'止盈({code_tp*100:.0f}%)'
            # 【V49-P0-3:利润锁定检查——不在目标池的股票也检查盘中冲高回撤】
            # 【V55-BUG-001修复:提取为_check_intraday_profit_lock方法,消除重复代码】
            if best_reason == '调仓卖出' and high_p > 0 and close_p > 0 and cost > 0:
                if self._check_intraday_profit_lock(cost, high_p, close_p, code):
                    best_reason = '利润锁定'
            _sell_code_details[code] = (best_price, best_reason)
        
        sell_codes = sell_codes_raw
        # 【V33关键修复:pos_mgr接管target_shares的所有修改权】
        # 旧bug(V29宣称修复但未完全修复): PositionManager复制了target_shares, mark_sold只修改pos_mgr.target_shares
        # 但买入循环仍遍历原始局部target_shares→冲高回落/止损卖出后同日重新买入(震荡bug)
        # 修复: 买入循环改用pos_mgr.target_shares, 确保mark_sold删除的股不会被重新买入
        pos_mgr = PositionManager(holdings, target_shares)

        # 【V48d:将_sell_code_details中更好的卖出原因标记到pos_mgr】
        # 这样卖出循环会使用更优的卖出价(止损价>close价/冲高回落open价>close价)
        for code, (best_price, best_reason) in _sell_code_details.items():
            if best_reason != '调仓卖出' and code in sell_codes:
                pos_mgr.mark_sold(code, best_reason)

        # 【P0-4修复:调仓日止损检查 - 即使股票仍在目标池中,如果触发止损也要卖出】
        # 之前bug: 止损只对"不在目标池"的股票生效,导致16笔交易亏损>3%止损线却未触发
        # 注意:_rebalance是同步方法,不能使用await,复用已有的prices参数
        # enable_stop_loss/enable_take_profit已在上方V48d处定义
        if (enable_stop_loss or enable_take_profit) and holdings:
            _sl_tp_codes = set(holdings.keys()) - set(sell_codes)  # 还在目标池中的持仓
            for code in list(_sl_tp_codes):
                if holdings.get(code, 0) <= 0:
                    continue
                # T+1: 当日买入不可止损卖出
                buy_dt = self._cost_basis_date.get(code)
                if buy_dt is not None and buy_dt == trade_date:
                    continue
                p = prices.get(code, {})
                cost = self._cost_basis.get(code, 0)
                if cost <= 0 or not isinstance(p, dict) or p.get('close', 0) <= 0:
                    continue
                code_sl, code_tp = self._get_sl_tp_for_code(code)
                stop_price = cost * (1 - code_sl)
                tp_price = cost * (1 + code_tp)
                low_p = p.get('low', p.get('close', 0))
                high_p = p.get('high', p.get('close', 0))
                open_p = p.get('open', p.get('close', 0))
                _close_p = p.get('close', 0)
                _strategies = self.stock_to_strategy.get(code, [])
                if isinstance(_strategies, str): _strategies = [_strategies]
                early_sell_price, early_sell_reason = self._check_early_sell_signals(
                    code, _strategies, cost, open_p, _close_p)
                if early_sell_price > 0:
                    sell_codes.append(code)
                    pos_mgr.mark_sold(code, early_sell_reason)  # V29:统一管理
                elif enable_stop_loss and low_p <= stop_price:
                    sell_codes.append(code)
                    reason = '跳空止损' if open_p <= stop_price else f'止损({code_sl*100:.0f}%)'
                    pos_mgr.mark_sold(code, reason)
                elif enable_take_profit and high_p >= tp_price:
                    sell_codes.append(code)
                    pos_mgr.mark_sold(code, f'止盈({code_tp*100:.0f}%)')
                # 【V48:调仓日也检查利润锁定——此前只在_check_and_execute_forced_sells中检查】
                # 【V55-BUG-001修复:提取为_check_intraday_profit_lock方法,消除重复代码】
                elif code not in sell_codes:
                    if high_p > 0 and _close_p > 0 and cost > 0:
                        if self._check_intraday_profit_lock(cost, high_p, _close_p, code):
                            sell_codes.append(code)
                            pos_mgr.mark_sold(code, '利润锁定')
        # 【Phase1-T+1】排除当日买入的股票(T+1: 当日买入不可卖出)
        # 【V49-P0-3修复:改用列表推导替代循环内remove,避免O(n²)和跳过元素bug】
        t1_blocked = [code for code in sell_codes
                      if self._cost_basis_date.get(code) is not None and self._cost_basis_date.get(code) == trade_date]
        sell_codes = [code for code in sell_codes if code not in set(t1_blocked)]
        if t1_blocked:
            logger.info(f"[T+1] 当日买入不可卖: {','.join(t1_blocked[:5])}{'...' if len(t1_blocked)>5 else ''}")
        # 【V34:持仓保护 - 盈利股不让调仓随意卖出,让止盈/保护性卖出自然退出】
        # 逻辑:如果持仓盈利≥5%且当日收阳线,即使不在目标池中也不因调仓卖出
        # 原因:调仓卖出会错过后续大涨(如龙头低吸盈利8%被调仓卖,次日冲高15%)
        # 保护性卖出(冲高回落/利润保护/止损/止盈)仍然正常触发
        # 【V35修复:已触发止损/冲高回落/利润保护的股不受保护,避免保护阻止止损】
        hold_protection_pct = self._risk_config.get('hold_protection_threshold', GLOBAL_RISK.get('hold_protection_threshold', 0.04))
        _mark_sold_codes = set(pos_mgr.sell_code_reasons.keys())  # 已有保护性卖出reason的股
        if hold_protection_pct > 0:
            protected_codes = []
            for code in list(sell_codes):
                if code in _mark_sold_codes:
                    continue  # V35:已有卖出reason(止损/冲高回落等)的股不受保护
                if code not in holdings or holdings.get(code, 0) <= 0:
                    continue
                cost = self._cost_basis.get(code, 0)
                p = prices.get(code, {})
                close_p = p.get('close', 0)
                open_p = p.get('open', close_p)
                if cost > 0 and close_p > 0:
                    profit_pct = (close_p / cost - 1)
                    is_yang_line = close_p >= open_p  # 收阳线
                    # V35:增加止损检查——即使盈利+阳线,如果low已跌破止损价,不应保护
                    should_still_protect = True
                    if enable_stop_loss:
                        code_sl, _ = self._get_sl_tp_for_code(code)
                        low_p = p.get('low', close_p)
                        if low_p <= cost * (1 - code_sl):
                            should_still_protect = False  # 盘中已触发止损,不保护
                    # 【V47修复:一字涨停不受保护(涨停开板风险大)】
                    is_yizi = (open_p == close_p == p.get('high', 0) == p.get('low', 0)) and open_p > 0
                    if profit_pct >= hold_protection_pct and is_yang_line and should_still_protect and not is_yizi:
                        protected_codes.append(code)
            # 【V49-P0-3修复:改用集合过滤替代循环内remove,避免O(n²)和跳过元素bug】
            _protected_set = set(protected_codes)
            sell_codes = [code for code in sell_codes if code not in _protected_set]
            if protected_codes:
                logger.debug('backtest', f"[持仓保护] 盈利+阳线,不调仓卖出: {','.join(protected_codes[:5])}")

        # 【P1-1修复:超过max_hold_days的持仓强制卖出,即使仍在目标池中】
        # 【P1-2修复(V15):改用交易日计算超时,替代日历天数*1.5】
        # 旧逻辑: 日历天数>max_hold*1.5 → 周中买入易误触发
        # 新逻辑: 统计all_trade_dates中的交易日数,精确不受周末/节假日影响
        global_max_hold = self._risk_config.get('max_hold_days', 999)
        over_hold_codes = []
        for code in list(holdings.keys()):
            if holdings.get(code, 0) > 0:
                buy_date_raw = self._cost_basis_date.get(code)
                max_hold_days = self._get_max_hold_for_code(code)  # 【V31:使用共享方法,消除重复逻辑】
                if buy_date_raw is not None and max_hold_days < 999:
                    try:
                        buy_dt_int = int(str(buy_date_raw))
                        trade_dt_int = int(str(trade_date))
                        trade_days_held = self._calc_trade_days_held(buy_dt_int, trade_dt_int)
                        if trade_days_held <= 0:
                            # fallback: 日历天数/1.5
                            bd = dt_now.strptime(str(buy_dt_int), '%Y%m%d')
                            td = dt_now.strptime(str(trade_dt_int), '%Y%m%d')
                            trade_days_held = int((td - bd).days / 1.5)
                        if trade_days_held >= max_hold_days and code not in sell_codes:
                            # 【V31修复:>=替代>,max_hold_days=3时第3天即触发超时】
                            over_hold_codes.append(code)
                    except (ValueError, TypeError):
                        pass
        sell_codes.extend(over_hold_codes)
        # 【Phase1-T+1】超时强卖也要递守T+1(正常不应出现:昨日买的今天不触超时)
        sell_codes = [c for c in sell_codes if self._cost_basis_date.get(c) != trade_date]
        # 【V54-Bug7修复:sell_codes去重改用dict.fromkeys保持插入顺序,避免set打乱卖出日志顺序】
        # 旧: list(set(sell_codes)) — set无序,每次运行卖出日志顺序不一致
        # 新: list(dict.fromkeys(sell_codes)) — 保持首次出现的顺序,日志稳定
        sell_codes = list(dict.fromkeys(sell_codes))
        # 【V29:超时强卖的股票当天不应被重新买入,由PositionManager管理target_shares】
        for code in over_hold_codes:
            pos_mgr.mark_sold(code, f'超时')
        # 【V29:止损/冲高回落/高开即卖/止盈的股票,也由PositionManager管理】
        # PositionManager.mark_sold()已自动从target_shares移除,不需额外的del循环
        # 【修复P1-6:减仓逻辑 - 持仓超过目标时卖出差额】
        # 【V33:使用pos_mgr.target_shares,与买入循环一致】
        reduce_codes = {code: holdings[code] - pos_mgr.target_shares[code] for code in holdings
                        if code in pos_mgr.target_shares and holdings.get(code, 0) > pos_mgr.target_shares[code]}
        # 【Phase1-T+1】当日买入的股票不可减仓(减仓=部分卖出)
        reduce_codes = {code: delta for code, delta in reduce_codes.items()
                        if self._cost_basis_date.get(code) != trade_date}
        # 【P1-4修复:减仓前检查止损止盈 - 已触发止损的减仓股改为全卖】
        enable_sl = self._risk_config.get('enable_stop_loss', True)
        enable_tp = self._risk_config.get('enable_take_profit', True)
        # 【P0-2修复:按策略查找策略级止损止盈参数,优先于全局参数】
        # 【P1-2修复(第十一轮):_get_sl_tp_for_code和_get_slippage_for_code已提升为实例方法】
        # 原局部函数定义已删除,直接调用 self.self._get_sl_tp_for_code(code) / self._get_slippage_for_code(code)

        codes_to_promote = []  # 从reduce_codes升级到sell_codes的股票
        codes_to_promote_reasons = {}  # code -> sell_reason(冲高回落/止损/止盈)
        for code in list(reduce_codes.keys()):
            p = prices.get(code, {})
            low_p = p.get('low', p.get('close', 0))
            high_p = p.get('high', p.get('close', 0))
            open_p = p.get('open', p.get('close', 0))
            _close_p = p.get('close', 0)
            cost = self._cost_basis.get(code, 0)
            if cost > 0 and p.get('close', 0) > 0:
                # 【P0-2修复(V17)】:减仓也要检查冲高回落/高开即卖/利润保护
                _strategies = self.stock_to_strategy.get(code, [])
                if isinstance(_strategies, str): _strategies = [_strategies]
                early_sell_price, early_sell_reason = self._check_early_sell_signals(
                    code, _strategies, cost, open_p, _close_p)
                if early_sell_price > 0:
                    codes_to_promote.append(code)
                    codes_to_promote_reasons[code] = early_sell_reason  # 记录具体reason
                else:
                    code_sl, code_tp = self._get_sl_tp_for_code(code)
                    if enable_sl and low_p <= cost * (1 - code_sl):
                        codes_to_promote.append(code)
                        # 【V33修复:记录止损具体reason(跳空止损/正常止损),避免卖出循环重复判断】
                        if open_p <= cost * (1 - code_sl):
                            codes_to_promote_reasons[code] = '跳空止损'
                        else:
                            codes_to_promote_reasons[code] = f'止损({code_sl*100:.0f}%)'
                    elif enable_tp and high_p >= cost * (1 + code_tp):
                        codes_to_promote.append(code)
                        codes_to_promote_reasons[code] = f'止盈({code_tp*100:.0f}%)'
        for code in codes_to_promote:
            sell_codes.append(code)
            # 【V33修复:promote的股票必须调用pos_mgr.mark_sold()记录reason】
            # 旧bug: 没有mark_sold→卖出循环走默认reason→重新判断可能得到不同结果
            _promote_reason = codes_to_promote_reasons.get(code, '调仓卖出')
            pos_mgr.mark_sold(code, _promote_reason)
            del reduce_codes[code]
        # 【修复P1-8:停牌股超时强卖 - close<=0的持仓连续持有>10交易日强制卖出(取最后有效价)】
        suspend_sell_codes = []
        for code in list(holdings.keys()):
            if holdings.get(code, 0) > 0 and code in prices:
                p = prices[code]
                if p.get('close', 0) <= 0:
                    # 【P0-1修复:从_cost_basis_date获取买入日期】
                    buy_date_raw = self._cost_basis_date.get(code)
                    if buy_date_raw is not None:
                        try:
                            # 【P2-3修复(V15):停牌超时也改用交易日计算,与P1-2超时强卖一致】
                            buy_dt_int = int(str(buy_date_raw))
                            trade_dt_int = int(str(trade_date))
                            trade_days_held = self._calc_trade_days_held(buy_dt_int, trade_dt_int)
                            if trade_days_held <= 0:
                                # fallback: 日历天数/1.5 ≈ 交易日
                                bd = dt_now.strptime(str(buy_dt_int), '%Y%m%d')
                                td = dt_now.strptime(str(trade_dt_int), '%Y%m%d')
                                trade_days_held = int((td - bd).days / 1.5)
                            # 【P2-2修复(V22):停牌超时阈值改用max(max_hold_days*3, 10),不再硬编码10天】
                            # 不同策略的max_hold_days不同(3/4天),固定10天对短持仓策略过长
                            # 【V31:使用共享方法_get_max_hold_for_code,消除重复逻辑】
                            _effective_mhd = self._get_max_hold_for_code(code)
                            _suspend_threshold = max(_effective_mhd * 3, 10)  # 最少10天缓冲
                            if trade_days_held > _suspend_threshold:
                                last_price = p.get('open', 0) or self._last_valid_price.get(code, 0)
                                if last_price > 0:
                                    suspend_sell_codes.append(code)
                        except (ValueError, TypeError):
                            pass

        # 【方案2:日频数据推算盘中卖出价】
        # 止损:盘中最低价触发 → 用low近似
        # 止盈:盘中最高价触发 → 用high近似
        # 其他:收盘卖出 → 用close
        # 【V49-P0-4修复:删除重复声明的enable_stop_loss/enable_take_profit(已在3850行声明)】
        # 旧bug: 4126行重复声明enable_stop_loss,与3850行同变量名但相隔276行,易混淆
        # enable_stop_loss/enable_take_profit 已在上方(V48d处)声明,此处无需重复
        # 【P0-2修复:默认全局参数,卖出循环中按code覆盖】
        global_sl = self._risk_config.get('stop_loss_pct', GLOBAL_RISK['stop_loss_pct'])
        global_tp = self._risk_config.get('take_profit_pct', 0.07)
        for ts_code in sell_codes:
            shares = holdings[ts_code]
            price_info = prices.get(ts_code, {})
            close_price = price_info.get('close', 0)
            high_price = price_info.get('high', close_price)
            low_price = price_info.get('low', close_price)
            open_price = price_info.get('open', close_price)
            if close_price <= 0 or shares <= 0:
                # 【修复P1-8:停牌股close=0时尝试用最后有效价卖出】
                if ts_code in suspend_sell_codes:
                    last_price = price_info.get('open', 0) or getattr(self, '_last_valid_price', {}).get(ts_code, 0)
                    if last_price > 0 and shares > 0:
                        # 停牌超时强卖,用最后有效价
                        sell_price = last_price
                        sell_reason = '停牌超时强卖'
                        price = sell_price
                        # 【P0-2修复(V25):停牌超时强卖不扣滑点(与止损/超时一致,被迫卖出)】
                        sell_price_adj = price
                        gross_amount = shares * sell_price_adj
                        commission = max(gross_amount * self.SELL_COMMISSION, self.MIN_COMMISSION)
                        stamp_tax = gross_amount * self.STAMP_TAX
                        net_amount = gross_amount - commission - stamp_tax
                        cash += net_amount
                        records.append(RebalanceRecord(
                            date=str(trade_date), action="sell", ts_code=ts_code,
                            shares=shares, price=price, amount=net_amount,
                            reason=sell_reason, sentiment=sentiment))
                        holdings.pop(ts_code, None)
                        if ts_code in self._cost_basis:
                            del self._cost_basis[ts_code]
                        if ts_code in self._cost_basis_date:
                            del self._cost_basis_date[ts_code]
                continue

            # 判断盘中是否触发止损/止盈(基于实际买入成本)
            cost_basis = self._cost_basis.get(ts_code, open_price)  # 用实际买入价
            sell_price = close_price  # 默认收盘价
            sell_reason = '调仓卖出'
            # 【V29:PositionManager记录的卖出原因优先使用,避免重复判断】
            if pos_mgr.should_sell(ts_code):
                _pre_determined_reason = pos_mgr.get_sell_reason(ts_code)
                # 【V29:统一卖出价映射,替代if/elif链】
                code_sl, code_tp = self._get_sl_tp_for_code(ts_code)
                sell_price, sell_reason = resolve_sell_price_and_reason(
                    _pre_determined_reason, cost_basis, open_price, close_price, code_sl, code_tp)
            elif cost_basis > 0:
                # 【P0-3修复(V16):冲高回落/高开即卖/利润保护reason统一为固定分类】
                # 旧: reason含价格细节如"冲高回落(开40.05涨9.7%)" → 前端统计每条独立
                # 新: reason固定分类"冲高回落"/"高开即卖"/"利润保护",价格细节存入record备注
                _strategies = self.stock_to_strategy.get(ts_code, [])
                if isinstance(_strategies, str): _strategies = [_strategies]
                early_sell_price, early_sell_reason = self._check_early_sell_signals(
                    ts_code, _strategies, cost_basis, open_price, close_price)
                early_sell_triggered = early_sell_price > 0
                if early_sell_triggered:
                    sell_price = early_sell_price
                    sell_reason = early_sell_reason
                if not early_sell_triggered:
                    # 【P0-2修复:按策略获取止损止盈参数】
                    code_sl, code_tp = self._get_sl_tp_for_code(ts_code)
                    stop_price = cost_basis * (1 - code_sl)
                    profit_price = cost_basis * (1 + code_tp)
                    if enable_stop_loss and low_price <= stop_price:
                        # 【Phase1-跳空止损】open直接跳空低于止损价,以open卖出(最差情况)
                        if open_price <= stop_price:
                            sell_price = open_price
                            sell_reason = f'跳空止损'
                        else:
                            sell_price = stop_price
                            sell_reason = f'止损({code_sl*100:.0f}%)'
                    elif enable_take_profit and high_price >= profit_price:
                        sell_price = profit_price
                        sell_reason = f'止盈({code_tp*100:.0f}%)'
            price = sell_price

            # 计算卖出金额
            # 【V29:统一滑点规则】
            slippage_pct = 0 if not should_apply_slippage(sell_reason) else self._get_slippage_for_code(ts_code)
            sell_price_adj = price * (1 - slippage_pct)
            gross_amount = shares * sell_price_adj
            commission = max(gross_amount * self.SELL_COMMISSION, self.MIN_COMMISSION)
            stamp_tax = gross_amount * self.STAMP_TAX
            net_amount = gross_amount - commission - stamp_tax

            # 更新现金
            cash += net_amount

            # 记录交易
            _sell_strategy = self._get_strategy_for_stock(ts_code)
            records.append(RebalanceRecord(
                date=str(trade_date),
                action="sell",
                ts_code=ts_code,
                shares=shares,
                price=price,  # 卖出用收盘价
                amount=net_amount,
                reason=sell_reason,
                strategy_name=_sell_strategy,
                sentiment=sentiment
            ))

            # 清空持仓并彻底删除key(不要保留shares=0的残留)
            # 旧bug: holdings[ts_code]=0 保留key → 后续遍历仍需检查shares>0
            # 清理买入成本记录
            del holdings[ts_code]
            if ts_code in self._cost_basis:
                del self._cost_basis[ts_code]
            if ts_code in self._cost_basis_date:
                del self._cost_basis_date[ts_code]

        # 再买入:目标持仓中需要增加的股票
        # 【V33关键修复:使用pos_mgr.target_shares而非局部target_shares】
        # pos_mgr.mark_sold()会从pos_mgr.target_shares删除冲高回落/止损/止盈的股
        # 如果遍历局部target_shares,这些股会被重新买入→震荡bug
        for ts_code, target_count in pos_mgr.target_shares.items():
            current_shares = holdings.get(ts_code, 0)
            delta = target_count - current_shares
            reduce_reason = None  # 【P1-5修复:每次循环重置,避免泄漏到后续股票】

            if delta <= 0:
                continue  # 不需要买入

            # 【方案2:日频数据推算盘中触发价】
            # 不同策略的买入时机不同,用日频OHLC推算合理买入价
            price_info = prices.get(ts_code, {})
            open_price = price_info.get('open', 0)
            high_price = price_info.get('high', open_price)
            low_price = price_info.get('low', open_price)
            close_price = price_info.get('close', 0)
            strategy_name = self._get_strategy_for_stock(ts_code)
            price = self._get_buy_price_for_stock(ts_code, open_price, close_price, high_price, low_price, price_info.get('pre_close', 0))
            if price <= 0:
                price = open_price
            if price <= 0:
                continue

            # 计算买入成本(含滑点扣除)
            slippage_pct = self._get_slippage_for_code(ts_code)
            buy_price_adj = price * (1 + slippage_pct)
            gross_amount = delta * buy_price_adj
            commission = max(gross_amount * self.BUY_COMMISSION, self.MIN_COMMISSION)
            total_cost = gross_amount + commission

            if cash < total_cost:
                # 现金不足,按比例缩减
                original_delta = delta
                ratio = cash / total_cost
                delta = int(int(delta * ratio) / 100) * 100
                if delta <= 0:
                    continue
                # 【修复新7:现金缩减买入信息附加到reason字段,后续日志显示】
                reduce_reason = f"现金不足缩减{ratio*100:.1f}%"
                gross_amount = delta * buy_price_adj
                commission = max(gross_amount * self.BUY_COMMISSION, self.MIN_COMMISSION)
                total_cost = gross_amount + commission

            # 更新现金
            cash -= total_cost

            # 更新持仓
            holdings[ts_code] = current_shares + delta
            # 【P0-1修复(V12):cost_basis应记录含滑点的实际成交价buy_price_adj】
            # 旧bug: 记录的是模拟价price(如半路追涨open*1.021),不含滑点
            # 导致止损/止盈基于不含滑点的价格计算,触发阈值偏差
            # 修复: 使用buy_price_adj(price*(1+slippage_pct))作为实际成本
            if not self._cost_basis:
                self._cost_basis = {}
            if not self._cost_basis_date:
                self._cost_basis_date = {}
            if current_shares > 0 and ts_code in self._cost_basis:
                # 增仓:加权平均成本 = (旧成本*旧股数 + 新实际成本*新股数) / 总股数
                old_cost = self._cost_basis[ts_code]
                total_shares = current_shares + delta
                self._cost_basis[ts_code] = (old_cost * current_shares + buy_price_adj * delta) / total_shares
                # 【Bug修复:增仓时不更新买入日期,保留首次买入日期用于超时判断】
            else:
                self._cost_basis[ts_code] = buy_price_adj  # 【P0-1修复】新买入:记录含滑点的实际成交价
                self._cost_basis_date[ts_code] = trade_date  # 仅新买入时记录首次买入日期

            # 记录交易
            strategy_name = self._get_strategy_for_stock(ts_code)  # 【P1-1修复:支持多策略列表】
            # 【修复新7:如果有现金缩减信息附加到reason】
            final_reason = "rebalance"
            if reduce_reason:
                final_reason = f"rebalance ({reduce_reason})"
            records.append(RebalanceRecord(
                date=str(trade_date),
                action="buy",
                ts_code=ts_code,
                shares=delta,
                price=price,
                amount=-total_cost,
                reason=final_reason,
                strategy_name=strategy_name,  # 【修复新6:存独立字段】
                sentiment=sentiment
            ))

        # 【修复P1-6:减仓逻辑 - 卖出超过目标的部分】
        for ts_code, reduce_shares in reduce_codes.items():
            if reduce_shares <= 0:
                continue
            shares = holdings.get(ts_code, 0)
            if shares < reduce_shares:
                reduce_shares = shares
            price_info = prices.get(ts_code, {})
            close_price = price_info.get('close', 0)
            if close_price <= 0:
                continue  # 停牌股不处理减仓
            # 减仓用收盘价(不做止损止盈判断,减仓是调仓行为)
            sell_price = close_price
            sell_reason = '减仓'
            slippage_pct = self._get_slippage_for_code(ts_code)
            sell_price_adj = sell_price * (1 - slippage_pct)
            gross_amount = reduce_shares * sell_price_adj
            commission = max(gross_amount * self.SELL_COMMISSION, self.MIN_COMMISSION)
            stamp_tax = gross_amount * self.STAMP_TAX
            net_amount = gross_amount - commission - stamp_tax
            cash += net_amount
            new_shares = shares - reduce_shares
            records.append(RebalanceRecord(
                date=str(trade_date), action="sell", ts_code=ts_code,
                shares=reduce_shares, price=sell_price, amount=net_amount,
                reason=sell_reason, sentiment=sentiment))
            if new_shares > 0:
                holdings[ts_code] = new_shares
            else:
                holdings.pop(ts_code, None)
                if ts_code in self._cost_basis:
                    del self._cost_basis[ts_code]
                if ts_code in self._cost_basis_date:
                    del self._cost_basis_date[ts_code]

        # 清理零持仓
        holdings = {code: shares for code, shares in holdings.items() if shares > 0}

        return cash, holdings, records

    async def _get_stock_names(self, ts_codes: list[str]):
        """批量获取股票名称,使用缓存减少查询"""
        result = {}
        need_query = []

        # 【P2-3修复(V21):用共享方法_standardize_ts_code替代局部_standardize_code】
        for ts_code in ts_codes:
            standard_code = self._standardize_ts_code(ts_code)

            if standard_code in self._stock_name_cache:
                result[ts_code] = self._stock_name_cache[standard_code]
            else:
                need_query.append(standard_code)

        # 查询缓存未命中的(已经标准化)
        if len(need_query) > 0:
            docs = await mongo_manager.find_many(
                C.STOCK_BASIC,
                {"ts_code": {"$in": need_query}},
                {"ts_code": 1, "name": 1}
            )

            for doc in docs:
                standard_code = doc["ts_code"]
                name = doc.get("name", standard_code)
                self._stock_name_cache[standard_code] = name

        # 构建结果,返回给调用方使用原始 ts_code 作为 key
        for ts_code in ts_codes:
            standard_code = self._standardize_ts_code(ts_code)

            if standard_code in self._stock_name_cache:
                result[ts_code] = self._stock_name_cache[standard_code]
            else:
                # 找不到,回退到使用原始代码去掉后缀作为名称
                if '.' in ts_code:
                    result[ts_code] = ts_code.split('.')[0]
                else:
                    result[ts_code] = ts_code

        return result
