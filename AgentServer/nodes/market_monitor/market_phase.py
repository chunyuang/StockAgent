"""
MarketPhase — 市场时间阶段分类

从scanner.py提取的独立模块，供scanner、scan_loop_runner、risk_loop_runner等共用。
"""

from datetime import datetime


class MarketPhase:
    """市场时间阶段分类【v2.9.21, v2.9.67提取到独立模块, v2.9.70增加尾盘子阶段】

    统一_scan_loop和_risk_loop_sync的时间门控逻辑,
    消除散布在两个方法中的魔术字符串比较。
    """
    WEEKEND = "weekend"          # 周末(调试模式)
    DEEP_NIGHT = "deep_night"    # 23:00-08:00 极低频
    PREMARKET = "premarket"      # 09:00-09:25 竞价前
    AUCTION = "auction"          # 09:25-09:30 竞价
    MORNING = "morning"          # 09:30-11:30 早盘
    LUNCH = "lunch"              # 11:30-13:00 午休
    AFTERNOON = "afternoon"      # 13:00-14:30 午盘
    LATE_TRADING = "late_trading" # 14:30-15:00 尾盘(禁止新开仓)
    AFTER_CLOSE = "after_close"  # 15:05+ 收盘结算
    OFF_HOURS = "off_hours"      # 其他非交易时间

    # 交易时段集合(含早盘/午休/午盘/尾盘)
    TRADING_PHASES = {MORNING, LUNCH, AFTERNOON, LATE_TRADING}
    # 可开仓时段(尾盘禁止新开仓)
    OPEN_ALLOWED_PHASES = {MORNING, AFTERNOON}
    # 活跃交易(不含午休)
    ACTIVE_PHASES = {AUCTION, MORNING, AFTERNOON, LATE_TRADING}

    @staticmethod
    def classify() -> str:
        """分类当前时间阶段(零副作用, 可随时调用)"""
        now = datetime.now()
        ct = now.strftime("%H:%M")
        if now.weekday() >= 5:
            return MarketPhase.WEEKEND
        if now.hour >= 23 or now.hour < 8:
            return MarketPhase.DEEP_NIGHT
        if "09:00" <= ct < "09:25":
            return MarketPhase.PREMARKET
        if "09:25" <= ct < "09:30":
            return MarketPhase.AUCTION
        if "09:30" <= ct < "11:30":
            return MarketPhase.MORNING
        if "11:30" <= ct < "13:00":
            return MarketPhase.LUNCH
        if "13:00" <= ct < "14:30":
            return MarketPhase.AFTERNOON
        if "14:30" <= ct <= "15:00":
            return MarketPhase.LATE_TRADING
        if ct >= "15:05":
            return MarketPhase.AFTER_CLOSE
        return MarketPhase.OFF_HOURS

    @staticmethod
    def is_trading_active(phase: str = None) -> bool:
        """当前是否处于交易活跃时段(竞价+早盘/午盘/尾盘,不含午休)【v2.9.39,v2.9.70更新】

        用于风控线程等需要快速判断是否应执行检查的场景。
        Args:
            phase: 传入阶段(省略则自动classify)
        """
        p = phase or MarketPhase.classify()
        return p in MarketPhase.ACTIVE_PHASES

    @staticmethod
    def is_open_allowed(phase: str = None) -> bool:
        """当前是否允许新开仓(尾盘禁止新开仓)【v2.9.70新增】

        早盘+午盘允许开仓, 尾盘和午休禁止新开仓。
        Args:
            phase: 传入阶段(省略则自动classify)
        """
        p = phase or MarketPhase.classify()
        return p in MarketPhase.OPEN_ALLOWED_PHASES

    @staticmethod
    def is_in_trading(phase: str = None) -> bool:
        """当前是否在交易时段(09:30-15:00,含早盘/午休/午盘/尾盘)【v2.9.70新增】

        替代旧的 phase == TRADING 判断,兼容新的4阶段拆分。
        Args:
            phase: 传入阶段(省略则自动classify)
        """
        p = phase or MarketPhase.classify()
        return p in MarketPhase.TRADING_PHASES
