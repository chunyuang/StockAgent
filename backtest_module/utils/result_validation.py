#!/usr/bin/env python3
"""
回测结果合理性校验
异常结果直接告警，避免逻辑错误导致的荒谬结果
"""
import logging
from typing import Dict

logger = logging.getLogger(__name__)

def validate_backtest_result(result: Dict, strategy_name: str) -> bool:
    """
    校验回测结果合理性，返回True表示正常，否则抛出异常
    """
    logger.info(f"📊 校验[{strategy_name}]回测结果合理性...")
    
    total_return = result.get('total_return_pct', 0)
    signals = result.get('total_signals', 0)
    win_rate = result.get('win_rate', 0)
    max_drawdown = result.get('max_drawdown_pct', 0)
    trade_days = result.get('trade_days', 0)
    
    # 1. 信号数校验：3个月回测信号数不能太少或太多
    if trade_days > 30 and signals < 5:
        logger.warning(f"⚠️  [{strategy_name}]信号过少: {signals}个，可能过滤条件过严或逻辑错误")
    if signals > trade_days * 10:  # 每天最多10个信号
        raise ValueError(f"❌ [{strategy_name}]信号过多: {signals}个，远超每日10个的合理范围，可能逻辑错误")
    
    # 2. 收益率校验：避免荒谬的收益率
    if total_return > 1000:  # 3个月收益率超过1000%肯定有问题
        raise ValueError(f"❌ [{strategy_name}]收益率异常: {total_return:.2f}%，超过1000%，可能逻辑错误")
    if total_return < -90:  # 3个月亏损超过90%肯定有问题
        raise ValueError(f"❌ [{strategy_name}]收益率异常: {total_return:.2f}%，亏损超过90%，可能逻辑错误")
    
    # 3. 胜率校验：0%或100%肯定有问题
    if win_rate == 0 and signals > 10:
        logger.warning(f"⚠️  [{strategy_name}]胜率为0%，可能逻辑错误或策略失效")
    if win_rate == 100 and signals > 10:
        raise ValueError(f"❌ [{strategy_name}]胜率为100%，肯定逻辑错误")
    
    # 4. 最大回撤校验：超过90%肯定有问题
    if max_drawdown > 90:
        raise ValueError(f"❌ [{strategy_name}]最大回撤异常: {max_drawdown:.2f}%，超过90%，可能风控失效")
    
    logger.info(f"✅ [{strategy_name}]结果校验通过")
    return True

def validate_all_results(results: Dict) -> bool:
    """校验所有策略结果"""
    logger.info("="*60)
    logger.info("🔍 执行回测结果合理性校验...")
    for strategy_name, result in results.items():
        validate_backtest_result(result, strategy_name)
    logger.info("✅ 所有策略结果校验通过！")
    logger.info("="*60)
    return True
