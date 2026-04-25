"""
第2层：特殊时期过滤
====================
三大核心功能：
a) 节假日前夕自动降低仓位
b) 重大会议期间自动调整仓位
c) 月末/季末/年末资金紧张时期自动降仓

优先级：年末 > 季末 > 月末 > 重大会议 > 节假日前夕
（取最低的仓位系数，最严格的生效）
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional


@dataclass
class SpecialPeriod:
    """特殊时期配置"""
    name: str
    period_type: str  # holiday, conference, month_end, quarter_end, year_end
    position_ratio: float  # 仓位系数 (0.0-1.0)
    start_date: Optional[str] = None  # YYYYMMDD, 固定日期用
    end_date: Optional[str] = None  # YYYYMMDD, 固定日期用
    days_before: Optional[int] = None  # 相对日期用（节假日前n天）
    days_in_period: Optional[int] = None  # 月末/季末/年末用多少天


class SpecialPeriodFilter:
    """特殊时期过滤器 - 第2层筛选"""
    
    # 内置的中国股市特殊时期配置（2025-2026）
    DEFAULT_CONFIG = [
        # ========== 节假日前夕 ==========
        # 2026年春节（1月29日-2月4日，节前7天降仓）
        SpecialPeriod(
            name="2026年春节前夕",
            period_type="holiday",
            position_ratio=0.2,  # 2成仓位
            start_date="20260118",
            end_date="20260128"
        ),
        # 2025年国庆（10月1-7日，节前5天降仓）
        SpecialPeriod(
            name="2025年国庆前夕",
            period_type="holiday",
            position_ratio=0.3,  # 3成仓位
            start_date="20250922",
            end_date="20250930"
        ),
        # 2026年五一（5月1-5日，节前3天降仓）
        SpecialPeriod(
            name="2026年五一前夕",
            period_type="holiday",
            position_ratio=0.5,  # 5成仓位
            start_date="20260426",
            end_date="20260430"
        ),
        # 2025年中秋（9月17日，节前2天降仓）
        SpecialPeriod(
            name="2025年中秋前夕",
            period_type="holiday",
            position_ratio=0.6,  # 6成仓位
            start_date="20250915",
            end_date="20250916"
        ),
        # 2025年端午（6月10日，节前2天降仓）
        SpecialPeriod(
            name="2025年端午前夕",
            period_type="holiday",
            position_ratio=0.6,  # 6成仓位
            start_date="20250606",
            end_date="20250609"
        ),
        
        # ========== 重大会议期间 ==========
        # 2026年两会（3月5日-3月15日）
        SpecialPeriod(
            name="2026年两会期间",
            period_type="conference",
            position_ratio=0.5,  # 5成仓位
            start_date="20260305",
            end_date="20260315"
        ),
        # 2025年中央经济工作会议（12月15-18日）
        SpecialPeriod(
            name="2025年中央经济工作会议",
            period_type="conference",
            position_ratio=0.4,  # 4成仓位
            start_date="20251215",
            end_date="20251218"
        ),
        # 2025年政治局会议（4月28日、7月24日、10月24日）
        SpecialPeriod(
            name="2025年4月政治局会议",
            period_type="conference",
            position_ratio=0.6,  # 6成仓位
            start_date="20250425",
            end_date="20250428"
        ),
        SpecialPeriod(
            name="2025年7月政治局会议",
            period_type="conference",
            position_ratio=0.6,  # 6成仓位
            start_date="20250721",
            end_date="20250724"
        ),
        SpecialPeriod(
            name="2025年10月政治局会议",
            period_type="conference",
            position_ratio=0.6,  # 6成仓位
            start_date="20251021",
            end_date="20251024"
        ),
        
        # ========== 月末/季末/年末（相对日期，每年都适用） ==========
        # 月末：每月最后3个交易日
        SpecialPeriod(
            name="月末效应",
            period_type="month_end",
            position_ratio=0.7,  # 7成仓位
            days_in_period=3
        ),
        # 季末：每季度最后5个交易日
        SpecialPeriod(
            name="季末效应",
            period_type="quarter_end",
            position_ratio=0.5,  # 5成仓位
            days_in_period=5
        ),
        # 年末：每年最后7个交易日
        SpecialPeriod(
            name="年末效应",
            period_type="year_end",
            position_ratio=0.3,  # 3成仓位
            days_in_period=7
        ),
    ]
    
    def __init__(self, custom_config: Optional[List[SpecialPeriod]] = None):
        """
        初始化特殊时期过滤器
        
        Args:
            custom_config: 自定义配置，如果为None则使用默认配置
        """
        self.config = custom_config if custom_config is not None else self.DEFAULT_CONFIG
        self._period_cache: Dict[str, List[SpecialPeriod]] = {}
    
    def get_position_multiplier(self, trade_date: str) -> float:
        """
        获取指定交易日的仓位系数
        
        优先级：年末 > 季末 > 月末 > 重大会议 > 节假日前夕
        
        Args:
            trade_date: 交易日期，格式 YYYYMMDD
            
        Returns:
            float: 仓位系数 (0.0-1.0)，1.0=满仓，0.5=半仓，0.0=空仓
        """
        date_int = int(trade_date)
        dt = datetime.strptime(trade_date, "%Y%m%d")
        
        active_periods: List[SpecialPeriod] = []
        
        # 1. 检查固定日期的特殊时期（假期、会议）
        for period in self.config:
            if period.start_date and period.end_date:
                start_int = int(period.start_date)
                end_int = int(period.end_date)
                if start_int <= date_int <= end_int:
                    active_periods.append(period)
        
        # 2. 检查月末（每月最后N个交易日）
        month_end_period = next((p for p in self.config if p.period_type == "month_end"), None)
        if month_end_period and self._is_month_end(dt, month_end_period.days_in_period or 3):
            active_periods.append(month_end_period)
        
        # 3. 检查季末（每季度最后N个交易日）
        quarter_end_period = next((p for p in self.config if p.period_type == "quarter_end"), None)
        if quarter_end_period and self._is_quarter_end(dt, quarter_end_period.days_in_period or 5):
            active_periods.append(quarter_end_period)
        
        # 4. 检查年末（每年最后N个交易日）
        year_end_period = next((p for p in self.config if p.period_type == "year_end"), None)
        if year_end_period and self._is_year_end(dt, year_end_period.days_in_period or 7):
            active_periods.append(year_end_period)
        
        if not active_periods:
            return 1.0  # 不在任何特殊时期，满仓
        
        # 取最低的仓位系数（最严格的生效）
        min_ratio = min(p.position_ratio for p in active_periods)
        
        return min_ratio
    
    def get_active_periods(self, trade_date: str) -> List[SpecialPeriod]:
        """
        获取指定日期生效的所有特殊时期
        
        Args:
            trade_date: 交易日期，格式 YYYYMMDD
            
        Returns:
            List[SpecialPeriod]: 生效的特殊时期列表
        """
        date_int = int(trade_date)
        dt = datetime.strptime(trade_date, "%Y%m%d")
        
        active_periods: List[SpecialPeriod] = []
        
        # 检查固定日期的特殊时期
        for period in self.config:
            if period.start_date and period.end_date:
                start_int = int(period.start_date)
                end_int = int(period.end_date)
                if start_int <= date_int <= end_int:
                    active_periods.append(period)
        
        # 检查月末
        month_end_period = next((p for p in self.config if p.period_type == "month_end"), None)
        if month_end_period and self._is_month_end(dt, month_end_period.days_in_period or 3):
            active_periods.append(month_end_period)
        
        # 检查季末
        quarter_end_period = next((p for p in self.config if p.period_type == "quarter_end"), None)
        if quarter_end_period and self._is_quarter_end(dt, quarter_end_period.days_in_period or 5):
            active_periods.append(quarter_end_period)
        
        # 检查年末
        year_end_period = next((p for p in self.config if p.period_type == "year_end"), None)
        if year_end_period and self._is_year_end(dt, year_end_period.days_in_period or 7):
            active_periods.append(year_end_period)
        
        return active_periods
    
    def _is_month_end(self, dt: datetime, n_days: int = 3) -> bool:
        """
        判断是否为月末最后N个交易日（用自然日近似）
        
        Args:
            dt: 日期
            n_days: 最后多少天算月末
            
        Returns:
            bool: 是否为月末
        """
        # 取下个月的第一天
        if dt.month == 12:
            next_month_first = datetime(dt.year + 1, 1, 1)
        else:
            next_month_first = datetime(dt.year, dt.month + 1, 1)
        
        # 计算到月底还有多少天
        days_to_month_end = (next_month_first - dt).days
        
        # 如果在最后N天范围内
        return 0 <= days_to_month_end <= n_days
    
    def _is_quarter_end(self, dt: datetime, n_days: int = 5) -> bool:
        """
        判断是否为季末最后N个交易日
        
        Args:
            dt: 日期
            n_days: 最后多少天算季末
            
        Returns:
            bool: 是否为季末
        """
        # 季度最后一个月：3, 6, 9, 12月
        quarter_end_months = {3, 6, 9, 12}
        
        if dt.month not in quarter_end_months:
            return False
        
        # 计算到季末还有多少天
        if dt.month == 3:
            quarter_end = datetime(dt.year, 4, 1)
        elif dt.month == 6:
            quarter_end = datetime(dt.year, 7, 1)
        elif dt.month == 9:
            quarter_end = datetime(dt.year, 10, 1)
        else:  # 12月
            quarter_end = datetime(dt.year + 1, 1, 1)
        
        days_to_quarter_end = (quarter_end - dt).days
        
        return 0 <= days_to_quarter_end <= n_days
    
    def _is_year_end(self, dt: datetime, n_days: int = 7) -> bool:
        """
        判断是否为年末最后N个交易日
        
        Args:
            dt: 日期
            n_days: 最后多少天算年末
            
        Returns:
            bool: 是否为年末
        """
        year_end = datetime(dt.year + 1, 1, 1)
        days_to_year_end = (year_end - dt).days
        
        return 0 <= days_to_year_end <= n_days
    
    def explain(self, trade_date: str) -> str:
        """
        解释指定日期的仓位决策
        
        Args:
            trade_date: 交易日期，格式 YYYYMMDD
            
        Returns:
            str: 解释文本
        """
        active_periods = self.get_active_periods(trade_date)
        position_multiplier = self.get_position_multiplier(trade_date)
        
        if not active_periods:
            return f"{trade_date}: 不在任何特殊时期，满仓（仓位系数 1.0）"
        
        period_names = ", ".join(p.name for p in active_periods)
        return f"{trade_date}: 处于 [{period_names}]，仓位系数 {position_multiplier:.1f}"


# 全局单例
_special_period_filter: Optional[SpecialPeriodFilter] = None


def get_special_period_filter() -> SpecialPeriodFilter:
    """获取特殊时期过滤器单例"""
    global _special_period_filter
    if _special_period_filter is None:
        _special_period_filter = SpecialPeriodFilter()
    return _special_period_filter
