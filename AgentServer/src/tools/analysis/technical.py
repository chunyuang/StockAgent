"""
技术分析工具

计算常用技术指标：MA、MACD、RSI、KDJ 等。
"""

import logging
from typing import List, Dict
from src.tools.registry import tool

logger = logging.getLogger(__name__)


def _calculate_ma(closes: List[float], period: int) -> List[float]:
    """计算移动平均线"""
    result = []
    for i in range(len(closes)):
        if i < period - 1:
            result.append(None)
        else:
            avg = sum(closes[i - period + 1:i + 1]) / period
            result.append(round(avg, 2))
    return result


def _calculate_ema(closes: List[float], period: int) -> List[float]:
    """计算指数移动平均"""
    result = []
    multiplier = 2 / (period + 1)
    
    for i, close in enumerate(closes):
        if i == 0:
            result.append(close)
        else:
            ema = (close - result[-1]) * multiplier + result[-1]
            result.append(round(ema, 2))
    
    return result


def _calculate_macd(closes: List[float]) -> Dict[str, List[float]]:
    """计算 MACD 指标"""
    ema12 = _calculate_ema(closes, 12)
    ema26 = _calculate_ema(closes, 26)
    
    # DIF = EMA12 - EMA26
    dif = [round(e12 - e26, 2) if e12 and e26 else None 
           for e12, e26 in zip(ema12, ema26)]
    
    # DEA = DIF的9日EMA
    dif_valid = [d for d in dif if d is not None]
    dea_values = _calculate_ema(dif_valid, 9) if dif_valid else []
    
    dea = [None] * (len(dif) - len(dea_values)) + dea_values
    
    # MACD柱 = (DIF - DEA) * 2
    macd = [round((d - e) * 2, 2) if d is not None and e is not None else None
            for d, e in zip(dif, dea)]
    
    return {"dif": dif, "dea": dea, "macd": macd}


def _calculate_rsi(closes: List[float], period: int = 14) -> List[float]:
    """计算 RSI 指标"""
    if len(closes) < period + 1:
        return [None] * len(closes)
    
    result = [None] * period
    
    gains = []
    losses = []
    
    for i in range(1, len(closes)):
        change = closes[i] - closes[i - 1]
        if change > 0:
            gains.append(change)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(change))
        
        if i >= period:
            avg_gain = sum(gains[-period:]) / period
            avg_loss = sum(losses[-period:]) / period
            
            if avg_loss == 0:
                rsi = 100
            else:
                rs = avg_gain / avg_loss
                rsi = 100 - (100 / (1 + rs))
            
            result.append(round(rsi, 2))
    
    return result


