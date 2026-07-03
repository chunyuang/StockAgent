#!/usr/bin/env python3
"""
实盘持仓管理模块
功能：记录持仓、自动检查止损止盈、持仓超期提醒、强制平仓提醒
"""
import sys
import logging

logger = logging.getLogger(__name__)
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'AgentServer'))  # FIXME: 使用sys.path.insert做模块查找是反模式，应改用setup.py/pyproject.toml将项目安装到venv中
sys.path.insert(0, os.path.dirname(__file__))

import json
import asyncio
import tempfile
from datetime import datetime
from typing import List, Dict
from dataclasses import dataclass, asdict
from nodes.backtest_engine.strategy_defaults import GLOBAL_RISK, STRATEGY_CONFIGS, STRATEGY_NAME_TO_ID

# V63: 引入卖出信号检查器(与回测共享),与live/position_manager.py对齐
from nodes.backtest_engine.factor_selection.sell_signal_checker import SellSignalChecker

@dataclass
class Position:
    """持仓信息数据模型
    
    记录单只股票的完整持仓信息，包括买入信息、风控参数和策略标签。
    提供持仓天数计算、止损止盈触发检查等业务方法。
    
    Attributes:
        ts_code: 股票代码（如 000001.SZ）
        name: 股票名称
        buy_date: 买入日期（YYYYMMDD格式）
        buy_price: 买入成交价（元）
        shares: 持股数量（股）
        total_cost: 总成本（元），= 买入价 × 数量
        stop_loss_price: 止损价（元），跌破此价触发止损卖出
        take_profit_price: 止盈价（元），涨到此价触发止盈卖出
        max_hold_days: 最大持仓天数，超期强制卖出，默认3天
        strategy: 策略标签，用于绩效归因分析
        notes: 备注信息
    """
    ts_code: str
    name: str
    buy_date: str  # YYYYMMDD
    buy_price: float
    shares: int
    total_cost: float
    stop_loss_price: float
    take_profit_price: float
    max_hold_days: int = 3
    strategy: str = "未知"
    notes: str = ""
    
    # 【V63-P1-6:预加载交易日历缓存,避免每次hold_days()都查MongoDB】
    _trade_dates_cache = None  # sorted list of int trade_dates
    _trade_dates_loaded = False
    
    @classmethod
    def _ensure_trade_dates_cache(cls):
        """加载交易日历到内存缓存(首次调用时加载,之后复用)"""
        if cls._trade_dates_loaded:
            return
        cls._trade_dates_loaded = True
        try:
            import asyncio
            from core.managers import mongo_manager
            async def _load():
                await mongo_manager.initialize()
                dates = await mongo_manager.distinct(
                    "stock_daily_ak_full", "trade_date", {})
                return sorted(dates)
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # 在async上下文中无法run_until_complete,降级
                    logger.debug("hold_days: async loop running, skip cache load")
                    return
                dates = loop.run_until_complete(_load())
                cls._trade_dates_cache = dates
                logger.info(f"✅ 交易日历缓存已加载: {len(dates)}个交易日")
            except RuntimeError:
                pass
        except Exception as e:
            logger.debug(f"交易日历缓存加载失败: {e}")
    
    def hold_days(self, current_date: str = None) -> int:
        """计算持仓天数（交易日）
        
        【V63-P1-6:优先使用内存缓存的交易日历,降级为自然日/1.5近似】
        自然日计算会导致:周五买入→周一hold_days=3(自然日)→误触发超时(实际仅1个交易日)
        
        Args:
            current_date: 计算基准日期（YYYYMMDD），默认取当天
        
        Returns:
            int: 持仓交易日天数
        """
        if not current_date:
            current_date = datetime.now().strftime("%Y%m%d")
        
        # 【V63-P1-6:使用内存缓存的交易日历,O(1)查找而非MongoDB查询】
        self._ensure_trade_dates_cache()
        if self._trade_dates_cache is not None:
            buy_int = int(self.buy_date)
            current_int = int(current_date)
            # 二分查找区间内的交易日数
            import bisect
            left = bisect.bisect_left(self._trade_dates_cache, buy_int)
            right = bisect.bisect_right(self._trade_dates_cache, current_int)
            # 买入日算第0天,所以交易日数-1
            return max(0, right - left - 1)
        
        # 降级:自然日/1.5近似
        try:
            buy_dt = datetime.strptime(self.buy_date, "%Y%m%d")
            current_dt = datetime.strptime(current_date, "%Y%m%d")
            return max(0, int((current_dt - buy_dt).days / 1.5))
        except (ValueError, TypeError):
            return 0
    
    def should_force_close(self, current_date: str = None) -> bool:
        """是否应该强制平仓（持仓超期）
        
        超短策略核心风控：持仓超过 max_hold_days 天必须卖出，
        防止短线变中线、中线变长线的问题。
        
        Args:
            current_date: 计算基准日期（YYYYMMDD），默认取当天
        
        Returns:
            bool: True表示持仓超期，应强制平仓
        """
        return self.hold_days(current_date) >= self.max_hold_days
    
    def check_stop_loss(self, current_price: float) -> bool:
        """检查是否触发止损
        
        Args:
            current_price: 当前价格（元）
        
        Returns:
            bool: True表示当前价格已跌破止损价
        """
        return current_price <= self.stop_loss_price
    
    def check_take_profit(self, current_price: float) -> bool:
        """检查是否触发止盈
        
        Args:
            current_price: 当前价格（元）
        
        Returns:
            bool: True表示当前价格已达到止盈价
        """
        return current_price >= self.take_profit_price
    
    def current_profit_pct(self, current_price: float) -> float:
        """计算当前收益率
        
        Args:
            current_price: 当前价格（元）
        
        Returns:
            float: 收益率（%），正数盈利，负数亏损
        """
        return (current_price - self.buy_price) / self.buy_price * 100 if self.buy_price and self.buy_price > 0 else 0.0

