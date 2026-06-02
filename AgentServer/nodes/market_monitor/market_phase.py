"""
MarketPhase — 市场时间阶段分类

从scanner.py提取的独立模块，供scanner、scan_loop_runner、risk_loop_runner等共用。
"""

from datetime import datetime


class MarketPhase:
    """市场时间阶段分类【v2.9.21, v2.9.67提取到独立模块】

    统一_scan_loop和_risk_loop_sync的时间门控逻辑,
    消除散布在两个方法中的魔术字符串比较。
    """
    WEEKEND = "weekend"          # 周末(调试模式)
    DEEP_NIGHT = "deep_night"    # 23:00-08:00 极低频
    PREMARKET = "premarket"      # 09:00-09:25 竞价前
    AUCTION = "auction"          # 09:25-09:30 竞价
    TRADING = "trading"          # 09:30-15:00 交易时间
    AFTER_CLOSE = "after_close"  # 15:05+ 收盘结算
    OFF_HOURS = "off_hours"      # 其他非交易时间

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
        if "09:30" <= ct <= "15:00":
            return MarketPhase.TRADING
        if ct >= "15:05":
            return MarketPhase.AFTER_CLOSE
        return MarketPhase.OFF_HOURS

    @staticmethod
    def is_trading_active(phase: str = None) -> bool:
        """当前是否处于交易活跃时段(竞价+交易)【v2.9.39】

        用于风控线程等需要快速判断是否应执行检查的场景。
        Args:
            phase: 传入阶段(省略则自动classify)
        """
        p = phase or MarketPhase.classify()
        return p in (MarketPhase.AUCTION, MarketPhase.TRADING)
