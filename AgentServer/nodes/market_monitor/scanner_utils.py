"""
ScannerUtils — Scanner工具方法集合

从MarketScanner拆分出来(Phase3.1)。
负责:
- 安全round
- Redis事件推送(Stream+Pub/Sub)
- Position/Signal对象序列化
- 关键因子提取
- 交易摘要报告生成
"""

import json
import logging
import math
import time
from datetime import datetime
from typing import Dict, List, Any

from nodes.market_monitor.scanner import ScanSignal

logger = logging.getLogger("scanner_utils")


class ScannerUtils:
    """
    Scanner工具方法集合(全部静态/无状态)
    
    用法:
        ScannerUtils.safe_round(v, 2)
        await ScannerUtils.publish_scanner_event("signal", {...})
        dict_repr = ScannerUtils.position_to_dict(pos, risk_getter)
    """
    
    @staticmethod
    def safe_round(v, digits=2):
        """安全round, 处理None/NaN/inf"""
        if v is None:
            return None
        try:
            if math.isnan(v) or math.isinf(v):
                return None
            return round(v, digits)
        except (TypeError, ValueError):
            return None
    
    @staticmethod
    async def publish_scanner_event(event_type: str, data: Dict):
        """推送scanner事件到Redis
        
        【Phase2.1:Signal/Position用Redis Stream(不可丢), 其他用Pub/Sub(允许丢)】
        - scanner:signal → Redis Stream(maxlen=1000)
        - scanner:position → Redis Stream(maxlen=5000)
        - scanner:timeline → Redis Pub/Sub(允许丢,1秒后还有下一帧)
        - scanner:status → Redis Pub/Sub(允许丢)
        """
        try:
            from core.managers import redis_manager
            if not redis_manager._client:
                return
            
            data["timestamp"] = datetime.now().strftime("%H:%M:%S")
            payload = json.dumps(data, ensure_ascii=False, default=str)
            
            if event_type in ("signal", "position"):
                stream_key = f"scanner:{event_type}"
                await redis_manager._client.xadd(
                    stream_key,
                    {"data": payload},
                    maxlen=5000 if event_type == "position" else 1000
                )
            else:
                channel = f"scanner:{event_type}"
                await redis_manager._client.publish(channel, payload)
        except Exception as e:
            logger.debug(f"[PUSH] Redis推送失败(可忽略): {e}")
    
    @staticmethod
    def position_to_dict(p, risk_getter=None) -> Dict:
        """Position对象转dict
        
        Args:
            p: Position对象
            risk_getter: callable(strategy_key) → risk_dict
        """
        risk = risk_getter(p.strategy) if risk_getter else {}
        sl_pct = risk.get("stop_loss_pct", 0.03) * 100
        tp_pct = risk.get("take_profit_pct", 0.07) * 100
        
        # 止损止盈价
        sl_price = round(p.avg_cost * (1 - risk.get("stop_loss_pct", 0.03)), 2) if risk else None
        tp_price = round(p.avg_cost * (1 + risk.get("take_profit_pct", 0.07)), 2) if risk else None
        mv = round(p.current_price * p.total_qty, 2)
        profit_amt = round((p.current_price - p.avg_cost) * p.total_qty, 2)
        
        strategy_cn = {
            "halfway_chase": "半路追涨", "first_limit_up": "首板打板",
            "dragon_head": "龙头低吸", "limit_down_qiao": "跌停翘板",
            "limit_up_open": "涨停开板",
            "anomaly_surge": "急速拉升", "anomaly_broken": "涨停炸板", "anomaly_strong": "强势涨停",
            "manual": "手动操作",
        }.get(p.strategy, p.strategy)
        
        return {
            "ts_code": p.ts_code, "stock_name": p.stock_name,
            "strategy": p.strategy, "strategy_name": strategy_cn, "shares": p.total_qty,
            "available_qty": p.available_qty,
            "cost_price": round(p.avg_cost, 2),
            "current_price": round(p.current_price, 2),
            "profit_pct": round(p.profit_pct, 2),
            "profit_amount": profit_amt,
            "market_value": mv,
            "today_buy": p.today_buy_qty,
            "stop_loss_pct": round(sl_pct, 1),
            "take_profit_pct": round(tp_pct, 1),
            "stop_loss_price": sl_price,
            "take_profit_price": tp_price,
            "distance_to_stop": round(p.profit_pct + sl_pct, 1),
        }
    
    @staticmethod
    def signal_to_dict(s: ScanSignal, signal_expire_seconds: int = 300) -> Dict:
        """ScanSignal对象转dict"""
        d = {
            "ts_code": s.ts_code, "stock_name": s.stock_name,
            "strategy": s.strategy, "strategy_name": s.strategy_name,
            "signal_type": s.signal_type, "price": ScannerUtils.safe_round(s.price),
            "pct_chg": ScannerUtils.safe_round(s.pct_chg),
            "volume_ratio": ScannerUtils.safe_round(s.volume_ratio),
            "turnover_rate": ScannerUtils.safe_round(s.turnover_rate),
            "is_limit_up": s.is_limit_up,
            "limit_up_count": s.limit_up_count,
            "confidence": s.confidence, "reason": s.reason,
            "scan_time": s.scan_time, "factors": s.factors,
            "signal_status": s.signal_status,
            "created_at": s.created_at,
            "expire_remaining": max(0, signal_expire_seconds - (time.time() - s.created_at)) if s.created_at > 0 else -1,
            "key_factors": ScannerUtils.extract_key_factors(s),
        }
        if s.decision_detail:
            d["decision_detail"] = s.decision_detail
        if s.layer_trace:
            d["layer_trace"] = s.layer_trace
        return d
    
    @staticmethod
    def extract_key_factors(s: ScanSignal) -> Dict[str, Any]:
        """提取信号的关键因子摘要(前端卡片展示用)"""
        factors = s.factors or {}
        key = {}
        if factors.get("circ_mv"):
            mv = factors["circ_mv"]
            key["circ_mv"] = f"{mv/10000:.0f}亿" if mv >= 10000 else f"{mv/100:.0f}万"
        if factors.get("pe") and factors["pe"] > 0:
            key["pe"] = f"PE{factors['pe']:.0f}"
        if factors.get("pb") and factors["pb"] > 0:
            key["pb"] = f"PB{factors['pb']:.1f}"
        if s.limit_up_count > 0:
            key["limit_count"] = f"{s.limit_up_count}连板"
        if factors.get("fd_amount"):
            key["fd_amount"] = f"封单{factors['fd_amount']/1000:.0f}万"
        if s.volume_ratio > 0:
            key["volume_ratio"] = f"量比{s.volume_ratio:.1f}"
        if s.turnover_rate > 0:
            key["turnover_rate"] = f"换手{s.turnover_rate:.1f}%"
        return key
    
    @staticmethod
    def generate_summary_report(scanner) -> Dict[str, Any]:
        """生成完整交易摘要报告(供API调用)
        
        Args:
            scanner: MarketScanner实例(读取broker/stats/timeline等)
        """
        if not scanner._broker:
            return {"error": "Broker未初始化"}
        
        acct = scanner._broker.get_account()
        positions = scanner._broker.get_positions()
        
        account_summary = {
            "total_assets": round(acct.total_assets, 2),
            "available_cash": round(acct.available_cash, 2),
            "market_value": round(acct.market_value, 2),
            "total_profit": round(acct.total_profit, 2),
            "position_ratio": round(acct.market_value / max(acct.total_assets, 1) * 100, 1),
            "position_count": len(positions),
        }
        
        position_details = []
        for p in positions:
            risk = scanner._get_strategy_risk(p.strategy)
            sl_pct = risk.get("stop_loss_pct", 0.03) * 100
            tp_pct = risk.get("take_profit_pct", 0.07) * 100
            position_details.append({
                "ts_code": p.ts_code,
                "stock_name": p.stock_name,
                "strategy": p.strategy,
                "shares": p.total_qty,
                "available_qty": p.available_qty,
                "cost_price": round(p.avg_cost, 2),
                "current_price": round(p.current_price, 2),
                "profit_pct": round(p.profit_pct, 2),
                "market_value": round(p.current_price * p.total_qty, 2),
                "stop_loss_price": round(p.avg_cost * (1 - risk.get("stop_loss_pct", 0.03)), 2),
                "take_profit_price": round(p.avg_cost * (1 + risk.get("take_profit_pct", 0.07)), 2),
                "stop_loss_pct": round(sl_pct, 1),
                "take_profit_pct": round(tp_pct, 1),
                "distance_to_stop": round(p.profit_pct + sl_pct, 1),
                "is_t1_locked": p.today_buy_qty > 0,
            })
        
        today_buys = [t for t in scanner._timeline if t.get("action") == "buy"]
        today_sells = [t for t in scanner._timeline if t.get("action") == "sell"]
        profitable_sells = [t for t in today_sells if t.get("profit_pct", 0) > 0]
        losing_sells = [t for t in today_sells if t.get("profit_pct", 0) < 0]
        
        trade_stats = {
            "total_trades": len(today_buys) + len(today_sells),
            "buys": len(today_buys),
            "sells": len(today_sells),
            "win_trades": len(profitable_sells),
            "loss_trades": len(losing_sells),
            "win_rate": round(len(profitable_sells) / max(len(today_sells), 1) * 100, 1),
            "avg_profit_pct": round(
                sum(t.get("profit_pct", 0) for t in profitable_sells) / max(len(profitable_sells), 1), 2
            ) if profitable_sells else 0,
            "avg_loss_pct": round(
                sum(t.get("profit_pct", 0) for t in losing_sells) / max(len(losing_sells), 1), 2
            ) if losing_sells else 0,
        }
        
        strategy_performance = {}
        for t in scanner._timeline:
            strat = t.get("strategy", "unknown")
            if strat not in strategy_performance:
                strategy_performance[strat] = {"trades": 0, "wins": 0, "total_pnl": 0}
            strategy_performance[strat]["trades"] += 1
            if t.get("action") == "sell":
                pnl = t.get("profit_pct", 0)
                strategy_performance[strat]["total_pnl"] += pnl
                if pnl > 0:
                    strategy_performance[strat]["wins"] += 1
        
        risk_status = {
            "circuit_breaker_active": scanner._circuit_breaker.get("trading_paused", False),
            "circuit_breaker_reason": scanner._circuit_breaker.get("pause_reason", ""),
            "consecutive_losses": scanner._circuit_breaker.get("consecutive_losses", 0),
            "today_trades": scanner._circuit_breaker.get("today_trades", 0),
            "today_losses": scanner._circuit_breaker.get("today_losses", 0),
            "dry_run": scanner._dry_run,
        }
        
        signal_stats = {
            "total": len(scanner._active_signals),
            "new": len([s for s in scanner._active_signals if s.signal_status == "new"]),
            "executed": len([s for s in scanner._active_signals if s.signal_status == "executed"]),
            "skipped": len([s for s in scanner._active_signals if s.signal_status == "skipped"]),
            "expired": len([s for s in scanner._active_signals if s.signal_status == "expired"]),
            "filtered": len([s for s in scanner._active_signals if s.signal_status == "filtered"]),
        }
        
        return {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "account": account_summary,
            "positions": position_details,
            "trade_stats": trade_stats,
            "strategy_performance": strategy_performance,
            "risk_status": risk_status,
            "signal_stats": signal_stats,
            "scanner_stats": dict(scanner._stats),
            "sentiment": getattr(scanner, '_current_sentiment', {}),
            "position_ratio": getattr(scanner, '_current_position_ratio', None),
        }