class PositionManager:
    """持仓管理器
    
    管理单个账户的所有持仓，提供：
    - 持仓的增删查（add/close/get）
    - 信号驱动建仓（add_position_by_signal）
    - 每日风控检查（daily_check）：止损/止盈/超期自动告警
    - 交易历史记录和绩效统计
    
    数据持久化到JSON文件：positions.json + trade_history.json
    """
    
    def __init__(self, data_file: str = "positions.json"):
        self.data_file = os.path.join(os.path.dirname(__file__), data_file)
        self.positions: Dict[str, Position] = {}  # ts_code -> Position
        self._load_positions()
    
    def _load_positions(self):
        """加载持仓数据"""
        if os.path.exists(self.data_file):
            try:
                with open(self.data_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, dict):
                    logger.error(f"⚠️  持仓数据格式异常（期望dict，实际{type(data).__name__}），初始化空持仓")
                    self.positions = {}
                    return
                for ts_code, pos_data in data.items():
                    try:
                        self.positions[ts_code] = Position(**pos_data)
                    except (TypeError, KeyError) as e:
                        logger.error(f"⚠️  跳过异常持仓记录 {ts_code}: {e}")
                logger.info(f"✅ 加载持仓数据成功，共{len(self.positions)}只持仓")
            except (json.JSONDecodeError, OSError) as e:
                logger.error(f"❌ 加载持仓数据失败: {e}")
                self.positions = {}
        else:
            logger.info("ℹ️  无历史持仓数据，初始化空持仓")
    
    def _save_positions(self):
        """保存持仓数据（原子写入：先写临时文件再rename，防崩溃损坏）"""
        try:
            data = {ts_code: asdict(pos) for ts_code, pos in self.positions.items()}
            # 【V67-P1:原子写入保护】先写临时文件再rename,避免进程崩溃导致数据损坏
            dir_name = os.path.dirname(self.data_file)
            fd, tmp_path = tempfile.mkstemp(suffix='.tmp', dir=dir_name)
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                os.replace(tmp_path, self.data_file)  # 原子rename
            except Exception:
                os.unlink(tmp_path) if os.path.exists(tmp_path) else None
                raise
            logger.info("✅ 持仓数据已保存")
        except (OSError, TypeError) as e:
            logger.error(f"❌ 保存持仓数据失败: {e}")
    
    def add_position(self, position: Position) -> bool:
        """添加新持仓
        
        Args:
            position: Position对象，包含完整的持仓信息
        
        Returns:
            bool: True添加成功，False表示该股票已在持仓中（不允许重复建仓）
        """
        if position.ts_code in self.positions:
            logger.warning(f"⚠️  {position.ts_code} 已在持仓中，是否需要加仓？")
            return False
        
        self.positions[position.ts_code] = position
        self._save_positions()
        logger.info(f"✅ 添加持仓：{position.name}({position.ts_code})，{position.shares}股，成本{position.buy_price:.2f}元")
        return True
    
    def add_position_by_signal(self, signal: Dict, buy_price: float = None, shares: int = None) -> bool:
        """通过选股信号创建持仓
        
        便捷方法：根据信号数据自动计算买入价、数量、止损止盈价。
        - 默认买入价 = 收盘价 × 1.01（应对高开）
        - 默认买入金额 = 1万元（100股整数倍）
        - 默认止损 = 买入价 × (1 - 策略止损百分比)
        - 默认止盈 = 买入价 × (1 + 策略止盈百分比)
        
        Args:
            signal: 选股信号字典，需包含 ts_code/name/close/date 等字段
            buy_price: 自定义买入价，None则使用默认计算
            shares: 自定义买入数量，None则使用默认计算
        
        Returns:
            bool: True建仓成功
        """
        if not buy_price:
            # 默认买入价为收盘价上浮1%
            close_price = signal.get("close") or 0
            if not close_price or not isinstance(close_price, (int, float)):
                logger.warning(f"⚠️ signal close价格异常({signal.get('close')}), 跳过建仓")
                return False
            buy_price = close_price * 1.01
        if not shares:
            # 默认买100股的整数倍，1万元
            shares = int(10000 / buy_price / 100) * 100
            if shares <= 0:
                shares = 100
        
        total_cost = buy_price * shares
        # 【V40修复:止损止盈从strategy_defaults策略维度读取，与回测保持一致】
        # 【V35修复:signal中strategy字段是中文名(如"龙头低吸"),但STRATEGY_CONFIGS的key是英文ID(如"dragon_head")】
        # 需要通过中文名→英文ID反向映射来正确查找策略参数
        from nodes.backtest_engine.strategy_defaults import STRATEGY_CONFIGS, GLOBAL_RISK, STRATEGY_NAME_TO_ID
        strategy_name = signal.get("strategy", "")  # 中文名如"龙头低吸"
        # 【V60:使用strategy_defaults统一映射,不再重复构建】
        strategy_id = STRATEGY_NAME_TO_ID.get(strategy_name, "")  # "龙头低吸" → "dragon_head"
        if not strategy_id:
            logger.warning(f"⚠️ 策略名\"{strategy_name}\"未在STRATEGY_CONFIGS中找到,使用全局默认风控参数")
        strategy_config = STRATEGY_CONFIGS.get(strategy_id, {})
        strategy_risk = strategy_config.get("riskParams", {})
        sl_pct = strategy_risk.get("stop_loss_pct", GLOBAL_RISK["stop_loss_pct"])  # 默认3%
        tp_pct = strategy_risk.get("take_profit_pct", GLOBAL_RISK["take_profit_pct"])  # 默认7%
        max_hold = strategy_risk.get("max_hold_days", GLOBAL_RISK["max_hold_days"])  # 默认3天
        
        stop_loss_price = buy_price * (1 - sl_pct)
        take_profit_price = buy_price * (1 + tp_pct)
        
        position = Position(
            ts_code=signal["ts_code"],
            name=signal["name"],
            buy_date=datetime.now().strftime("%Y%m%d"),
            buy_price=buy_price,
            shares=shares,
            total_cost=total_cost,
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
            max_hold_days=max_hold,
            strategy=signal.get("strategy", "未知"),
            notes=f"信号日期：{signal.get('date', datetime.now().strftime('%Y%m%d'))}"
        )
        
        return self.add_position(position)
    
    def close_position(self, ts_code: str, sell_price: float, sell_date: str = None, reason: str = "手动平仓") -> Dict:
        """平仓指定股票
        
        执行平仓流程：计算盈亏 → 记录交易历史 → 删除持仓 → 持久化
        
        Args:
            ts_code: 要平仓的股票代码
            sell_price: 卖出成交价（元）
            sell_date: 卖出日期（YYYYMMDD），默认当天
            reason: 平仓原因，用于交易历史记录
        
        Returns:
            Dict: 交易记录字典，包含盈亏详情；股票不在持仓中时返回空dict
        """
        if ts_code not in self.positions:
            logger.warning(f"⚠️  {ts_code} 不在持仓中")
            return {}
        
        pos = self.positions[ts_code]
        if not sell_date:
            sell_date = datetime.now().strftime("%Y%m%d")
        
        sell_amount = sell_price * pos.shares
        profit = sell_amount - pos.total_cost
        profit_pct = (sell_price - pos.buy_price) / pos.buy_price * 100 if pos.buy_price and pos.buy_price > 0 else 0.0
        hold_days = pos.hold_days(sell_date)
        
        # 记录交易历史
        trade_record = {
            "ts_code": ts_code,
            "name": pos.name,
            "buy_date": pos.buy_date,
            "sell_date": sell_date,
            "buy_price": pos.buy_price,
            "sell_price": sell_price,
            "shares": pos.shares,
            "profit": profit,
            "profit_pct": profit_pct,
            "hold_days": hold_days,
            "strategy": pos.strategy,
            "reason": reason
        }
        self._add_trade_history(trade_record)
        
        # 删除持仓
        del self.positions[ts_code]
        self._save_positions()
        
        logger.info(f"✅ 平仓 {pos.name}({ts_code})，持仓{hold_days}天，盈利{profit:.2f}元({profit_pct:.2f}%)，原因：{reason}")
        return trade_record
    
    def _add_trade_history(self, record: Dict):
        """添加交易历史"""
        history_file = os.path.join(os.path.dirname(__file__), "trade_history.json")
        history = []
        if os.path.exists(history_file):
            try:
                with open(history_file, "r", encoding="utf-8") as f:
                    history = json.load(f)
            except (json.JSONDecodeError, OSError):
                pass  # 文件损坏或不存在，从空列表开始
        
        history.append(record)
        try:
            with open(history_file, "w", encoding="utf-8") as f:
                json.dump(history, f, ensure_ascii=False, indent=2)
        except (OSError, TypeError) as e:
            logger.error(f"❌ 保存交易历史失败: {e}")
    
    async def daily_check(self, current_date: str = None) -> List[Dict]:
        """每日盘后持仓风控检查
        
        从MongoDB获取当日行情，逐只检查：
        1. 持仓超期 → danger级别，建议强制平仓
        2. 触发止损（最低价≤止损价） → danger级别，建议立即卖出
        3. 接近止损（5%以内） → warning级别
        4. 触发止盈（最高价≥止盈价） → success级别，建议止盈
        5. 接近止盈（5%以内） → warning级别
        
        Args:
            current_date: 检查日期（YYYYMMDD），默认当天
        
        Returns:
            List[Dict]: 告警列表，每条包含 ts_code/name/alerts/level 等字段
        """
        if not current_date:
            current_date = datetime.now().strftime("%Y%m%d")
        
        logger.info(f"========== 持仓每日检查 {current_date} ==========")
        alerts = []
        
        if not self.positions:
            logger.info("ℹ️  当前无持仓")
            return alerts
        
        # 获取当日行情数据
        from core.managers import mongo_manager
        ts_codes = list(self.positions.keys())
        
        price_map = {}
        try:
            daily_data = await mongo_manager.find_many(
                "stock_daily_ak_full",
                {"ts_code": {"$in": ts_codes}, "trade_date": int(current_date)},
                projection={"ts_code": 1, "close": 1, "pct_chg": 1, "high": 1, "low": 1, "open": 1, "pre_close": 1}
            )
            if daily_data:
                price_map = {x.get("ts_code", ""): x for x in daily_data if x.get("ts_code")}
        except (ConnectionError, OSError, ValueError) as e:
            logger.error(f"⚠️  获取行情数据失败: {e}，将使用成本价代替")
        except Exception as e:
            logger.error(f"⚠️  获取行情数据异常: {e}，将使用成本价代替")
        
        for ts_code, pos in self.positions.items():
            daily = price_map.get(ts_code, {})
            current_price = daily.get("close", 0) if isinstance(daily, dict) else 0
            if current_price <= 0:
                # 行情缺失时标记为critical而非用成本价替代（成本价代市价导致止损止盈检查失效）
                logger.warning(f"⚠️  {ts_code} 行情缺失，标记为critical")
                alert = {
                    "ts_code": ts_code,
                    "name": pos.name,
                    "current_price": pos.buy_price,  # 仅用于显示
                    "pct_chg": 0,
                    "hold_days": pos.hold_days(current_date),
                    "profit_pct": 0,
                    "alerts": ["⚠️  行情数据缺失，无法计算盈亏，建议人工核查"],
                    "level": "danger"
                }
                alerts.append(alert)
                continue
            high = daily.get("high", current_price) if isinstance(daily, dict) else current_price
            low = daily.get("low", current_price) if isinstance(daily, dict) else current_price
            open_p = daily.get("open", current_price) if isinstance(daily, dict) else current_price
            pct_chg = daily.get("pct_chg", 0) if isinstance(daily, dict) else 0
            
            alert = {
                "ts_code": ts_code,
                "name": pos.name,
                "current_price": current_price,
                "pct_chg": pct_chg,
                "hold_days": pos.hold_days(current_date),
                "profit_pct": pos.current_profit_pct(current_price),
                "alerts": []
            }
            
            # 检查强制平仓
            if pos.should_force_close(current_date):
                alert["alerts"].append(f"⚠️  持仓超期：已持有{alert['hold_days']}天，超过{pos.max_hold_days}天上限，建议强制平仓")
                alert["level"] = "danger"

            # 【V63-P0-5:龙头5天低利润提前退出,与回测_check_and_execute_forced_sells对齐】
            # 【V66-P1-1:从GLOBAL_RISK读取阈值,不再硬编码5天/3%】
            _strategy = pos.strategy or '未知'
            _strategy_id = STRATEGY_NAME_TO_ID.get(_strategy, '')  # 中文名→英文ID
            _early_exit_days = GLOBAL_RISK.get('dragon_head_early_exit_days', 5)
            _early_exit_min_profit = GLOBAL_RISK.get('dragon_head_early_exit_min_profit', 0.03)
            if _strategy_id == 'dragon_head' and alert['hold_days'] >= _early_exit_days and not alert.get('level'):
                profit_pct = pos.current_profit_pct(current_price)
                if profit_pct < _early_exit_min_profit * 100:  # GLOBAL_RISK存小数(0.03), profit_pct是百分比
                    alert["alerts"].append(f"⚠️ 龙头5天低利润：持仓{alert['hold_days']}天收益仅{profit_pct:.1f}%，建议提前退出")
                    alert["level"] = "danger"

            # 检查止损【V50:区分跳空止损vs正常止损,与回测sell_signal_checker对齐】
            # 回测: open<=stop_price → 跳空止损(以open卖出), low<=stop_price → 正常止损(以stop_price卖出)
            if low <= pos.stop_loss_price:
                if open_p <= pos.stop_loss_price and open_p > 0:
                    alert["alerts"].append(f"🔴 跳空止损：开盘价{open_p:.2f}直接跳空低于止损价{pos.stop_loss_price:.2f}，建议以开盘价卖出")
                    alert["level"] = "danger"
                    alert["open"] = open_p  # 【V60:传递开盘价给上层,跳空止损应用open价卖出】
                else:
                    alert["alerts"].append(f"🔴 触发止损：最低价{low:.2f} ≤ 止损价{pos.stop_loss_price:.2f}，建议以止损价卖出")
                    alert["level"] = "danger"
            elif current_price <= pos.stop_loss_price * 1.05:
                alert["alerts"].append(f"🟡 接近止损：当前价{current_price:.2f} 接近止损价{pos.stop_loss_price:.2f}，注意风险")
                alert["level"] = "warning"

            # 检查止盈
            if high >= pos.take_profit_price:
                alert["alerts"].append(f"🟢 触发止盈：最高价{high:.2f} ≥ 止盈价{pos.take_profit_price:.2f}，建议止盈")
                alert["level"] = "success"
            elif current_price >= pos.take_profit_price * 0.95:
                alert["alerts"].append(f"🟡 接近止盈：当前价{current_price:.2f} 接近止盈价{pos.take_profit_price:.2f}，注意落袋为安")
                alert["level"] = "warning"

            # 【V63-P0-1:使用回测SellSignalChecker统一卖出判断,消除实盘-回测不一致】
            # 旧(V62): 调用SellSignalChecker但返回值处理有bug(tuple当dict)且market_data未传入high/low
            # 新(V63): 重构为与live/position_manager.py一致的_check_early_sell_signals方法
            # 将冲高回落/利润保护/高开即卖/利润锁定统一到独立方法中
            self._check_early_sell_signals(pos, open_p, current_price, high, low, alert)
            
            if alert["alerts"]:
                alerts.append(alert)
                logger.warning(f"{alert['level'] == 'danger' and '🔴' or alert['level'] == 'warning' and '🟡' or '🟢'} {pos.name}({ts_code})：")
                for a in alert["alerts"]:
                    logger.info(f"   - {a}")
            else:
                logger.info(f"✅ {pos.name}({ts_code})：当前盈利{alert['profit_pct']:.2f}%，持仓{alert['hold_days']}天，正常")
        
        return alerts
    
    def _check_early_sell_signals(self, pos, open_price: float, close_price: float,
                                    high_price: float, low_price: float, alert: Dict):
        """V63: 冲高回落/利润保护/高开即卖/利润锁定检查(与回测SellSignalChecker对齐)

        【V63-P0-1:与live/position_manager.py的_check_early_sell_signals统一实现】
        - 调用回测SellSignalChecker.check_early_sell(),返回tuple(sell_price, reason)
        - 旧V62代码将tuple当dict处理导致运行时错误,现已修复
        - 告警级别: 冲高回落/高开即卖=danger, 利润保护/利润锁定=success(与paper_trading.py处理一致)
        - live/版本利润保护/利润锁定用warning级别(V63-P0-4:应改为success)

        Args:
            pos: Position持仓对象
            open_price: 开盘价
            close_price: 收盘价
            high_price: 最高价
            low_price: 最低价
            alert: 告警dict(直接追加alerts)
        """
        try:
            # 构建策略参数(从STRATEGY_CONFIGS读取,与回测一致)
            strategy_name = pos.strategy or "龙头低吸"
            strategy_id = STRATEGY_NAME_TO_ID.get(strategy_name, '')  # 【V63:统一使用STRATEGY_NAME_TO_ID映射】

            strategy_params = {}
            strategy_risk_params = {}
            if strategy_id:
                cfg = STRATEGY_CONFIGS.get(strategy_id, {})
                strategy_params = dict(cfg.get('params', {}))
                strategy_risk_params = dict(cfg.get('riskParams', {}))

            # 【V63-P1-1:合并STRATEGY_PULLBACK_PARAMS到strategy_params】
            # 旧: strategy_params只有params,不含pullback_profit_lock_threshold等冲高回落参数
            # 新: pullback参数已在V55-LIVE-009中直接内嵌到STRATEGY_CONFIGS.params,无需额外合并
            # 验证: STRATEGY_CONFIGS各策略params已包含pullback_mid_fallback_pct/pullback_high_threshold/pullback_profit_lock_threshold

            # 创建checker
            checker = SellSignalChecker(
                {strategy_name: strategy_params},
                {strategy_name: strategy_risk_params},
                GLOBAL_RISK
            )

            # 1. 冲高回落/利润保护/高开即卖
            # 【V63修复:check_early_sell返回tuple(sell_price, reason),不是dict】
            early_sell_price, early_sell_reason = checker.check_early_sell(
                pos.ts_code, [strategy_name], pos.buy_price, open_price, close_price)

            if early_sell_price > 0:
                # 【V63-P0-4:告警级别与paper_trading.py处理逻辑对齐】
                # 冲高回落/高开即卖 → danger(会亏损,需紧急处理)
                # 利润保护/利润锁定 → success(仍在盈利,落袋为安)
                # 旧live/版本利润保护/利润锁定用warning,但paper_trading.py只处理success级别的利润保护/利润锁定
                _is_danger = early_sell_reason in ('冲高回落', '高开即卖')
                alert["alerts"].append(
                    f"⚡ {early_sell_reason}: 开盘{open_price:.2f} 收盘{close_price:.2f} "
                    f"成本{pos.buy_price:.2f}, 建议以{early_sell_price:.2f}卖出"
                )
                if not alert.get("level"):
                    alert["level"] = "danger" if _is_danger else "success"
                return  # 早盘信号已触发,不检查利润锁定

            # 2. 利润锁定(盘中冲高但从高点大幅回撤)
            if high_price > 0 and close_price > 0 and pos.buy_price > 0:
                high_rise = (high_price / pos.buy_price - 1)
                close_rise = (close_price / pos.buy_price - 1)
                # 利润锁定参数: 优先策略级, 回退全局
                lock_min_high = GLOBAL_RISK.get('intraday_lock_min_high_rise', 0.05)
                lock_pullback = GLOBAL_RISK.get('intraday_lock_pullback_pct', 0.02)
                lock_min_profit = GLOBAL_RISK.get('intraday_lock_min_profit', 0.02)
                # 【V63:策略级参数覆盖,与live/position_manager.py对齐】
                if strategy_risk_params:
                    if 'intraday_lock_min_high_rise' in strategy_risk_params:
                        lock_min_high = strategy_risk_params['intraday_lock_min_high_rise']
                    if 'intraday_lock_pullback_pct' in strategy_risk_params:
                        lock_pullback = strategy_risk_params['intraday_lock_pullback_pct']
                    if 'intraday_lock_min_profit' in strategy_risk_params:
                        lock_min_profit = strategy_risk_params['intraday_lock_min_profit']

                if high_rise >= lock_min_high and close_price < high_price:
                    intraday_pullback = (high_price - close_price) / high_price
                    if intraday_pullback >= lock_pullback and close_rise >= lock_min_profit:
                        alert["alerts"].append(
                            f"🔒 利润锁定: 盘中冲高{high_rise*100:.1f}%回撤{intraday_pullback*100:.1f}%"
                            f"收盘{close_rise*100:.1f}%, 建议以{close_price:.2f}卖出"
                        )
                        # 【V63-P0-4:利润锁定用success级别,与paper_trading.py处理一致】
                        if not alert.get("level"):
                            alert["level"] = "success"

            # 3. 【V67-P0:盘后trailing_stop检查,与Scanner盘中逻辑对齐】
            # 盘中由Scanner实时监控trailing_stop,但盘后如果Scanner未运行,需要daily_settlement兜底
            # 逻辑: 如果曾盈利>=trailing_stop_pct(策略级), 且收盘价从最高价回撤>=trailing_stop_pct, 则触发
            if high_price > 0 and close_price > 0 and pos.buy_price > 0:
                high_rise = (high_price / pos.buy_price - 1)
                # 从策略级读取trailing_stop_pct
                _ts_pct = strategy_risk_params.get('trailing_stop_pct',
                            GLOBAL_RISK.get('trailing_stop_pct', 0.02))
                # 只有盈利>=trailing_stop_pct时才激活追踪止损
                if high_rise >= _ts_pct and close_price < high_price:
                    pullback_from_high = (high_price - close_price) / high_price
                    # 追踪止损线 = 最高价 * (1 - trailing_stop_pct)
                    trailing_stop_price = high_price * (1 - _ts_pct)
                    if close_price <= trailing_stop_price:
                        close_rise = (close_price / pos.buy_price - 1)
                        alert["alerts"].append(
                            f"🔄 追踪止损: 盘中最高{high_price:.2f}(+{high_rise*100:.1f}%), "
                            f"收盘{close_price:.2f}(+{close_rise*100:.1f}%), "
                            f"从高点回撤{pullback_from_high*100:.1f}%≥{_ts_pct*100:.0f}%, "
                            f"建议以{close_price:.2f}卖出"
                        )
                        if not alert.get("level") or alert.get("level") == "warning":
                            alert["level"] = "success"  # 追踪止损时仍在盈利,用success级别
        except Exception as e:
            logger.warning(f"⚠️ {pos.ts_code} 卖出信号检查失败: {e}")

    def get_positions(self) -> List[Dict]:
        """获取所有持仓（不含实时价格，buy_price作为current_price fallback）
        
        注意：返回的dict不含current_price，如需实时价格请使用get_positions_with_prices()
        """
        result = []
        for pos in self.positions.values():
            result.append({
                "ts_code": pos.ts_code,
                "name": pos.name,
                "buy_date": pos.buy_date,
                "buy_price": pos.buy_price,
                "shares": pos.shares,
                "total_cost": pos.total_cost,
                "stop_loss_price": pos.stop_loss_price,
                "take_profit_price": pos.take_profit_price,
                "hold_days": pos.hold_days(),
                "strategy": pos.strategy,
                "notes": pos.notes
            })
        return result
    
    async def get_positions_with_prices(self, trade_date: str = None) -> List[Dict]:
        """【V66-P0-1修复】获取所有持仓（含实时收盘价）
        
        从MongoDB获取最新收盘价填充current_price字段，解决以下问题：
        - paper_trading._update_account_performance: 净值计算需要真实市价
        - daily_scheduler._step_compute_rebalance: 持仓保护需要真实盈亏
        - daily_scheduler._step_execute_trades: 卖出价需要真实市价
        - risk_alert.check_account_risk: 仓位比例需要真实市价
        
        Args:
            trade_date: 交易日期(YYYYMMDD)，None则获取最新交易日数据
        
        Returns:
            List[Dict]: 持仓列表，每个dict包含current_price字段
        """
        if not trade_date:
            trade_date = datetime.now().strftime("%Y%m%d")
        
        # 先获取基础持仓数据
        positions = self.get_positions()
        if not positions:
            return positions
        
        # 从MongoDB批量获取最新收盘价
        price_map = {}
        try:
            from core.managers import mongo_manager
            ts_codes = [p["ts_code"] for p in positions]
            
            # 先尝试当日数据
            daily_data = await mongo_manager.find_many(
                "stock_daily_ak_full",
                {"ts_code": {"$in": ts_codes}, "trade_date": int(trade_date)},
                projection={"ts_code": 1, "close": 1, "pct_chg": 1, "high": 1, "low": 1, "open": 1}
            )
            
            if daily_data:
                price_map = {x.get("ts_code", ""): x for x in daily_data if x.get("ts_code") and x.get("close", 0) > 0}
            
            # 对当日无数据的，获取最近交易日数据
            missing_codes = [c for c in ts_codes if c not in price_map]
            if missing_codes:
                for code in missing_codes:
                    try:
                        doc = await mongo_manager.find_one(
                            "stock_daily_ak_full",
                            {"ts_code": code},
                            projection={"ts_code": 1, "close": 1, "trade_date": 1},
                            sort=[("trade_date", -1)]
                        )
                        if doc and doc.get("close", 0) > 0:
                            price_map[code] = doc
                    except Exception:
                        pass
        except Exception as e:
            logger.warning(f"获取持仓实时价格失败, fallback到buy_price: {e}")
        
        # 填充current_price
        for pos in positions:
            daily = price_map.get(pos["ts_code"], {})
            pos["current_price"] = daily.get("close", 0) if isinstance(daily, dict) else 0
            if pos["current_price"] <= 0:
                pos["current_price"] = pos["buy_price"]  # fallback到成本价
            # 额外填充行情数据(供上层使用)
            pos["pct_chg"] = daily.get("pct_chg", 0) if isinstance(daily, dict) else 0
            pos["high"] = daily.get("high", 0) if isinstance(daily, dict) else 0
            pos["low"] = daily.get("low", 0) if isinstance(daily, dict) else 0
            pos["open"] = daily.get("open", 0) if isinstance(daily, dict) else 0
        
        return positions
    
    def get_trade_history(self, limit: int = 100) -> List[Dict]:
        """获取交易历史"""
        history_file = os.path.join(os.path.dirname(__file__), "trade_history.json")
        if not os.path.exists(history_file):
            return []
        
        try:
            with open(history_file, "r", encoding="utf-8") as f:
                history = json.load(f)
            if not isinstance(history, list):
                logger.error(f"⚠️  交易历史格式异常，期望list，实际{type(history).__name__}")
                return []
            # 按卖出日期倒序
            history.sort(key=lambda x: x.get("sell_date", ""), reverse=True)
            return history[:limit]
        except (json.JSONDecodeError, OSError, KeyError) as e:
            logger.error(f"⚠️  读取交易历史失败: {e}")
            return []
    
    def get_performance_summary(self) -> Dict:
        """获取绩效统计摘要
        
        基于全部交易历史计算：
        - 总交易次数、胜率、总盈利
        - 平均每笔收益率
        - 最大回撤（简单峰值法）
        - 平均持仓天数
        
        Returns:
            Dict: 绩效统计字典，无交易记录时返回全零默认值
        """
        default_result = {
            "total_trades": 0,
            "win_rate": 0,
            "total_profit": 0,
            "avg_profit_pct": 0,
            "max_drawdown": 0,
            "avg_hold_days": 0
        }
        history = self.get_trade_history()
        if not history:
            return default_result
        
        try:
            total_trades = len(history)
            win_trades = [t for t in history if t.get("profit", 0) > 0]
            lose_trades = [t for t in history if t.get("profit", 0) <= 0]
            win_rate = len(win_trades) / total_trades * 100 if total_trades > 0 else 0
            total_profit = sum(t.get("profit", 0) for t in history)
            avg_profit_pct = sum(t.get("profit_pct", 0) for t in history) / total_trades if total_trades > 0 else 0
            avg_hold_days = sum(t.get("hold_days", 0) for t in history) / total_trades if total_trades > 0 else 0
            
            # 计算最大回撤（简单版）
            balance = 0
            max_balance = 0
            max_drawdown = 0
            for trade in sorted(history, key=lambda x: x.get("sell_date", "")):
                balance += trade.get("profit", 0)
                if balance > max_balance:
                    max_balance = balance
                drawdown = (max_balance - balance) / max_balance * 100 if max_balance > 0 else 0
                if drawdown > max_drawdown:
                    max_drawdown = drawdown
            
            return {
                "total_trades": total_trades,
                "win_trades": len(win_trades),
                "lose_trades": total_trades - len(win_trades),
                "win_rate": round(win_rate, 2),
                "total_profit": round(total_profit, 2),
                "avg_profit_pct": round(avg_profit_pct, 2),
                "max_drawdown": round(max_drawdown, 2),
                "avg_hold_days": round(avg_hold_days, 1),
                "latest_trade_date": history[0].get("sell_date", "") if history else ""
            }
        except (KeyError, TypeError, ZeroDivisionError) as e:
            logger.error(f"⚠️  计算绩效统计失败: {e}")
            return default_result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="持仓管理工具")
    parser.add_argument("--action", required=True, choices=["list", "add", "close", "check", "history", "performance"], help="操作类型")
    parser.add_argument("--ts-code", help="股票代码")
    parser.add_argument("--name", help="股票名称")
    parser.add_argument("--buy-price", type=float, help="买入价格")
    parser.add_argument("--shares", type=int, help="买入数量")
    parser.add_argument("--sell-price", type=float, help="卖出价格")
    parser.add_argument("--reason", help="平仓原因")
    parser.add_argument("--date", help="日期(YYYYMMDD)")
    
    args = parser.parse_args()
    
    manager = PositionManager()
    
    if args.action == "list":
        positions = manager.get_positions()
        if not positions:
            logger.info("当前无持仓")
        else:
            logger.info(f"当前持仓共{len(positions)}只：")
            for pos in positions:
                logger.info(f"{pos['name']}({pos['ts_code']}) | 成本{pos['buy_price']:.2f} | 持仓{pos['hold_days']}天 | 止损{pos['stop_loss_price']:.2f} | 止盈{pos['take_profit_price']:.2f}")
    
    elif args.action == "add":
        if not all([args.ts_code, args.name, args.buy_price, args.shares]):
            logger.error("参数错误：需要 --ts-code、--name、--buy-price、--shares")
            sys.exit(1)
        
        from nodes.backtest_engine.strategy_defaults import GLOBAL_RISK
        
        pos = Position(
            ts_code=args.ts_code,
            name=args.name,
            buy_date=args.date or datetime.now().strftime("%Y%m%d"),
            buy_price=args.buy_price,
            shares=args.shares,
            total_cost=args.buy_price * args.shares,
            stop_loss_price=args.buy_price * (1 - GLOBAL_RISK["stop_loss_pct"]),
            take_profit_price=args.buy_price * (1 + GLOBAL_RISK["take_profit_pct"])
        )
        manager.add_position(pos)
    
    elif args.action == "close":
        if not all([args.ts_code, args.sell_price]):
            logger.error("参数错误：需要 --ts-code、--sell-price")
            sys.exit(1)
        manager.close_position(args.ts_code, args.sell_price, args.date, args.reason or "手动平仓")
    
    elif args.action == "check":
        asyncio.run(manager.daily_check(args.date))
    
    elif args.action == "history":
        history = manager.get_trade_history(20)
        logger.info(f"最近{len(history)}笔交易：")
        for t in history:
            profit_icon = "✅" if t["profit"] > 0 else "❌"
            logger.info(f"{t['sell_date']} {profit_icon} {t['name']}({t['ts_code']}) | 盈利{t['profit']:.2f}元({t['profit_pct']:.2f}%) | 持仓{t['hold_days']}天 | 原因：{t['reason']}")
    
    elif args.action == "performance":
        perf = manager.get_performance_summary()
        logger.info("="*50)
        logger.info("📊 实盘绩效统计")
        logger.info("="*50)
        logger.info(f"总交易次数：{perf['total_trades']}次")
        logger.info(f"胜率：{perf['win_rate']}%（{perf['win_trades']}胜{perf['lose_trades']}负）")
        logger.info(f"总盈利：{perf['total_profit']:.2f}元")
        logger.info(f"平均每笔收益：{perf['avg_profit_pct']:.2f}%")
        logger.info(f"最大回撤：{perf['max_drawdown']:.2f}%")
        logger.info(f"平均持仓天数：{perf['avg_hold_days']}天")
        if perf['latest_trade_date']:
            logger.info(f"最近交易日期：{perf['latest_trade_date']}")
        logger.info("="*50)
