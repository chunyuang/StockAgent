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
    period_type: str  # holiday, conference, month_end, quarter_end, year_end, futures_expiry, option_expiry, earnings_period
    position_ratio: float  # 仓位系数 (0.0-1.0)
    start_date: Optional[str] = None  # YYYYMMDD, 固定日期用
    end_date: Optional[str] = None  # YYYYMMDD, 固定日期用
    days_before: Optional[int] = None  # 相对日期用（节假日前n天）
    days_in_period: Optional[int] = None  # 月末/季末/年末用多少天


class SpecialPeriodFilter:
    """特殊时期过滤器 - 第2层筛选"""
    
    # 内置的中国股市特殊时期配置（2025-2026）
    # 【P2-E修复：假期/会议日期硬编码，回测超出2025-2026范围时warn】
    # 假期日期来源：国务院办公厅年度放假通知
    # 会议日期来源：两会/政治局会议常规时间
    # 注意：新增年份时需在此追加配置
    DEFAULT_CONFIG = [
        # ========== 节假日前夕 ==========
        # 2025年清明（4月4日，节前2天降仓）
        SpecialPeriod(
            name="2025年清明前夕",
            period_type="holiday",
            position_ratio=0.6,  # 6成仓位
            start_date="20250401",
            end_date="20250403"
        ),
        # 2025年五一（5月1-5日，节前3天降仓）
        SpecialPeriod(
            name="2025年五一前夕",
            period_type="holiday",
            position_ratio=0.5,  # 5成仓位
            start_date="20250425",
            end_date="20250430"
        ),
        # 2026年清明（4月5日，节前2天降仓）
        SpecialPeriod(
            name="2026年清明前夕",
            period_type="holiday",
            position_ratio=0.6,  # 6成仓位
            start_date="20260330",
            end_date="20260402"
        ),
        # 2025年春节（1月28日-2月4日，节前7天降仓）
        # 【P1-4修复(V12)：补充2025年春节配置，回测2025年数据时也会降仓】
        SpecialPeriod(
            name="2025年春节前夕",
            period_type="holiday",
            position_ratio=0.2,  # 2成仓位
            start_date="20250117",
            end_date="20250127"
        ),
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
        
        # ========== 股指期货交割日（每月第三个周五） ==========
        # 影响：交割日尾盘集中交割放大波动，当月合约到期日效应
        # 设计：交割日当天0.8，前1天0.9（相对日期，每年自动适用）
        SpecialPeriod(
            name="股指期货交割日",
            period_type="futures_expiry",
            position_ratio=0.8,
        ),
        SpecialPeriod(
            name="股指期货交割日前1天",
            period_type="futures_expiry",
            position_ratio=0.9,
        ),
        
        # ========== ETF期权交割日（每月第四个周三） ==========
        # 影响：50ETF/300ETF期权交割，对大盘蓝筹有压制
        SpecialPeriod(
            name="ETF期权交割日",
            period_type="option_expiry",
            position_ratio=0.9,
        ),
        
        # ========== 财报密集披露期（相对日期，每年适用） ==========
        # 影响：1月(年报预告)/4月(年报+一季报)/7月(中报预告)/10月(三季报)截止日前3天
        # 业绩雷集中爆发，超短策略持仓容易被个股暴雷拖累
        # 设计：披露截止日前3天仓位0.6
        SpecialPeriod(
            name="财报披露截止期",
            period_type="earnings_period",
            position_ratio=0.6,
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
        # 检测配置覆盖的年份范围，用于回测时警告
        fixed_dates = [p for p in self.config if p.start_date]
        if fixed_dates:
            self._covered_years = {int(p.start_date[:4]) for p in fixed_dates}
        else:
            self._covered_years = set()
    
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
        
        # 警告：回测日期超出固定假期配置范围
        if self._covered_years and int(trade_date[:4]) > max(self._covered_years):
            import logging
            logging.getLogger(__name__).warning(
                f"回测日期{trade_date}超出特殊时期配置范围({min(self._covered_years)}-{max(self._covered_years)})，"
                f"假期/会议降仓将不会生效，请在DEFAULT_CONFIG中补充{trade_date[:4]}年配置"
            )
        
        active_periods: List[SpecialPeriod] = []
        
        # 1. 检查固定日期的特殊时期（假期、会议）
        for period in self.config:
            if period.start_date and period.end_date:
                start_int = int(period.start_date)
                end_int = int(period.end_date)
                if start_int <= date_int <= end_int:
                    active_periods.append(period)
        
        # 2. 检查股指期货交割日（每月第三个周五±1天）
        futures_periods = [p for p in self.config if p.period_type == "futures_expiry"]
        for fp in futures_periods:
            if self._is_futures_expiry(dt, fp):
                active_periods.append(fp)
        
        # 3. 检查ETF期权交割日（每月第四个周三）
        option_periods = [p for p in self.config if p.period_type == "option_expiry"]
        for op in option_periods:
            if self._is_option_expiry(dt):
                active_periods.append(op)
        
        # 4. 检查财报披露期
        earnings_periods = [p for p in self.config if p.period_type == "earnings_period"]
        for ep in earnings_periods:
            if self._is_earnings_period(dt):
                active_periods.append(ep)
        
        # 5. 检查月末
        month_end_period = next((p for p in self.config if p.period_type == "month_end"), None)
        if month_end_period and self._is_month_end(dt, month_end_period.days_in_period or 3):
            active_periods.append(month_end_period)
        
        # 6. 检查季末
        quarter_end_period = next((p for p in self.config if p.period_type == "quarter_end"), None)
        if quarter_end_period and self._is_quarter_end(dt, quarter_end_period.days_in_period or 5):
            active_periods.append(quarter_end_period)
        
        # 7. 检查年末
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
        
        # 检查股指期货交割日
        for fp in [p for p in self.config if p.period_type == "futures_expiry"]:
            if self._is_futures_expiry(dt, fp):
                active_periods.append(fp)
        
        # 检查ETF期权交割日
        for op in [p for p in self.config if p.period_type == "option_expiry"]:
            if self._is_option_expiry(dt):
                active_periods.append(op)
        
        # 检查财报披露期
        for ep in [p for p in self.config if p.period_type == "earnings_period"]:
            if self._is_earnings_period(dt):
                active_periods.append(ep)
        
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
    
    def _is_futures_expiry(self, dt: datetime, period: SpecialPeriod) -> bool:
        """判断是否为股指期货交割日（每月第三个周五）或前1天
        
        中国金融期货交易所规定：股指期货交割日为每月第三个周五
        遇法定节假日顺延，但极少发生（2026年无此情况）
        
        Args:
            dt: 日期
            period: 交割日配置（通过position_ratio区分当天0.8和前1天0.9）
        Returns:
            bool
        """
        if dt.weekday() != 4:  # 不是周五
            # 检查是否是交割日前1天（周四）
            if dt.weekday() != 3:
                return False
            # 前一天配置才生效（position_ratio=0.9的是前1天）
            if period.position_ratio > 0.85:
                # 找当月第三个周五
                third_friday = self._get_third_friday(dt.year, dt.month)
                if third_friday is None:
                    return False
                # 当前是周四，检查明天是否是第三个周五
                return (third_friday - dt).days == 1
            return False
        
        # 是周五，检查是否是第三个周五
        third_friday = self._get_third_friday(dt.year, dt.month)
        if third_friday is None:
            return False
        
        is_expiry_day = dt.date() == third_friday.date()
        # position_ratio<=0.85的是交割日当天(0.8)
        if period.position_ratio <= 0.85:
            return is_expiry_day
        # position_ratio>0.85的是前1天(0.9)，但前1天已在上面处理
        return False
    
    @staticmethod
    def _get_third_friday(year: int, month: int) -> Optional[datetime]:
        """获取指定月份的第三个周五"""
        d = datetime(year, month, 1)
        fridays = []
        while d.month == month:
            if d.weekday() == 4:
                fridays.append(d)
            d += timedelta(days=1)
        return fridays[2] if len(fridays) >= 3 else None
    
    @staticmethod
    def _is_option_expiry(dt: datetime) -> bool:
        """判断是否为ETF期权交割日（每月第四个周三）
        
        上交所/深交所规定：ETF期权交割日为每月第四个周三
        """
        if dt.weekday() != 2:  # 不是周三
            return False
        # 计算是本月第几个周三
        d = datetime(dt.year, dt.month, 1)
        wed_count = 0
        while d <= dt:
            if d.weekday() == 2:
                wed_count += 1
            d += timedelta(days=1)
        return wed_count == 4
    
    @staticmethod
    def _is_earnings_period(dt: datetime) -> bool:
        """判断是否为财报密集披露期
        
        A股法定披露时间窗口：
        - 年报预告：1月31日前（截止日前3天=1/29-1/31）
        - 年报+一季报：4月30日前（截止日前3天=4/28-4/30）
        - 中报预告：7月15日前（截止日前3天=7/13-7/15）
        - 三季报：10月31日前（截止日前3天=10/29-10/31）
        """
        m, d = dt.month, dt.day
        # 1月底（年报预告截止）
        if m == 1 and d >= 29:
            return True
        # 4月底（年报+一季报截止）
        if m == 4 and d >= 28:
            return True
        # 7月中（中报预告截止7/15）
        if m == 7 and 13 <= d <= 15:
            return True
        # 10月底（三季报截止）
        if m == 10 and d >= 29:
            return True
        return False
    
    def _is_month_end(self, dt: datetime, n_days: int = 3) -> bool:
        """
        判断是否为月末最后N个自然日（用自然日近似交易日）
        
        【P0-D修复：增加注释说明这是自然日近似，非精确交易日】
        精确方案需要传入交易日历，但当前回测中special_period_filter是同步调用，
        无法访问MongoDB交易日历。自然日近似在大多数情况下误差≤2天，可接受。
        
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
        判断是否为季末最后N个自然日
        
        【P0-D修复：增加注释说明这是自然日近似】
        
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
        判断是否为年末最后N个自然日
        
        【P0-D修复：增加注释说明这是自然日近似】
        
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
