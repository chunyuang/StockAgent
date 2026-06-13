"""
StrategyScorer — 策略筛选引擎

从MarketScanner拆分出来(Phase3.1)。
负责:
- 日级因子+实时数据合并
- 策略有效配置获取(ParamCenter > 前端覆盖 > strategy_defaults)
- 策略风控参数获取
- 策略筛选条件应用(复用回测逻辑)
"""

import logging
from datetime import datetime
from typing import Dict, List, Any, Optional

import pandas as pd

from nodes.market_monitor.scanner import ScanSignal

logger = logging.getLogger("strategy_scorer")


class StrategyScorer:
    """
    策略筛选引擎
    
    用法:
        scorer = StrategyScorer(scanner)  # scanner引用(读取配置)
        merged_df = scorer.merge_factors(realtime_data)
        signals = await scorer.apply_strategies(merged_df, trade_date)
    """
    
    def __init__(self, scanner):
        """
        Args:
            scanner: MarketScanner实例(读取配置/持仓)
        """
        self._scanner = scanner
        self._name_map: Dict[str, str] = {}  # ts_code→stock_name
    
    # ==================== 属性代理 ====================
    
    @property
    def broker(self) -> Any:
        return self._scanner._broker
    
    @property
    def config(self) -> Dict:
        return self._scanner.config
    
    @property
    def daily_factors_df(self) -> pd.DataFrame:
        return self._scanner._daily_factors_df
    
    @property
    def param_center(self) -> Any:
        return self._scanner._param_center
    
    # ==================== 因子合并 ====================
    
    def merge_factors(self, realtime_data: Dict[str, Dict]) -> pd.DataFrame:
        """合并日级因子+实时数据(编排方法)"""
        if not realtime_data:
            return pd.DataFrame()

        rt_df = self._realtime_to_dataframe(realtime_data)
        return self._merge_with_daily_factors(rt_df)

    def _realtime_to_dataframe(self, realtime_data: Dict[str, Dict]) -> pd.DataFrame:
        """实时数据→DataFrame"""
        rt_rows = []
        for ts_code, rt in realtime_data.items():
            row = {"ts_code": ts_code}
            row["pct_chg"] = rt.get("pct_chg", 0)
            row["volume_ratio"] = rt.get("volume_ratio", 0)
            row["turnover_rate"] = rt.get("turnover_rate", 0)
            row["circ_mv"] = rt.get("circ_mv", 0)
            row["open"] = rt.get("open", 0)
            row["high"] = rt.get("high", 0)
            row["low"] = rt.get("low", 0)
            row["close"] = rt.get("price", 0)
            row["pre_close"] = rt.get("pre_close", 0)
            row["stock_name"] = rt.get("name", "") or self._name_map.get(ts_code, "")

            pct = rt.get("pct_chg") or 0
            row["is_limit_up"], row["is_limit_down"] = self._classify_limit(ts_code, pct)
            row["limit_up_count"] = row["is_limit_up"]
            rt_rows.append(row)
        return pd.DataFrame(rt_rows)

    @staticmethod
    def _classify_limit(ts_code: str, pct: float) -> tuple:
        """根据涨跌幅和板块判断涨停/跌停"""
        if ts_code.startswith('688'):
            return (1 if pct >= 19.5 else 0, 1 if pct <= -19.5 else 0)
        elif ts_code.startswith(('4', '8')):
            return (1 if pct >= 29.5 else 0, 1 if pct <= -29.5 else 0)
        return (1 if pct >= 9.5 else 0, 1 if pct <= -9.5 else 0)

    def _merge_with_daily_factors(self, rt_df: pd.DataFrame) -> pd.DataFrame:
        """合并日级因子"""
        daily_df = self.daily_factors_df
        if daily_df is not None and not daily_df.empty:
            daily_cols = ["ts_code", "ma5", "macd", "rsi_6", "boll_upper", "atr",
                          "limit_up_count", "limit_up_yesterday", "limit_down_yesterday",
                          "first_limit_up", "fear_greed_index"]
            available_cols = [c for c in daily_cols if c in daily_df.columns]
            if available_cols:
                daily_sub = daily_df[available_cols].copy()
                merged = rt_df.merge(daily_sub, on="ts_code", how="left", suffixes=("", "_daily"))
                for col in ["ma5", "macd", "rsi_6", "boll_upper", "atr", "limit_up_count",
                            "limit_up_yesterday", "limit_down_yesterday", "first_limit_up"]:
                    if col in merged.columns:
                        merged[col] = merged[col].fillna(0)
                return merged
        return rt_df
    
    # ==================== 策略配置 ====================
    
    def get_effective_strategy_config(self, strategy_key: str) -> Dict:
        """获取策略有效配置(ParamCenter > 前端覆盖 > strategy_defaults)"""
        # 优先级1: ParamCenter(MongoDB, 支持热更新)
        if self.param_center and self.param_center._initialized:
            pc_params = self.param_center._cache.get(strategy_key)
            if pc_params:
                return pc_params
        
        # 优先级2: strategy_defaults + 前端覆盖
        from nodes.backtest_engine.strategy_defaults import STRATEGY_CONFIGS
        base = dict(STRATEGY_CONFIGS.get(strategy_key, {}))
        overrides = self.config.get("strategy_overrides", {}).get(strategy_key)
        if overrides:
            if "params" in overrides:
                base["params"] = {**base.get("params", {}), **overrides["params"]}
            if "riskParams" in overrides:
                base["riskParams"] = {**base.get("riskParams", {}), **overrides["riskParams"]}
            if "enabled" in overrides:
                base["enabled"] = overrides["enabled"]
        return base
    
    def get_strategy_risk(self, strategy_key: str) -> Dict:
        """获取策略风控参数(小数形式: 0.03=3%)
        
        【v2.9.92x】同时合并params中卖出相关的参数(与回测对齐)
        旧bug: next_day_open_sell_pct/pullback_*等在params里但只合并riskParams，
        导致实盘用3%默认值而回测是2%
        """
        from nodes.backtest_engine.strategy_defaults import GLOBAL_RISK
        cfg = self.get_effective_strategy_config(strategy_key)
        risk = dict(GLOBAL_RISK)
        risk.update(cfg.get("riskParams", {}))
        # 【v2.9.92x】合并params中的卖出相关参数(与回测STRATEGY_PULLBACK_PARAMS对齐)
        params = cfg.get("params", {})
        sell_param_keys = [
            "next_day_open_sell_pct",
            "pullback_profit_lock_threshold",
            "pullback_mid_fallback_pct",
            "pullback_high_threshold",
            "allow_after_10am",
        ]
        for k in sell_param_keys:
            if k in params and k not in risk:
                risk[k] = params[k]
        # 防御: 百分比形式(>1)自动转小数
        for pct_key in ["stop_loss_pct", "take_profit_pct", "next_day_open_sell_pct",
                       "pullback_profit_lock_threshold", "pullback_mid_fallback_pct",
                       "pullback_high_threshold"]:
            if risk.get(pct_key, 0) > 1:
                risk[pct_key] = risk[pct_key] / 100
        return risk
    
    # ==================== 策略筛选 ====================
    

    def update_name_map(self, name_map: Dict[str, str]) -> None:
        """更新股票名称映射(从scanner传入)"""
        self._name_map = name_map
    async def apply_strategies(self, merged_df: pd.DataFrame, trade_date: str) -> List[ScanSignal]:
        """策略筛选(编排方法: 复用回测逻辑, 读取前端覆盖参数)"""
        if merged_df is None or len(merged_df) == 0:
            return []

        from nodes.backtest_engine.strategy_defaults import STRATEGY_CONFIGS
        from nodes.backtest_engine.factor_selection.portfolio_backtest import PortfolioBacktester

        bt = PortfolioBacktester()
        signals = []
        existing_positions = (
            {p.ts_code for p in self.broker.get_positions()} if self.broker else set()
        )

        for strategy_key in STRATEGY_CONFIGS:
            cfg = self.get_effective_strategy_config(strategy_key)
            if not cfg.get("enabled", True):
                continue

            strategy_name = cfg.get("name", strategy_key)
            params = cfg.get("params", {})
            conditions = bt._build_strategy_filter_conditions(strategy_name, params)
            mask = self._apply_filter_conditions(merged_df, conditions)
            selected = merged_df[mask]

            for _, row in selected.iterrows():
                ts_code = row.get("ts_code", "")
                if ts_code in existing_positions:
                    continue
                signals.append(self._build_signal_from_row(
                    row, strategy_key, strategy_name, len(conditions), len(merged_df), len(selected),
                ))

        return signals

    def _apply_filter_conditions(
        self, merged_df: pd.DataFrame, conditions: list,
    ) -> pd.Series:
        """将回测筛选条件应用到merged_df, 返回bool mask"""
        mask = pd.Series(True, index=merged_df.index)
        for cond in conditions:
            col = cond.get("name") or cond.get("column")
            op = cond.get("operator", ">=")
            val = cond.get("target") or cond.get("value")
            if col and val is not None and col in merged_df.columns:
                try:
                    col_data = merged_df[col].fillna(0)
                    if op == ">=":   mask &= (col_data >= val)
                    elif op == "<=": mask &= (col_data <= val)
                    elif op == ">":  mask &= (col_data > val)
                    elif op == "<":  mask &= (col_data < val)
                    elif op == "==": mask &= (col_data == val)
                except TypeError:
                    pass
        return mask

    def _build_signal_from_row(
        self, row, strategy_key: str, strategy_name: str,
        conditions_count: int, candidates_before: int, candidates_after: int,
    ) -> ScanSignal:
        """从DataFrame行构建ScanSignal对象"""
        ts_code = row.get("ts_code", "")
        pct = float(row.get('pct_chg') or 0)
        vr = float(row.get('volume_ratio') or 0)
        tr = float(row.get('turnover_rate') or 0)
        lbc = int(row.get('limit_up_count', 0))

        if strategy_key == 'halfway_chase':
            reason = f"涨{pct:.1f}% 量比{vr:.1f} 换手{tr:.1f}%{' ⚠️ST' if 'ST' in row.get('stock_name','') else ''}"
        elif strategy_key == 'first_limit_up':
            reason = f"首板涨停 封单强 炸板{lbc}次"
        elif strategy_key == 'dragon_head':
            reason = f"{lbc}连板龙头 回调{pct:.1f}%"
        elif strategy_key == 'limit_down_qiao':
            reason = f"跌停撬板 反弹{pct:.1f}%"
        else:
            reason = f"{strategy_name} 涨{pct:.1f}%"

        return ScanSignal(
            ts_code=ts_code,
            stock_name=row.get("stock_name", "") or self._name_map.get(ts_code, ""),
            strategy=strategy_key,
            strategy_name=strategy_name,
            price=row.get("close", 0) or row.get("price", 0),
            pct_chg=pct,
            volume_ratio=vr,
            turnover_rate=tr,
            is_limit_up=bool(row.get("is_limit_up", 0)),
            limit_up_count=lbc,
            reason=reason,
            scan_time=datetime.now().strftime("%H:%M:%S"),
            factors={k: row.get(k, 0) for k in
                     ["pct_chg", "volume_ratio", "turnover_rate", "circ_mv",
                      "ma5", "rsi_6", "is_limit_up", "limit_up_count"]
                     if k in row.index},
            layer_trace={
                "L6_strategy": {
                    "strategy": strategy_key,
                    "strategy_name": strategy_name,
                    "conditions_applied": conditions_count,
                    "candidates_before": candidates_before,
                    "candidates_after": candidates_after,
                    "passed": True,
                }
            },
        )

    # ==================== 盘中异动检测 ====================

    def detect_anomalies(self, realtime_data: Dict[str, Dict],
                          active_signals: List[ScanSignal],
                          prev_cache: Dict[str, Dict]) -> List[ScanSignal]:
        """盘中异动检测(编排方法)

        检测类型: 急速拉升/跌停打开/量比突变/封板松动
        不消耗额外必盈额度, 从已有的realtime_data里检测
        """
        signals = []
        active_keys = {s.ts_code + "|" + s.strategy for s in active_signals}

        for ts_code, rt in realtime_data.items():
            key = ts_code + "|anomaly"
            if key in active_keys:
                continue
            signal = self._check_single_anomaly(ts_code, rt, prev_cache)
            if signal:
                signals.append(signal)

        if signals:
            logger.info(f"[ANOMALY] 异动检测: {len(signals)}只")
        return signals

    def _check_broken_board(
        self, ts_code: str, name: str, price: float,
        pct_chg: float, turnover: float, is_broken: bool,
        is_limit_down: bool, open_times: int,
    ) -> Optional[ScanSignal]:
        """跌停撬板(炸板股)检测【v2.9.62提取】"""
        if is_broken and not is_limit_down and pct_chg > 5 and open_times <= 2:
            return ScanSignal(
                ts_code=ts_code, stock_name=name,
                strategy="anomaly_broken", strategy_name="涨停炸板",
                signal_type="buy", price=price,
                pct_chg=pct_chg, volume_ratio=0,
                turnover_rate=turnover, is_limit_up=False,
                reason=f"涨停炸板2次内 涨{pct_chg:.1f}%",
            )
        return None

    def _check_strong_limit(
        self, ts_code: str, name: str, price: float,
        pct_chg: float, turnover: float, is_limit_up: bool,
        fd_amount: float, open_times: int, limit_times: int,
    ) -> Optional[ScanSignal]:
        """强势涨停(大封单+无炸板)检测【v2.9.62提取】"""
        if is_limit_up and fd_amount > 100000 and open_times == 0:
            return ScanSignal(
                ts_code=ts_code, stock_name=name,
                strategy="anomaly_strong", strategy_name="强势涨停",
                signal_type="buy", price=price,
                pct_chg=pct_chg, volume_ratio=0,
                turnover_rate=turnover, is_limit_up=True,
                reason=f"连板{limit_times} 封单{fd_amount/1000:.0f}万 无炸板",
            )
        return None

    def _check_surge(
        self, ts_code: str, name: str, price: float,
        pct_chg: float, turnover: float, is_limit_up: bool,
        prev_price: float,
    ) -> Optional[ScanSignal]:
        """急速拉升(5分钟内涨幅>3%)检测【v2.9.62提取】"""
        if prev_price > 0 and price > 0:
            price_change_pct = (price - prev_price) / prev_price * 100
            if price_change_pct > 3 and not is_limit_up:
                return ScanSignal(
                    ts_code=ts_code, stock_name=name,
                    strategy="anomaly_surge", strategy_name="急速拉升",
                    signal_type="buy", price=price,
                    pct_chg=pct_chg, volume_ratio=0,
                    turnover_rate=turnover, is_limit_up=False,
                    reason=f"5分钟涨{price_change_pct:.1f}%",
                )
        return None

    def _check_single_anomaly(
        self, ts_code: str, rt: Dict, prev_cache: Dict[str, Dict],
    ) -> Optional[ScanSignal]:
        """单只股票异动检测, 返回信号或None【v2.9.62重构: 3种异动提取子方法】"""
        pct_chg = rt.get("pct_chg", 0)
        is_limit_up = rt.get("is_limit_up", False)
        is_limit_down = rt.get("is_limit_down", False)
        is_broken = rt.get("is_broken_board", False)
        open_times = rt.get("open_times", 0)
        limit_times = rt.get("limit_times", 0)
        name = rt.get("name", "") or self._name_map.get(ts_code, "")
        price = rt.get("price", 0)
        turnover = rt.get("turnover_rate", 0)
        fd_amount = rt.get("fd_amount", 0)

        # 1. 跌停撬板(炸板股)
        sig = self._check_broken_board(
            ts_code, name, price, pct_chg, turnover,
            is_broken, is_limit_down, open_times,
        )
        if sig:
            return sig

        # 2. 强势涨停(大封单+无炸板)
        sig = self._check_strong_limit(
            ts_code, name, price, pct_chg, turnover,
            is_limit_up, fd_amount, open_times, limit_times,
        )
        if sig:
            return sig

        # 3. 急速拉升(5分钟内涨幅>3%)
        prev_price = prev_cache.get(ts_code, {}).get("price", 0)
        return self._check_surge(
            ts_code, name, price, pct_chg, turnover,
            is_limit_up, prev_price,
        )
