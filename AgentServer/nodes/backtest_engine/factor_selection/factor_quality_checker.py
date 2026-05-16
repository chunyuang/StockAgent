"""
因子数据质量检查器

在回测前检查因子数据质量，防止因数据缺失导致回测结果异常。
"""

import math
from typing import Dict, List, Set, Tuple
from dataclasses import dataclass
from enum import Enum


class FactorQualityLevel(Enum):
    """因子质量等级"""
    GOOD = "good"  # 数据完整
    WARNING = "warning"  # 部分缺失
    ERROR = "error"  # 严重缺失


@dataclass
class FactorQualityReport:
    """因子质量报告"""
    level: FactorQualityLevel
    total_factors: int
    missing_factors: List[str]
    empty_factors: List[str]
    low_quality_factors: List[str]  # 缺失率>30%
    message: str


class FactorQualityChecker:
    """因子数据质量检查器"""
    
    # 核心因子列表（缺失时严重影响回测结果）
    CORE_FACTORS = {
        "pct_chg",  # 涨跌幅
        "volume_ratio",  # 量比
        "turnover_rate",  # 换手率
        "circ_mv",  # 流通市值
        "opening_pct_chg",  # 竞价涨幅
    }
    
    # 策略必需因子映射
    STRATEGY_REQUIRED_FACTORS = {
        "半路追涨": {"pct_chg", "volume_ratio", "intraday_max_rise_pct", "intraday_open_rise_pct"},
        "首板打板": {"first_limit_up", "limit_up_yesterday", "opening_pct_chg", "volume_ratio", "turnover_rate", "circ_mv"},
        "涨停开板": {"limit_up_yesterday", "is_limit_up", "intraday_max_rise_pct", "volume_ratio", "turnover_rate"},
        "龙头低吸": {"circ_mv", "limit_up_count", "pullback_pct", "pullback_days", "volume_ratio"},
        "跌停翘板": {"limit_down_yesterday", "open_above_limit_down", "circ_mv", "turnover_rate"},
    }
    
    # 可用默认值的因子
    FACTOR_DEFAULTS = {
        "market_leader": 0,  # 无龙头标识
        "limit_up_open_amount": 0,  # 无开板封单数据
        "limit_up_open_count": 0,
        "hot_sector": 0,
        "limit_up_time": 0,
        "limit_up_open_duration": 0,
        "pullback_ma5": 0,
        "limit_down_open_amount": 0,
        "rise_after_limit_down": 0,
        "sentiment_score": 50,  # 中性情绪
    }
    
    def __init__(self, strict_mode: bool = False):
        """
        Args:
            strict_mode: 严格模式，缺失核心因子时抛出异常
        """
        self.strict_mode = strict_mode
    
    def check_factor_quality(
        self,
        factor_df,
        requested_factors: List[Dict],
        enabled_strategies: List[str],
        trade_date: str
    ) -> FactorQualityReport:
        """检查因子数据质量
        
        Args:
            factor_df: 因子DataFrame
            requested_factors: 请求的因子列表
            enabled_strategies: 启用的策略列表
            trade_date: 交易日期
            
        Returns:
            FactorQualityReport: 因子质量报告
        """
        if factor_df is None or len(factor_df) == 0:
            return FactorQualityReport(
                level=FactorQualityLevel.ERROR,
                total_factors=len(requested_factors),
                missing_factors=[f["name"] for f in requested_factors],
                empty_factors=[],
                low_quality_factors=[],
                message=f"交易日期 {trade_date} 无任何因子数据"
            )
        
        missing_factors = []
        empty_factors = []
        low_quality_factors = []
        
        # 检查每个因子
        for f in requested_factors:
            factor_name = f["name"]
            
            # 检查是否存在
            if factor_name not in factor_df.columns:
                missing_factors.append(factor_name)
                continue
            
            # 检查是否全为空
            col = factor_df[factor_name]
            if col.isna().all():
                empty_factors.append(factor_name)
                continue
            
            # 检查缺失率
            null_rate = col.isna().sum() / len(col)
            if null_rate > 0.3:
                low_quality_factors.append(f"{factor_name}(缺失{null_rate*100:.0f}%)")
        
        # 计算质量等级
        total = len(requested_factors)
        missing_count = len(missing_factors) + len(empty_factors)
        
        # 检查核心因子缺失
        core_missing = self.CORE_FACTORS & (set(missing_factors) | set(empty_factors))
        
        # 检查策略必需因子缺失
        strategy_missing = {}
        for strategy in enabled_strategies:
            required = self.STRATEGY_REQUIRED_FACTORS.get(strategy, set())
            missing = required & (set(missing_factors) | set(empty_factors))
            if missing:
                strategy_missing[strategy] = missing
        
        # 判断质量等级
        if core_missing or (missing_count / total > 0.3):
            level = FactorQualityLevel.ERROR
            msg = f"严重数据缺失: {len(core_missing)} 个核心因子缺失"
            if strategy_missing:
                msg += f", {len(strategy_missing)} 个策略必需因子缺失"
        elif missing_count > 0 or low_quality_factors:
            level = FactorQualityLevel.WARNING
            msg = f"部分数据缺失: {missing_count} 个因子缺失, {len(low_quality_factors)} 个质量较差"
        else:
            level = FactorQualityLevel.GOOD
            msg = "因子数据质量良好"
        
        return FactorQualityReport(
            level=level,
            total_factors=total,
            missing_factors=missing_factors,
            empty_factors=empty_factors,
            low_quality_factors=low_quality_factors,
            message=msg
        )
    
    def apply_factor_defaults(self, factor_df, missing_factors: List[str]) -> None:
        """为缺失的因子应用默认值（原地修改DataFrame）
        
        Args:
            factor_df: 因子DataFrame
            missing_factors: 缺失的因子列表
        """
        for factor_name in missing_factors:
            if factor_name in self.FACTOR_DEFAULTS:
                default_value = self.FACTOR_DEFAULTS[factor_name]
                factor_df[factor_name] = default_value
    
    def should_abort_backtest(self, report: FactorQualityReport) -> Tuple[bool, str]:
        """判断是否应该中止回测
        
        Args:
            report: 因子质量报告
            
        Returns:
            (should_abort, reason): 是否中止及原因
        """
        if report.level == FactorQualityLevel.ERROR:
            if self.strict_mode:
                return True, f"严格模式下检测到严重数据缺失: {report.message}"
            else:
                # 非严格模式下，仅当中止核心因子缺失时才中止
                core_missing = set(report.missing_factors + report.empty_factors) & self.CORE_FACTORS
                if core_missing:
                    return True, f"核心因子缺失: {', '.join(core_missing)}"
        
        return False, ""
    
    def get_quality_summary(self, report: FactorQualityReport) -> str:
        """获取质量摘要（用于日志）
        
        Args:
            report: 因子质量报告
            
        Returns:
            质量摘要字符串
        """
        lines = [
            f"📊 因子数据质量检查: {report.level.value.upper()}",
            f"   总因子数: {report.total_factors}",
        ]
        
        if report.missing_factors:
            lines.append(f"   ❌ 缺失因子({len(report.missing_factors)}): {', '.join(report.missing_factors[:10])}")
            if len(report.missing_factors) > 10:
                lines.append(f"      ... 等{len(report.missing_factors)}个")
        
        if report.empty_factors:
            lines.append(f"   ⚠️  全空因子({len(report.empty_factors)}): {', '.join(report.empty_factors[:10])}")
        
        if report.low_quality_factors:
            lines.append(f"   ⚠️  低质量因子({len(report.low_quality_factors)}): {', '.join(report.low_quality_factors[:5])}")
        
        lines.append(f"   📝 {report.message}")
        
        return "\n".join(lines)
