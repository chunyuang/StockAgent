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

    # ==================== Phase4.3: 健康度评分 ====================
    # ==================== v2.9.24: 运行时诊断提取 ====================

    @staticmethod
    def diagnose(scanner) -> Dict[str, Any]:
        """运行时诊断摘要(关键健康指标+可操作建议)【v2.9.23→v2.9.24提取】
        
        与get_status的区别:
        - get_status: 完整状态快照(包含所有细节)
        - diagnose: 关键指标+异常检测+修复建议(前端告警用)
        
        Args:
            scanner: MarketScanner实例
        """
        issues: list = []
        now = time.time()
        
        # 1. 风控线程存活检查
        if scanner._risk_running and scanner._risk_thread and not scanner._risk_thread.is_alive():
            issues.append({
                "level": "critical",
                "area": "risk_thread",
                "message": "风控线程已退出",
                "restarts": scanner._risk_thread_restarts,
                "action": "风控线程将自动重启,如持续退出请检查日志",
            })
        
        # 2. 行情缓存过期
        cache_age = now - (scanner._last_realtime_update_ts or 0)
        if scanner._is_running and cache_age > 120:
            issues.append({
                "level": "warning",
                "area": "quote_cache",
                "message": f"行情缓存{cache_age:.0f}秒未更新",
                "action": "检查行情源(量脉/东财)连接状态",
            })
        
        # 3. scan_loop连续异常
        error_count = getattr(scanner, '_scan_loop_error_count', 0)
        if error_count > 0:
            issues.append({
                "level": "warning" if error_count < 3 else "critical",
                "area": "scan_loop",
                "message": f"扫描循环连续{error_count}次异常",
                "action": "3次以内自动恢复,超过3次scanner将停止",
            })
        
        # 4. pending_sells积压
        pending_count = len(scanner._pending_sells)
        if pending_count > 5:
            issues.append({
                "level": "warning",
                "area": "pending_sells",
                "message": f"{pending_count}个挂起卖出待执行",
                "action": "检查是否多票跌停或执行超时",
            })
        
        # 5. circuit_breaker触发
        if scanner._circuit_breaker.get("trading_paused"):
            issues.append({
                "level": "critical",
                "area": "circuit_breaker",
                "message": f"熔断器已触发: {scanner._circuit_breaker.get('pause_reason', '未知')}",
                "action": "可调用reset_circuit_breaker()重置",
            })
        
        # 6. 风控检查超时
        last_risk = scanner._last_risk_check_ts
        if scanner._is_running and last_risk and (now - last_risk) > 10:
            issues.append({
                "level": "warning",
                "area": "risk_check",
                "message": f"风控检查{(now - last_risk):.0f}秒未执行",
                "action": "检查风控线程是否正常运行",
            })
        
        return {
            "healthy": len([i for i in issues if i["level"] == "critical"]) == 0,
            "issues": issues,
            "summary": {
                "running": scanner._is_running,
                "positions": len(scanner._broker.get_positions()) if scanner._broker else 0,
                "active_signals": len(scanner._active_signals),
                "cache_age_sec": round(cache_age, 1),
                "pending_sells": pending_count,
                "risk_thread_alive": scanner._risk_thread.is_alive() if scanner._risk_thread else False,
                "scan_errors": error_count,
                "trading_paused": scanner._circuit_breaker.get("trading_paused", False),
            },
        }

    @staticmethod
    def build_account_info(scanner) -> Dict[str, Any]:
        """构建账户信息(兼容掘金+模拟broker)【v2.9.27:从scanner提取】"""
        default = {"total_assets": 0, "available_cash": 0, "market_value": 0, "total_profit": 0}
        if scanner._trade_mode == scanner.MODE_GM and scanner._gm_broker:
            gm_acct = scanner._gm_broker.get_account()
            return {
                "total_assets": gm_acct.get("total_assets", 0),
                "available_cash": gm_acct.get("available_cash", 0),
                "market_value": gm_acct.get("market_value", 0),
                "total_profit": 0,
            }
        elif scanner._broker:
            acct = scanner._broker.get_account()
            return {
                "total_assets": round(acct.total_assets, 2),
                "available_cash": round(acct.available_cash, 2),
                "market_value": round(acct.market_value, 2),
                "total_profit": round(acct.total_profit, 2),
            }
        return default

    @staticmethod
    def compute_health_score(scanner) -> Dict[str, Any]:
        """Scanner健康度评分(绿/黄/红)

        维度:
        - scan_lag: 全量扫描延迟(上次到现在)
        - risk_check_lag: 风控检查延迟
        - quote_staleness: 行情数据陈旧度
        - warnings: 告警列表

        Args:
            scanner: MarketScanner实例
        """
        now = time.time()
        warnings = []

        # 1. 扫描延迟
        scan_lag = (now - scanner._last_scan_ts) if scanner._last_scan_ts > 0 else 999
        if scan_lag > 600:  # 10分钟没扫描
            warnings.append(f"扫描延迟{scan_lag:.0f}秒")

        # 2. 风控检查延迟
        risk_lag = (now - scanner._last_risk_check_ts) if scanner._last_risk_check_ts > 0 else 999
        if risk_lag > 10:  # 10秒没做风控检查
            warnings.append(f"风控延迟{risk_lag:.0f}秒")

        # 3. 行情陈旧度
        quote_staleness = scanner._quote_manager.get_staleness() if scanner._quote_manager else 999.0
        if quote_staleness > 60:  # 行情超过1分钟没更新
            warnings.append(f"行情陈旧{quote_staleness:.0f}秒")

        # 4. 行情降级
        if scanner._quote_manager and scanner._quote_manager.degrade_level > 0:
            warnings.append(f"行情降级level={scanner._quote_manager.degrade_level}")

        # 5. 跌停挂起
        if scanner._state_lock is None:
            pending_count = len(scanner._pending_sells)
        else:
            with scanner._state_lock:
                pending_count = len(scanner._pending_sells)
        if pending_count > 0:
            warnings.append(f"跌停挂起{pending_count}只")

        # 6. 熔断器
        if hasattr(scanner, '_circuit_breaker') and scanner._circuit_breaker.get('trading_paused'):
            warnings.append("熔断器已触发")

        # 7. EventBus异常率(v2.8)
        if hasattr(scanner, '_event_bus') and scanner._event_bus:
            stats = scanner._event_bus.get_stats()
            total_errors = sum(s.get('errors', 0) for s in stats.values())
            total_handled = sum(s.get('handled', 0) for s in stats.values())
            if total_errors > 0 and total_handled > 0:
                error_rate = total_errors / (total_handled + total_errors)
                if error_rate > 0.1:  # >10%错误率
                    warnings.append(f"EventBus异常率{error_rate:.0%}({total_errors}/{total_handled+total_errors})")

        # 8. 【v2.9.5:风控线程存活状态】
        risk_thread_alive = (
            hasattr(scanner, '_risk_thread') and scanner._risk_thread is not None
            and scanner._risk_thread.is_alive()
        )
        if not risk_thread_alive and getattr(scanner, '_risk_running', False):
            warnings.append("风控线程已停止")

        # 健康判定
        is_healthy = (
            scan_lag < 360 and      # 6分钟内有扫描
            risk_lag < 5 and         # 5秒内有风控检查
            quote_staleness < 30 and # 行情30秒内更新
            risk_thread_alive and    # 【v2.9.5:风控线程存活】
            len(warnings) == 0
        )
        is_warning = not is_healthy and (
            scan_lag < 600 and      # 10分钟内
            risk_lag < 30 and       # 30秒内
            quote_staleness < 120 and # 2分钟内
            risk_thread_alive       # 风控线程至少还活着
        )

        if is_healthy:
            status = "green"
        elif is_warning:
            status = "yellow"
        else:
            status = "red"

        return {
            "status": status,          # green/yellow/red
            "is_healthy": is_healthy,
            "scan_lag_seconds": round(scan_lag, 1),
            "risk_check_lag_seconds": round(risk_lag, 1),
            "quote_staleness_seconds": round(quote_staleness, 1),
            "risk_thread_alive": risk_thread_alive,           # 【v2.9.5】
            "risk_thread_restarts": getattr(scanner, '_risk_thread_restarts', 0),  # 【v2.9.5】
            "warnings": warnings,
            "event_bus_stats": scanner._event_bus.get_stats() if hasattr(scanner, '_event_bus') and scanner._event_bus else {},
        }

    @staticmethod
    def format_slow_steps(steps: list) -> str:
        """格式化扫描慢步骤日志【v2.9.28:从scan_once提取】
        
        Args:
            steps: [(label, ms), ...] 分步耗时列表
        Returns:
            慢步骤日志字符串, 无慢步骤返回空字符串
        """
        slow_marks = []
        for label, ms in steps:
            if ms > 1000:
                slow_marks.append(f"\U0001f534{label}={ms:.0f}ms")
            elif ms > 100:
                slow_marks.append(f"\u26a0\ufe0f{label}={ms:.0f}ms")
        return f" | 慢步骤: {', '.join(slow_marks)}" if slow_marks else ""