@tool(
    name="calculate_technical_indicators",
    description="计算股票技术指标，包括MA、MACD、RSI等",
    category="analysis",
    tags=["technical", "indicator"],
)
async def calculate_technical_indicators(
    stock_code: str,
    indicators: List[str] = None,
) -> dict:
    """
    计算技术指标
    
    Args:
        stock_code: 股票代码
        indicators: 要计算的指标列表 (默认全部)，可选: ma, macd, rsi, kdj
    
    Returns:
        技术指标数据
    """
    from core.managers import mongo_manager
    
    if indicators is None:
        indicators = ["ma", "macd", "rsi"]
    
    try:
        # 获取K线数据
        records = await mongo_manager.find_many(
            "stock_daily_ak_full",
            {"ts_code": stock_code},
            sort=[("trade_date", -1)],
            limit=120,  # 足够计算各种指标
        )
        
        if not records or len(records) < 30:
            return {"error": "K线数据不足，无法计算指标"}
        
        # 按日期正序
        records = list(reversed(records))
        
        closes = [r["close"] for r in records]
        dates = [r["trade_date"] for r in records]
        
        result = {
            "code": stock_code,
            "count": len(records),
            "latest_date": dates[-1],
            "latest_close": closes[-1],
            "indicators": {},
        }
        
        # 计算 MA
        if "ma" in indicators:
            result["indicators"]["ma"] = {
                "ma5": _calculate_ma(closes, 5)[-1],
                "ma10": _calculate_ma(closes, 10)[-1],
                "ma20": _calculate_ma(closes, 20)[-1],
                "ma60": _calculate_ma(closes, 60)[-1] if len(closes) >= 60 else None,
            }
            
            # 判断均线多头/空头
            ma5 = result["indicators"]["ma"]["ma5"]
            ma10 = result["indicators"]["ma"]["ma10"]
            ma20 = result["indicators"]["ma"]["ma20"]
            
            if ma5 and ma10 and ma20:
                if ma5 > ma10 > ma20:
                    result["indicators"]["ma"]["status"] = "多头排列"
                elif ma5 < ma10 < ma20:
                    result["indicators"]["ma"]["status"] = "空头排列"
                else:
                    result["indicators"]["ma"]["status"] = "均线交织"
        
        # 计算 MACD
        if "macd" in indicators:
            macd_data = _calculate_macd(closes)
            result["indicators"]["macd"] = {
                "dif": macd_data["dif"][-1],
                "dea": macd_data["dea"][-1],
                "macd": macd_data["macd"][-1],
            }
            
            # 判断 MACD 状态
            dif = macd_data["dif"][-1]
            dea = macd_data["dea"][-1]
            
            if dif and dea:
                if dif > 0 and dif > dea:
                    result["indicators"]["macd"]["status"] = "金叉向上"
                elif dif < 0 and dif < dea:
                    result["indicators"]["macd"]["status"] = "死叉向下"
                elif dif > dea:
                    result["indicators"]["macd"]["status"] = "多头"
                else:
                    result["indicators"]["macd"]["status"] = "空头"
        
        # 计算 RSI
        if "rsi" in indicators:
            rsi = _calculate_rsi(closes, 14)
            result["indicators"]["rsi"] = {
                "rsi14": rsi[-1],
            }
            
            if rsi[-1]:
                if rsi[-1] >= 80:
                    result["indicators"]["rsi"]["status"] = "超买"
                elif rsi[-1] <= 20:
                    result["indicators"]["rsi"]["status"] = "超卖"
                elif rsi[-1] >= 60:
                    result["indicators"]["rsi"]["status"] = "偏强"
                elif rsi[-1] <= 40:
                    result["indicators"]["rsi"]["status"] = "偏弱"
                else:
                    result["indicators"]["rsi"]["status"] = "中性"
        
        return result
        
    except Exception as e:
        logger.error(f"Technical analysis error: {e}")
        return {"error": str(e)}


@tool(
    name="analyze_trend",
    description="分析股票价格趋势和支撑压力位",
    category="analysis",
    tags=["technical", "trend"],
)
async def analyze_trend(stock_code: str, days: int = 60) -> dict:
    """
    分析价格趋势
    
    Args:
        stock_code: 股票代码
        days: 分析周期 (默认60天)
    
    Returns:
        趋势分析结果
    """
    from core.managers import mongo_manager
    
    try:
        records = await mongo_manager.find_many(
            "stock_daily_ak_full",
            {"ts_code": stock_code},
            sort=[("trade_date", -1)],
            limit=days,
        )
        
        if not records or len(records) < 20:
            return {"error": "数据不足"}
        
        records = list(reversed(records))
        
        closes = [r["close"] for r in records]
        highs = [r["high"] for r in records]
        lows = [r["low"] for r in records]
        
        # 计算关键价位
        current_price = closes[-1]
        high_price = max(highs)
        low_price = min(lows)
        avg_price = sum(closes) / len(closes)
        
        # 计算价格位置
        price_range = high_price - low_price
        if price_range > 0:
            position = (current_price - low_price) / price_range * 100
        else:
            position = 50
        
        # 计算趋势（简单：比较前后半段均价）
        mid = len(closes) // 2
        first_half_avg = sum(closes[:mid]) / mid
        second_half_avg = sum(closes[mid:]) / (len(closes) - mid)
        
        if second_half_avg > first_half_avg * 1.05:
            trend = "上涨"
        elif second_half_avg < first_half_avg * 0.95:
            trend = "下跌"
        else:
            trend = "震荡"
        
        # 计算涨跌幅
        change_pct = (closes[-1] / closes[0] - 1) * 100
        
        # 计算波动率
        returns = [(closes[i] / closes[i-1] - 1) for i in range(1, len(closes))]
        volatility = (sum([r**2 for r in returns]) / len(returns)) ** 0.5 * 100
        
        return {
            "code": stock_code,
            "period": f"{days}天",
            "current_price": current_price,
            "trend": trend,
            "change_pct": round(change_pct, 2),
            "price_position": f"{position:.1f}%",
            "volatility": round(volatility, 2),
            "support": round(low_price, 2),
            "resistance": round(high_price, 2),
            "avg_price": round(avg_price, 2),
        }
        
    except Exception as e:
        logger.error(f"Trend analysis error: {e}")
        return {"error": str(e)}
