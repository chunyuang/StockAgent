#!/usr/bin/env python3
"""
买入前风控检查模块
实现交易前的多层次风险过滤，防止在高风险环境下开仓

风控检查项（基于金融专家审核建议）：
1. 市场环境过滤：上证指数跌幅>3%暂停开仓
2. 日内回撤控制：单日最大回撤3%熔断
3. 连续亏损熔断：连续3次亏损暂停交易
4. 个股风险过滤：排除ST/最小市值30亿/最大波动率20%

返回结果：包含是否允许交易和明确拒绝原因
"""
import sys
import logging

logger = logging.getLogger(__name__)
import os
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'AgentServer'))
sys.path.insert(0, os.path.dirname(__file__))


@dataclass
class RiskCheckResult:
    """风控检查结果"""
    allowed: bool                  # 是否允许交易
    reason: str                   # 允许或拒绝的原因说明
    risk_level: str              # 风险等级：low/medium/high/critical
    details: Dict[str, any]      # 详细检查结果
    timestamp: str               # 检查时间
    
    def to_dict(self):
        return asdict(self)


class PreBuyRiskChecker:
    """买入前风控检查器
    
    在执行买入交易前，先进行全方位风险检查。
    如果任何一项检查未通过，拒绝开仓并返回明确原因。
    
    使用方式：
        checker = PreBuyRiskChecker(config)
        result = checker.check_before_buy(
            account_id="acc001",
            ts_code="000001.SZ",
            buy_price=10.50,
            buy_amount=10000
        )
        
        if not result.allowed:
            logger.error(f"❌ 交易被拒绝: {result.reason}")
        else:
            logger.info(f"✅ 允许交易: {result.reason}")
    """
    
    def __init__(self, config: Dict = None):
        """初始化风控检查器
        
        Args:
            config: 可选配置覆盖
                - market_filter_enabled: 是否启用市场环境过滤（默认True）
                - reference_index: 参考指数代码（默认sh000001上证指数）
                - max_index_drop: 指数最大跌幅阈值（默认0.03）
                - daily_max_drawdown: 单日最大回撤阈值（默认0.03）
                - consecutive_loss_limit: 连续亏损次数限制（默认3）
                - exclude_st_stocks: 是否排除ST股票（默认True）
                - min_market_cap: 最小市值阈值，单位亿元（默认30）
                - max_volatility: 最大波动率阈值（默认0.20）
        """
        self.default_config = {
            "market_filter_enabled": True,        # 启用市场环境过滤
            "reference_index": "sh000001",       # 参考指数：上证指数
            "max_index_drop": 0.03,             # 指数最大跌幅3%
            "daily_max_drawdown": 0.03,         # 单日最大回撤3%
            "consecutive_loss_limit": 3,         # 连续亏损3次熔断
            "consecutive_loss_pause_days": 1,    # 熔断后暂停天数
            "exclude_st_stocks": True,           # 排除ST股票
            "min_market_cap": 30,                # 最小市值30亿元
            "max_volatility": 0.20,              # 最大波动率20%
            "limit_board_caution": True,         # 涨跌停板次日谨慎
        }
        self.config = {**self.default_config, **(config or {})}
        
        # 数据文件路径
        self.trade_history_file = os.path.join(os.path.dirname(__file__), "trade_history.json")
        self.market_data_file = os.path.join(os.path.dirname(__file__), "market_data_cache.json")
        self.stock_risk_file = os.path.join(os.path.dirname(__file__), "stock_risk_cache.json")
        
        # 加载历史数据
        self.trade_history = self._load_trade_history()
        self.market_data = self._load_market_data()
        self.stock_risk_cache = self._load_stock_risk_cache()
    
    def _load_trade_history(self) -> List[Dict]:
        """加载交易历史"""
        if not os.path.exists(self.trade_history_file):
            return []
        try:
            with open(self.trade_history_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                if not isinstance(data, list):
                    return []
                return data
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"⚠️  加载交易历史失败: {e}")
            return []
    
    def _save_trade_history(self):
        """保存交易历史"""
        try:
            with open(self.trade_history_file, "w", encoding="utf-8") as f:
                json.dump(self.trade_history, f, ensure_ascii=False, indent=2)
        except (OSError, TypeError) as e:
            logger.error(f"⚠️  保存交易历史失败: {e}")
    
    def _load_market_data(self) -> Dict:
        """加载市场数据缓存"""
        if not os.path.exists(self.market_data_file):
            return {}
        try:
            with open(self.market_data_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                if not isinstance(data, dict):
                    return {}
                return data
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"⚠️  加载市场数据失败: {e}")
            return {}
    
    def _save_market_data(self):
        """保存市场数据缓存"""
        try:
            with open(self.market_data_file, "w", encoding="utf-8") as f:
                json.dump(self.market_data, f, ensure_ascii=False, indent=2)
        except (OSError, TypeError) as e:
            logger.error(f"⚠️  保存市场数据失败: {e}")
    
    def _load_stock_risk_cache(self) -> Dict:
        """加载股票风险缓存"""
        if not os.path.exists(self.stock_risk_file):
            return {}
        try:
            with open(self.stock_risk_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                if not isinstance(data, dict):
                    return {}
                return data
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"⚠️  加载股票风险缓存失败: {e}")
            return {}
    
    def _save_stock_risk_cache(self):
        """保存股票风险缓存"""
        try:
            with open(self.stock_risk_file, "w", encoding="utf-8") as f:
                json.dump(self.stock_risk_cache, f, ensure_ascii=False, indent=2)
        except (OSError, TypeError) as e:
            logger.error(f"⚠️  保存股票风险缓存失败: {e}")
    
    def _record_trade(self, account_id: str, ts_code: str, 
                      buy_price: float, buy_amount: float, 
                      sell_price: float = None, result: str = "pending"):
        """记录交易
        
        Args:
            account_id: 账户ID
            ts_code: 股票代码
            buy_price: 买入价格
            buy_amount: 买入金额
            sell_price: 卖出价格（可选）
            result: 交易结果（pending/profit/loss）
        """
        self.trade_history.append({
            "time": datetime.now().isoformat(),
            "account_id": account_id,
            "ts_code": ts_code,
            "buy_price": buy_price,
            "buy_amount": buy_amount,
            "sell_price": sell_price,
            "result": result,
            "profit_pct": None,
            "profit_amount": None
        })
        
        # 如果有卖出价格，计算盈亏
        if sell_price:
            profit_amount = (sell_price - buy_price) * (buy_amount / buy_price)
            profit_pct = (sell_price - buy_price) / buy_price * 100
            
            self.trade_history[-1]["profit_amount"] = profit_amount
            self.trade_history[-1]["profit_pct"] = profit_pct
            
            if profit_pct >= 0:
                self.trade_history[-1]["result"] = "profit"
            else:
                self.trade_history[-1]["result"] = "loss"
        
        self._save_trade_history()
    
    def _get_consecutive_losses(self, account_id: str, days: int = 5) -> int:
        """获取连续亏损次数
        
        Args:
            account_id: 账户ID
            days: 查看最近N天的交易记录
        
        Returns:
            int: 连续亏损次数
        """
        cutoff_date = datetime.now() - timedelta(days=days)
        recent_trades = [
            t for t in self.trade_history 
            if t["account_id"] == account_id 
            and t["result"] in ["profit", "loss"]
            and datetime.fromisoformat(t["time"]) >= cutoff_date
        ]
        
        if not recent_trades:
            return 0
        
        # 计算连续亏损次数
        consecutive_count = 0
        for trade in reversed(recent_trades):
            if trade["result"] == "loss":
                consecutive_count += 1
            else:
                break
        
        return consecutive_count
    
    def _check_market_environment(self) -> Tuple[bool, str, Dict]:
        """检查市场环境
        
        检查上证指数等参考指数的跌幅是否超过阈值
        
        Returns:
            Tuple[bool, str, Dict]: (是否通过, 原因说明, 详细数据)
        """
        if not self.config["market_filter_enabled"]:
            return True, "市场环境过滤已禁用", {"enabled": False}
        
        try:
            # TODO: 从实际数据源获取指数数据
            # 这里使用模拟数据，实际应从 tushare/akshare 获取
            index_code = self.config["reference_index"]
            
            # 模拟获取今日指数跌幅
            # 实际实现：从market_data_cache读取或从API获取
            today_drop = self.market_data.get(f"{index_code}_today_drop", 0.01)  # 模拟1%跌幅
            
            details = {
                "index_code": index_code,
                "today_drop": today_drop,
                "threshold": self.config["max_index_drop"]
            }
            
            if today_drop >= self.config["max_index_drop"]:
                return False, f"市场环境恶劣，{index_code}今日跌幅{today_drop*100:.2f}%，超过阈值{self.config['max_index_drop']*100:.0f}%，暂停开仓", details
            
            return True, f"市场环境正常，{index_code}今日跌幅{today_drop*100:.2f}%，在安全范围内", details
            
        except Exception as e:
            logger.error(f"⚠️  市场环境检查异常: {e}")
            # 出错时保守处理，允许交易
            return True, "市场环境检查异常，默认允许交易", {"error": str(e)}
    
    def _check_daily_drawdown(self, account_id: str, current_balance: float, 
                              initial_balance: float) -> Tuple[bool, str, Dict]:
        """检查日内回撤
        
        计算账户当日最大回撤，如果超过阈值则拒绝交易
        
        Args:
            account_id: 账户ID
            current_balance: 当前余额
            initial_balance: 当日初始余额
        
        Returns:
            Tuple[bool, str, Dict]: (是否通过, 原因说明, 详细数据)
        """
        if current_balance <= 0:
            return False, "账户余额为0或负数，无法交易", {"balance": current_balance}
        
        # 计算当日回撤
        if initial_balance <= 0:
            return True, "当日初始余额无效，跳过回撤检查", {"initial_balance": initial_balance}
        
        drawdown = (initial_balance - current_balance) / initial_balance
        
        details = {
            "current_balance": current_balance,
            "initial_balance": initial_balance,
            "drawdown": drawdown,
            "threshold": self.config["daily_max_drawdown"]
        }
        
        if drawdown >= self.config["daily_max_drawdown"]:
            return False, f"日内回撤过大，当前回撤{drawdown*100:.2f}%，超过阈值{self.config['daily_max_drawdown']*100:.0f}%，触发熔断", details
        
        return True, f"日内回撤正常，当前回撤{drawdown*100:.2f}%，在安全范围内", details
    
    def _check_consecutive_losses(self, account_id: str) -> Tuple[bool, str, Dict]:
        """检查连续亏损
        
        统计最近N天的交易记录，如果连续亏损次数超过阈值则拒绝交易
        
        Args:
            account_id: 账户ID
        
        Returns:
            Tuple[bool, str, Dict]: (是否通过, 原因说明, 详细数据)
        """
        consecutive_losses = self._get_consecutive_losses(account_id, days=5)
        
        details = {
            "consecutive_losses": consecutive_losses,
            "threshold": self.config["consecutive_loss_limit"]
        }
        
        if consecutive_losses >= self.config["consecutive_loss_limit"]:
            return False, f"连续亏损次数过多，最近5天连续亏损{consecutive_losses}次，超过阈值{self.config['consecutive_loss_limit']}次，触发熔断", details
        
        if consecutive_losses > 0:
            return True, f"连续亏损{consecutive_losses}次，未达到熔断阈值{self.config['consecutive_loss_limit']}次，谨慎交易", details
        
        return True, "近期无连续亏损，交易状态良好", details
    
    def _check_stock_risk(self, ts_code: str, current_price: float = None) -> Tuple[bool, str, Dict]:
        """检查个股风险
        
        检查股票是否属于高风险类型：
        - ST股票
        - 小盘股（市值过小）
        - 高波动率股票
        
        Args:
            ts_code: 股票代码
            current_price: 当前价格（可选，用于计算市值）
        
        Returns:
            Tuple[bool, str, Dict]: (是否通过, 原因说明, 详细数据)
        """
        # 检查ST股票
        if self.config["exclude_st_stocks"]:
            is_st = "ST" in ts_code or "*ST" in ts_code
            if is_st:
                return False, f"个股风险过高，{ts_code}为ST股票，已被排除", {"is_st": True}
        
        # TODO: 从实际数据源获取股票基本信息（市值、波动率等）
        # 这里使用模拟数据，实际应从数据库获取
        stock_info = self.stock_risk_cache.get(ts_code, {
            "market_cap": 50,  # 模拟50亿市值
            "volatility_20d": 0.15,  # 模拟20日波动率15%
            "limit_up_days": 0,  # 连续涨停天数
            "limit_down_days": 0  # 连续跌停天数
        })
        
        details = {
            "ts_code": ts_code,
            "market_cap": stock_info.get("market_cap", 0),
            "volatility_20d": stock_info.get("volatility_20d", 0),
            "limit_up_days": stock_info.get("limit_up_days", 0),
            "limit_down_days": stock_info.get("limit_down_days", 0)
        }
        
        # 检查市值
        min_cap = self.config["min_market_cap"]
        if stock_info.get("market_cap", 0) < min_cap:
            return False, f"个股风险过高，{ts_code}市值{stock_info.get('market_cap', 0)}亿元，低于阈值{min_cap}亿元", details
        
        # 检查波动率
        max_volatility = self.config["max_volatility"]
        if stock_info.get("volatility_20d", 0) > max_volatility:
            return False, f"个股风险过高，{ts_code}20日波动率{stock_info.get('volatility_20d', 0)*100:.1f}%，超过阈值{max_volatility*100:.0f}%", details
        
        # 检查涨跌停板次日谨慎
        if self.config["limit_board_caution"]:
            limit_up = stock_info.get("limit_up_days", 0)
            limit_down = stock_info.get("limit_down_days", 0)
            if limit_up >= 2 or limit_down >= 2:
                return False, f"个股风险过高，{ts_code}连续涨停{limit_up}天/跌停{limit_down}天，次日延续性差，谨慎交易", details
        
        return True, f"{ts_code}个股风险检查通过，市值{stock_info.get('market_cap', 0)}亿元，20日波动率{stock_info.get('volatility_20d', 0)*100:.1f}%", details
    
    def check_before_buy(self, account_id: str, ts_code: str, 
                       buy_price: float, buy_amount: float,
                       initial_balance: float = None,
                       current_balance: float = None) -> RiskCheckResult:
        """买入前风控检查（入口方法）
        
        依次执行5项检查，如果任何一项未通过则拒绝交易
        
        Args:
            account_id: 账户ID
            ts_code: 股票代码
            buy_price: 买入价格
            buy_amount: 买入金额
            initial_balance: 当日初始余额（可选，用于计算回撤）
        
        Returns:
            RiskCheckResult: 风控检查结果
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        details = {}
        all_reasons = []
        
        # 1. 市场环境过滤
        market_passed, market_reason, market_details = self._check_market_environment()
        details["market_check"] = market_details
        all_reasons.append(f"市场环境: {market_reason}")
        
        if not market_passed:
            return RiskCheckResult(
                allowed=False,
                reason=market_reason,
                risk_level="critical",
                details=details,
                timestamp=timestamp
            )
        
        # 2. 日内回撤控制
        if initial_balance:
            drawdown_passed, drawdown_reason, drawdown_details = self._check_daily_drawdown(
                account_id, current_balance or initial_balance or buy_amount, initial_balance
            )
            details["drawdown_check"] = drawdown_details
            all_reasons.append(f"日内回撤: {drawdown_reason}")
            
            if not drawdown_passed:
                return RiskCheckResult(
                    allowed=False,
                    reason=drawdown_reason,
                    risk_level="high",
                    details=details,
                    timestamp=timestamp
                )
        
        # 3. 连续亏损熔断
        loss_passed, loss_reason, loss_details = self._check_consecutive_losses(account_id)
        details["consecutive_loss_check"] = loss_details
        all_reasons.append(f"连续亏损: {loss_reason}")
        
        if not loss_passed:
            return RiskCheckResult(
                allowed=False,
                reason=loss_reason,
                risk_level="high",
                details=details,
                timestamp=timestamp
            )
        
        # 4. 个股风险过滤
        stock_passed, stock_reason, stock_details = self._check_stock_risk(ts_code, buy_price)
        details["stock_risk_check"] = stock_details
        all_reasons.append(f"个股风险: {stock_reason}")
        
        if not stock_passed:
            return RiskCheckResult(
                allowed=False,
                reason=stock_reason,
                risk_level="medium",
                details=details,
                timestamp=timestamp
            )
        
        # 5. 涨跌停板检查
        limit_check_details = {"ts_code": ts_code, "buy_price": buy_price}
        # TODO: 接入实时行情判断当前是否涨停/跌停
        # 涨停板无法买入，跌停板次日谨慎
        details["limit_board_check"] = limit_check_details
        all_reasons.append("涨跌停板: 检查通过（待接入实时行情）")
        
        # 全部检查通过
        return RiskCheckResult(
            allowed=True,
            reason=";".join(all_reasons),
            risk_level="low",
            details=details,
            timestamp=timestamp
        )
    
    def check_before_sell(self, account_id: str, ts_code: str,
                         sell_price: float, buy_price: float,
                         reason: str = "手动平仓") -> RiskCheckResult:
        """卖出前风控检查
        
        检查卖出操作是否合理，防止非理性卖出：
        - 止损检查：如果当前价格已跌破止损价，应立即卖出
        - 止盈检查：如果已达到止盈目标，提醒卖出
        - 情绪卖出检查：防止恐慌性抛售
        
        Args:
            account_id: 账户ID
            ts_code: 股票代码
            sell_price: 卖出价格
            buy_price: 买入价格
            reason: 卖出原因
        
        Returns:
            RiskCheckResult: 风控检查结果
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        details = {}
        
        profit_pct = (sell_price - buy_price) / buy_price if buy_price > 0 else 0
        details["profit_pct"] = profit_pct
        
        # 止损触发：亏损超过5%应果断止损
        if profit_pct < -0.05:
            return RiskCheckResult(
                allowed=True,
                reason=f"止损卖出：{ts_code}亏损{profit_pct*100:.2f}%，超过5%止损线，建议立即卖出",
                risk_level="high",
                details=details,
                timestamp=timestamp
            )
        
        # 止盈提醒
        if profit_pct > 0.10:
            details["take_profit_hint"] = True
        
        # 正常卖出
        return RiskCheckResult(
            allowed=True,
            reason=f"允许卖出：{ts_code}，盈亏{profit_pct*100:.2f}%",
            risk_level="low",
            details=details,
            timestamp=timestamp
        )
    
    def update_trade_result(self, account_id: str, ts_code: str,
                           buy_price: float, sell_price: float, buy_amount: float):
        """更新交易结果（用于连续亏损统计）
        
        在平仓完成后调用，记录本次交易的盈亏结果。
        
        Args:
            account_id: 账户ID
            ts_code: 股票代码
            buy_price: 买入价格
            sell_price: 卖出价格
            buy_amount: 买入金额
        """
        profit_pct = (sell_price - buy_price) / buy_price * 100 if buy_price > 0 else 0
        result = "profit" if profit_pct >= 0 else "loss"
        
        self.trade_history.append({
            "time": datetime.now().isoformat(),
            "account_id": account_id,
            "ts_code": ts_code,
            "buy_price": buy_price,
            "buy_amount": buy_amount,
            "sell_price": sell_price,
            "result": result,
            "profit_pct": profit_pct,
            "profit_amount": (sell_price - buy_price) * (buy_amount / buy_price) if buy_price > 0 else 0
        })
        
        self._save_trade_history()
        return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="买入前风控检查工具")
    parser.add_argument("--check-buy", action="store_true", help="执行买入风控检查")
    parser.add_argument("--account-id", required=True, help="账户ID")
    parser.add_argument("--ts-code", required=True, help="股票代码")
    parser.add_argument("--buy-price", type=float, required=True, help="买入价格")
    parser.add_argument("--buy-amount", type=float, required=True, help="买入金额")
    parser.add_argument("--initial-balance", type=float, help="当日初始余额")
    
    args = parser.parse_args()
    
    checker = PreBuyRiskChecker()
    
    if args.check_buy:
        result = checker.check_before_buy(
            account_id=args.account_id,
            ts_code=args.ts_code,
            buy_price=args.buy_price,
            buy_amount=args.buy_amount,
            initial_balance=args.initial_balance
        )
        if result:
            logger.info(f"风控检查结果: {'允许' if result.allowed else '拒绝'}")
            logger.info(f"原因: {result.reason}")
            logger.info(f"风险等级: {result.risk_level}")
        else:
            logger.error("风控检查返回空结果（可能数据源异常）")
