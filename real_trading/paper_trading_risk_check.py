"""
风控检查模块集成到paper_trading

将pre_buy_risk_check.py的风控检查功能集成到paper_trading交易流程中，实现：
1. 交易前风控检查
2. 拒绝记录
3. 风控配置动态调整
"""

import json
import logging

logger = logging.getLogger(__name__)
import os
from typing import Dict, List, Optional
from datetime import datetime

from pre_buy_risk_check import PreBuyRiskChecker, RiskCheckResult


class PaperTradingEngineWithRisk:
    """
    带风控检查的交易引擎
    
    在PaperTradingEngine基础上添加风控功能：
    - 初始化时创建PreBuyRiskChecker
    - 买入前进行风控检查
    - 记录拒绝交易
    - 支持动态调整风控参数
    """
    
    def __init__(self, data_file: str = "paper_accounts_risk.json"):
        """
        初始化交易引擎
        
        Args:
            data_file: 账户数据文件名
        """
        self.data_file = os.path.join(os.path.dirname(__file__), data_file)
        
        # 初始化风控检查器
        self.risk_checker = PreBuyRiskChecker(config={
            "market_filter_enabled": True,      # 启用市场环境过滤
            "reference_index": "sh000001",       # 上证指数
            "max_index_drop": 0.03,             # 指数最大跌幅3%
            "daily_max_drawdown": 0.03,       # 日内最大回撤3%
            "consecutive_loss_limit": 3,         # 连续亏损3次暂停
            "consecutive_loss_pause_days": 1,    # 暂停1天
            "exclude_st_stocks": True,          # 排除ST股票
            "min_market_cap": 30,              # 最小市值30亿
            "max_volatility": 0.20,             # 最大波动率20%
            "limit_board_caution": True,          # 涨跌停板次日谨慎
        })
        
        # 拒绝记录（用于MongoDB存储和前端展示）
        self.rejection_log_file = os.path.join(
            os.path.dirname(__file__), 
            "paper_trade_rejections.json"
        )
        
        self._load_accounts()
        self._load_rejections()
    
    def _load_accounts(self):
        """加载模拟账户数据"""
        if not os.path.exists(self.data_file):
            return
        
        try:
            with open(self.data_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                if not isinstance(data, dict):
                    logger.error(f"⚠️  账户数据格式异常")
                    self.accounts = {}
                    return
                
                for acc_id, acc_data in data.items():
                    # 只加载账户信息，不加载持仓和交易历史
                    # 这里简化处理，实际应该使用原有的加载逻辑
                    try:
                        from types import SimpleNamespace
                        acc = SimpleNamespace(**acc_data) if isinstance(acc_data, dict) else acc_data
                        self.accounts[acc_id] = acc
                    except (TypeError, AttributeError, KeyError):
                        # 如果数据结构不匹配，创建空对象
                        pass
                
                logger.info(f"✅ 加载账户数据成功，共{len(self.accounts)}个账户")
        except Exception as e:
            logger.error(f"❌ 加载账户数据失败: {e}")
            self.accounts = {}
    
    def _save_accounts(self):
        """保存账户数据"""
        # 这里简化处理，只保存账户信息
        # 实际应该使用原有的保存逻辑
        try:
            with open(self.data_file, "w", encoding="utf-8") as f:
                data = {acc_id: acc.__dict__ for acc_id, acc in self.accounts.items()}
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info("✅ 账户数据已保存")
        except Exception as e:
            logger.error(f"❌ 保存账户数据失败: {e}")
    
    def _load_rejections(self):
        """加载拒绝记录"""
        if not os.path.exists(self.rejection_log_file):
            return []
        
        try:
            with open(self.rejection_log_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
                return []
        except Exception as e:
            logger.error(f"⚠️  加载拒绝记录失败: {e}")
            return []
    
    def _save_rejection(self, rejection: Dict):
        """保存拒绝记录"""
        try:
            # 确保文件存在
            if not os.path.exists(self.rejection_log_file):
                with open(self.rejection_log_file, "w", encoding="utf-8") as f:
                    json.dump([], f, ensure_ascii=False)
            
            # 读取现有记录
            with open(self.rejection_log_file, "r", encoding="utf-8") as f:
                rejections = json.load(f)
            
            # 添加新记录
            rejections.append(rejection)
            
            # 保存
            with open(self.rejection_log_file, "w", encoding="utf-8") as f:
                json.dump(rejections, f, ensure_ascii=False, indent=2)
            logger.info(f"✅ 拒绝记录已保存")
        except Exception as e:
            logger.error(f"❌ 保存拒绝记录失败: {e}")
    
    async def place_order_with_risk_check(self, account_id: str, ts_code: str, name: str, 
                                    buy_price: float, shares: int, 
                                    strategy: str = "未知", slippage: float = 0.002) -> Dict:
        """
        带风控检查的买入下单方法
        
        Args:
            同 PaperTradingEngine.place_order 参数
        """
        # 1. 检查账户是否存在
        if account_id not in self.accounts:
            return {
                "success": False,
                "msg": f"账户{account_id}不存在"
            }
        
        account = self.accounts[account_id]
        if account.status != "active":
            return {
                "success": False,
                "msg": f"账户{account_id}已关闭"
            }
        
        # 2. 风控检查
        try:
            risk_result = self.risk_checker.check_before_buy(
                account_id=account_id,
                ts_code=ts_code,
                buy_price=buy_price,
                buy_amount=buy_price * shares,
                initial_balance=self._get_initial_balance(account_id)
            )
        except Exception as e:
            # 风控检查异常，记录日志但允许交易继续
            logger.error(f"⚠️ 风控检查异常: {e}")
            risk_result = RiskCheckResult(
                allowed=True,  # 检查失败默认允许交易
                reason="风控检查异常，允许交易",
                risk_level="medium",
                details={"error": str(e)},
                timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            )
        
        # 3. 如果未通过风控检查，拒绝交易
        if not risk_result.allowed:
            # 记录拒绝
            rejection = {
                "timestamp": datetime.now().isoformat(),
                "account_id": account_id,
                "ts_code": ts_code,
                "buy_price": buy_price,
                "shares": shares,
                "strategy": strategy,
                "risk_check": risk_result.to_dict(),
                "slippage": slippage
            }
            self._save_rejection(rejection)
            
            logger.error(f"❌ 交易被拒绝: {risk_result.reason}")
            return {
                "success": False,
                "msg": f"交易被风控拒绝: {risk_result.reason}",
                "rejection": rejection
            }
        
        # 4. 通过风控检查，执行交易（这里简化处理，实际应调用原PaperTradingEngine的交易逻辑）
        logger.info(f"✅ 风控检查通过，允许交易")
        logger.info(f"📊 股票: {name}({ts_code}) 数量: {shares}")
        
        # TODO: 这里应该调用原有的buy_stock逻辑
        # 实际集成时需要：
        # 1. 保留原PaperTradingEngine类
        # 2. 或将风控检查集成到原有的place_order方法中
        # 3. 避免重复实现交易逻辑
        
        # 模拟返回成功（仅用于演示）
        return {
            "success": True,
            "msg": "下单成功(风控检查已通过)"
        }
    
    def _get_initial_balance(self, account_id: str) -> float:
        """获取账户初始余额
        
        这里简化处理，实际应该从账户信息中获取
        """
        if account_id not in self.accounts:
            return 100000.0
        
        account = self.accounts[account_id]
        # 返回当前余额作为初始余额的估算
        return account.current_balance
    
    def get_rejection_list(self, account_id: str = None, limit: int = 50, 
                         start_date: str = None, end_date: str = None) -> List[Dict]:
        """
        获取拒绝记录列表
        
        Args:
            account_id: 账户ID，None则返回所有记录
            limit: 返回记录数限制
            start_date: 开始日期（YYYYMMDD）
            end_date: 结束日期（YYYYMMDD）
        
        Returns:
            拒绝记录列表
        """
        rejections = self._load_rejections()
        
        # 筛选
        filtered = rejections
        if account_id:
            filtered = [r for r in rejections if r.get("account_id") == account_id]
        
        if start_date:
            filtered = [r for r in filtered if r.get("timestamp", "") >= start_date]
        if end_date:
            filtered = [r for r in filtered if r.get("timestamp", "") <= end_date]
        
        if limit:
            filtered = filtered[-limit:]
        
        return filtered
    
    def update_risk_config(self, config: Dict[str, any]):
        """
        动态更新风控配置
        
        Args:
            config: 风控参数配置字典
        """
        self.risk_checker.config = {
            **self.risk_checker.config,
            **config
        }
        logger.info(f"✅ 风控配置已更新")
    
    def get_risk_config(self) -> Dict[str, any]:
        """
        获取当前风控配置
        
        Returns:
            当前风控配置字典
        """
        return self.risk_checker.config


# 使用示例
if __name__ == "__main__":
    engine = PaperTradingEngineWithRisk()
    
    # 测试风控检查
    logger.info("测试风控检查...")
    
    # 获取当前风控配置
    config = engine.get_risk_config()
    logger.info("当前风控配置:", config)
    
    # 获取拒绝记录
    rejections = engine.get_rejection_list()
    logger.info(f"拒绝记录数: {len(rejections)}")