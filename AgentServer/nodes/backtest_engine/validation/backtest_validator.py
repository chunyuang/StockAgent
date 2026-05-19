"""
回测参数校验器

在回测开始前校验参数合法性，防止异常输入导致回测失败或结果异常。
"""

import re
from datetime import datetime
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass


@dataclass
class ValidationError:
    """校验错误"""
    field: str
    message: str
    value: any


class BacktestValidator:
    """回测参数校验器"""
    
    # 日期格式
    DATE_PATTERN = re.compile(r'^\d{8}$')
    
    # 股票代码格式
    STOCK_CODE_PATTERN = re.compile(r'^\d{6}\.(SH|SZ|BJ)$')
    
    # 策略ID列表
    VALID_STRATEGY_IDS = {
        "halfway_chase",
        "first_limit_up", 
        "limit_up_open",
        "dragon_head",
        "leader_buy_dip",  # 龙头低吸 - 前端/实盘信号引擎别名
        "limit_down_qiao"
    }
    
    # 参数范围限制
    PARAM_RANGES = {
        "initial_cash": (10000, 100_000_000),  # 1万~1亿
        "stop_loss_pct": (0.01, 0.2),  # 1%~20%
        "take_profit_pct": (0.01, 0.5),  # 1%~50%
        "max_hold_days": (1, 30),  # 1~30天
        "max_position_per_stock": (0.05, 1.0),  # 5%~100%
        "max_position": (0.1, 1.0),  # 10%~100%
        "commission_rate": (0.0001, 0.01),  # 万1~1%
        "stamp_duty_rate": (0.0001, 0.01),  # 万1~1%
        "slippage_pct": (0.0, 0.05),  # 0~5%
        "liquidity_threshold": (100, 10000),  # 100万~1亿
        "volume_threshold": (0.5, 20.0),  # 0.5~20倍
    }
    
    def validate_backtest_request(self, request: Dict) -> Tuple[bool, List[ValidationError]]:
        """校验回测请求
        
        Args:
            request: 回测请求参数
            
        Returns:
            (is_valid, errors): 是否合法及错误列表
        """
        errors = []
        
        # 1. 校验日期
        errors.extend(self._validate_dates(request))
        
        # 2. 校验资金
        errors.extend(self._validate_capital(request))
        
        # 3. 校验策略
        errors.extend(self._validate_strategies(request))
        
        # 4. 校验风控参数
        errors.extend(self._validate_risk_params(request))
        
        # 5. 校验交易成本
        errors.extend(self._validate_trading_costs(request))
        
        return len(errors) == 0, errors
    
    def _validate_dates(self, request: Dict) -> List[ValidationError]:
        """校验日期参数"""
        errors = []
        
        start_date = request.get("start_date")
        end_date = request.get("end_date")
        
        # 检查格式
        if not start_date or not self.DATE_PATTERN.match(str(start_date)):
            errors.append(ValidationError(
                "start_date",
                f"开始日期格式错误，应为YYYYMMDD格式",
                start_date
            ))
        
        if not end_date or not self.DATE_PATTERN.match(str(end_date)):
            errors.append(ValidationError(
                "end_date",
                f"结束日期格式错误，应为YYYYMMDD格式",
                end_date
            ))
        
        # 检查逻辑
        if start_date and end_date:
            try:
                start_dt = datetime.strptime(str(start_date), '%Y%m%d')
                end_dt = datetime.strptime(str(end_date), '%Y%m%d')
                
                if start_dt > end_dt:
                    errors.append(ValidationError(
                        "start_date",
                        f"开始日期({start_date})不能晚于结束日期({end_date})",
                        start_date
                    ))
                
                # 检查日期范围（不能太久远）
                min_date = datetime(2020, 1, 1)
                max_date = datetime.now()
                
                if start_dt < min_date:
                    errors.append(ValidationError(
                        "start_date",
                        f"开始日期不能早于2020-01-01",
                        start_date
                    ))
                
                if end_dt > max_date:
                    errors.append(ValidationError(
                        "end_date",
                        f"结束日期不能晚于今天",
                        end_date
                    ))
                
                # 检查时间跨度（不超过3年）
                days = (end_dt - start_dt).days
                if days > 365 * 3:
                    errors.append(ValidationError(
                        "end_date",
                        f"回测时间跨度不能超过3年（当前{days}天）",
                        end_date
                    ))
                
            except ValueError as e:
                errors.append(ValidationError(
                    "date",
                    f"日期解析失败: {e}",
                    f"{start_date}~{end_date}"
                ))
        
        return errors
    
    def _validate_capital(self, request: Dict) -> List[ValidationError]:
        """校验资金参数"""
        errors = []
        
        initial_cash = request.get("initial_cash") or request.get("initial_capital")
        
        if initial_cash is not None:
            min_val, max_val = self.PARAM_RANGES["initial_cash"]
            if not isinstance(initial_cash, (int, float)):
                errors.append(ValidationError(
                    "initial_cash",
                    f"初始资金应为数字",
                    initial_cash
                ))
            elif initial_cash < min_val or initial_cash > max_val:
                errors.append(ValidationError(
                    "initial_cash",
                    f"初始资金应在{min_val:,.0f}~{max_val:,.0f}之间",
                    initial_cash
                ))
        
        return errors
    
    def _validate_strategies(self, request: Dict) -> List[ValidationError]:
        """校验策略参数"""
        errors = []
        
        strategies = request.get("strategies") or []
        selected_strategies = request.get("selected_strategies") or []
        
        # 至少需要一个策略
        if not strategies and not selected_strategies:
            errors.append(ValidationError(
                "strategies",
                "至少需要选择一个策略",
                []
            ))
            return errors
        
        # 校验策略ID
        for strategy_id in strategies:
            if strategy_id not in self.VALID_STRATEGY_IDS:
                errors.append(ValidationError(
                    "strategies",
                    f"无效的策略ID: {strategy_id}",
                    strategy_id
                ))
        
        # 校验selected_strategies结构
        for s in selected_strategies:
            if not isinstance(s, dict):
                errors.append(ValidationError(
                    "selected_strategies",
                    "策略配置应为字典",
                    s
                ))
                continue
            
            strategy_id = s.get("id", "")
            if strategy_id not in self.VALID_STRATEGY_IDS:
                errors.append(ValidationError(
                    "selected_strategies",
                    f"无效的策略ID: {strategy_id}",
                    strategy_id
                ))
            
            # 校验策略参数
            params = s.get("params", {})
            if params:
                errors.extend(self._validate_strategy_params(strategy_id, params))
        
        return errors
    
    def _validate_strategy_params(self, strategy_id: str, params: Dict) -> List[ValidationError]:
        """校验策略特定参数"""
        errors = []
        
        # 通用参数校验
        for param_name, (min_val, max_val) in self.PARAM_RANGES.items():
            if param_name in params:
                value = params[param_name]
                if isinstance(value, (int, float)):
                    if value < min_val or value > max_val:
                        errors.append(ValidationError(
                            f"strategies.{strategy_id}.params.{param_name}",
                            f"{param_name}应在{min_val}~{max_val}之间",
                            value
                        ))
        
        # 策略特定参数校验
        if strategy_id == "halfway_chase":
            min_rise = params.get("min_rise_pct")
            max_rise = params.get("max_rise_pct")
            if min_rise is not None and max_rise is not None:
                if min_rise > max_rise:
                    errors.append(ValidationError(
                        "halfway_chase.params",
                        f"最小涨幅({min_rise})不能大于最大涨幅({max_rise})",
                        f"{min_rise}~{max_rise}"
                    ))
        
        elif strategy_id == "first_limit_up":
            min_cap = params.get("min_circulation_market_cap")
            max_cap = params.get("max_circulation_market_cap")
            if min_cap is not None and max_cap is not None:
                if min_cap > max_cap:
                    errors.append(ValidationError(
                        "first_limit_up.params",
                        f"最小市值({min_cap})不能大于最大市值({max_cap})",
                        f"{min_cap}~{max_cap}"
                    ))
        
        return errors
    
    def _validate_risk_params(self, request: Dict) -> List[ValidationError]:
        """校验风控参数"""
        errors = []
        
        params = request.get("params", {})
        
        # 校验止损止盈
        stop_loss = params.get("stop_loss_pct")
        take_profit = params.get("take_profit_pct")
        
        if stop_loss is not None and take_profit is not None:
            if stop_loss >= take_profit:
                errors.append(ValidationError(
                    "params.stop_loss_pct",
                    f"止损比例({stop_loss*100:.1f}%)应小于止盈比例({take_profit*100:.1f}%)",
                    f"{stop_loss} vs {take_profit}"
                ))
        
        # 校验仓位参数
        max_pos_per_stock = params.get("max_position_per_stock")
        max_total_pos = params.get("max_position") or params.get("max_total_position")
        
        if max_pos_per_stock is not None and max_total_pos is not None:
            if max_pos_per_stock > max_total_pos:
                errors.append(ValidationError(
                    "params.max_position_per_stock",
                    f"单票仓位({max_pos_per_stock*100:.0f}%)不能大于总仓位上限({max_total_pos*100:.0f}%)",
                    f"{max_pos_per_stock} vs {max_total_pos}"
                ))
        
        return errors
    
    def _validate_trading_costs(self, request: Dict) -> List[ValidationError]:
        """校验交易成本参数"""
        errors = []
        
        params = request.get("params", {})
        
        # 校验佣金率
        commission = params.get("commission_rate")
        if commission is not None:
            min_val, max_val = self.PARAM_RANGES["commission_rate"]
            if commission < min_val or commission > max_val:
                errors.append(ValidationError(
                    "params.commission_rate",
                    f"佣金率应在{min_val*10000:.0f}~{max_val*10000:.0f}万分之之间",
                    commission
                ))
        
        # 校验印花税
        stamp_duty = params.get("stamp_duty_rate")
        if stamp_duty is not None:
            min_val, max_val = self.PARAM_RANGES["stamp_duty_rate"]
            if stamp_duty < min_val or stamp_duty > max_val:
                errors.append(ValidationError(
                    "params.stamp_duty_rate",
                    f"印花税率应在{min_val*1000:.0f}~{max_val*1000:.0f}千分之之间",
                    stamp_duty
                ))
        
        # 校验滑点
        slippage = params.get("slippage_pct")
        if slippage is not None:
            min_val, max_val = self.PARAM_RANGES["slippage_pct"]
            if slippage < min_val or slippage > max_val:
                errors.append(ValidationError(
                    "params.slippage_pct",
                    f"滑点应在{min_val*100:.0f}%~{max_val*100:.0f}%之间",
                    slippage
                ))
        
        return errors
    
    def get_error_summary(self, errors: List[ValidationError]) -> str:
        """获取错误摘要
        
        Args:
            errors: 错误列表
            
        Returns:
            错误摘要字符串
        """
        if not errors:
            return "✅ 参数校验通过"
        
        lines = [f"❌ 参数校验失败，共{len(errors)}个错误:\n"]
        
        for i, err in enumerate(errors, 1):
            lines.append(f"  {i}. [{err.field}] {err.message}")
            if err.value is not None:
                lines.append(f"     当前值: {err.value}")
        
        return "\n".join(lines)
