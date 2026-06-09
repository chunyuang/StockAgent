#!/usr/bin/env python3
"""Scanner API - 复盘/归因/偏差/参数漂移"""
import asyncio
import logging
import math
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from nodes.web.api.utils import sanitize_nan as _sanitize

# 从scanner共享模块导入
from nodes.web.api.scanner_shared import (
    _get_scanner, _get_scanner_instance, _clean_mongo,
    _fill_stock_names, _safe_read_shared, logger,
    ScannerStartRequest, ManualTradeRequest, PartialSellRequest,
    StopScannerRequest, ScanOnceRequest, PauseRequest,
)

router = APIRouter(prefix="/scanner", tags=["复盘/归因/偏差/参数漂移"])

# 策略ID归一化(anomaly_surge→halfway_chase等)
try:
    from nodes.backtest_engine.strategy_defaults import normalize_strategy_id as _norm_strat
except ImportError:
    def _norm_strat(s): return s


@router.get("/backtest-compare")
async def backtest_compare(date: str = None):
    """实盘vs回测对比

    优先从MongoDB读取回测结果,fallback到backtest_result.json文件

    Args:
        date: YYYYMMDD格式, 不传则全量
    """
    try:
        from core.managers import mongo_manager

        # 1. 从MongoDB获取实盘统计(按策略)
        live_stats = {}
        if mongo_manager.is_initialized:
            from collections import defaultdict
            ls = defaultdict(lambda: {"trades":0,"wins":0,"total_pnl":0})
            sell_query = {"side":"sell","status":"filled"}
            if date:
                # 【v2.9.86修复】broker_orders.trade_date是int，不能用str
                sell_query["trade_date"] = {"$lte": int(date)}
            async for doc in mongo_manager.db["broker_orders"].find(sell_query):
                strat = _norm_strat(doc.get("strategy","unknown"))
                pct = doc.get("profit_pct",0) or 0
                ls[strat]["trades"] += 1
                if pct >= 0:
                    ls[strat]["wins"] += 1
                ls[strat]["total_pnl"] += pct
            for strat, v in ls.items():
                live_stats[strat] = {
                    "trades": v["trades"],
                    "win_rate": round(v["wins"]/max(v["trades"],1)*100, 1),
                    "total_pnl": round(v["total_pnl"], 2),
                }

        # 2. 从MongoDB回测结果读取(优先same_period)
        backtest_results = {}
        backtest_type = "none"
        if mongo_manager.is_initialized:
            # 2a. 优先查same_period(同区间回测)
            same_period_doc = await mongo_manager.db["backtest_results"].find_one(
                {"status": "completed", "type": "same_period"},
                sort=[("created_at", -1)]
            )
            if same_period_doc:
                backtest_type = "same_period"
                strategies = same_period_doc.get("params", {}).get("strategy_ids", [])
                raw_summary = same_period_doc.get("result", {}).get("summary", {})
                # 解析summary: 可能是嵌套dict(含strategy_results)或error dict
                if isinstance(raw_summary, dict) and "error" not in raw_summary:
                    # 有strategy_results时, 拆分到每个策略
                    sr = raw_summary.get("strategy_results", {})
                    cn_to_en = {"半路追涨":"halfway_chase","涨停开板":"limit_up_open","跌停翘板":"limit_down_qiao","首板打板":"first_limit_up","龙头低吸":"dragon_head"}
                    # 【V75修复】优先从strategy_defaults读取映射
                    try:
                        from nodes.backtest_engine.strategy_defaults import STRATEGY_NAME_TO_ID
                        cn_to_en = dict(STRATEGY_NAME_TO_ID)
                    except ImportError:
                        pass
                    if sr:
                        for cn_name, v in sr.items():
                            sid = cn_to_en.get(cn_name, cn_name)
                            if sid not in backtest_results:
                                backtest_results[sid] = {
                                    "total_return": v.get("total_return", 0),
                                    "win_rate": v.get("win_rate", 0),
                                    "max_drawdown": v.get("max_drawdown", 0),
                                    "sharpe": 0,
                                    "trades": v.get("total_trades", 0),
                                    "source": "same_period",
                                    "period": f"{same_period_doc.get('params',{}).get('start_date','')}~{same_period_doc.get('params',{}).get('end_date','')}",
                                }
                    else:
                        # 整体summary
                        summary = raw_summary
                        for sid in strategies:
                            if sid not in backtest_results:
                                backtest_results[sid] = {
                                    "total_return": summary.get("total_return", 0),
                                    "win_rate": summary.get("win_rate", 0),
                                    "max_drawdown": summary.get("max_drawdown", 0),
                                    "sharpe": summary.get("sharpe_ratio", 0),
                                    "trades": summary.get("total_trades", 0),
                                    "source": "same_period",
                                    "period": f"{same_period_doc.get('params',{}).get('start_date','')}~{same_period_doc.get('params',{}).get('end_date','')}",
                                }
                else:
                    # error或无数据
                    backtest_type = "same_period_failed"
                    backtest_results = {}  # fallback到文件

            # 2b. fallback: 普通回测
            if not backtest_results:
                async for doc in mongo_manager.db["backtest_results"].find(
                    {"status": "completed"},
                    {"_id": 0, "task_id": 1, "params.strategy_ids": 1, "result.summary": 1, "created_at": 1}
                ).sort("created_at", -1).limit(5):
                    strategies = doc.get("params", {}).get("strategy_ids", [])
                    summary = doc.get("result", {}).get("summary", {})
                    for sid in strategies:
                        if sid not in backtest_results:
                            backtest_results[sid] = {
                                "total_return": summary.get("total_return", 0),
                                "win_rate": summary.get("win_rate", 0),
                                "max_drawdown": summary.get("max_drawdown", 0),
                                "sharpe": summary.get("sharpe_ratio", 0),
                                "trades": summary.get("total_trades", 0),
                                "source": "mongodb",
                            }
                    backtest_type = "historical"

        # 2b. fallback: 从backtest_result.json文件读取
        logger.info(f"[BACKTEST-COMPARE] backtest_results empty: {not backtest_results}, keys: {list(backtest_results.keys())}")
        if not backtest_results:
            import os, json
            result_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "results", "backtest_result.json")
            logger.info(f"[BACKTEST-COMPARE] fallback file: {result_file} exists={os.path.exists(result_file)}")
            if os.path.exists(result_file):
                try:
                    with open(result_file, 'r') as f:
                        bt_data = json.load(f)
                    logger.info(f"[BACKTEST-COMPARE] loaded strategies: {list(bt_data.get('strategy_results',{}).keys())}")
                    cn_to_en = {"半路追涨":"halfway_chase","涨停开板":"limit_up_open","跌停翘板":"limit_down_qiao","首板打板":"first_limit_up","龙头低吸":"dragon_head"}
                    # 【V75修复】优先从strategy_defaults读取映射
                    try:
                        from nodes.backtest_engine.strategy_defaults import STRATEGY_NAME_TO_ID
                        cn_to_en = dict(STRATEGY_NAME_TO_ID)
                    except ImportError:
                        pass
                    for cn_name, v in bt_data.get("strategy_results",{}).items():
                        en_name = cn_to_en.get(cn_name, cn_name)
                        if en_name not in backtest_results:
                            ret = v.get("total_return", 0) or 0
                            # total_return<10视为倍数(2.65=265%),>=10视为百分比
                            ret_pct = round(ret * 100, 1) if abs(ret) < 10 else round(ret, 1)
                            dd = v.get("max_drawdown", 0) or 0
                            dd_pct = round(dd * 100, 1) if abs(dd) < 1 and dd != 0 else round(dd, 1)
                            backtest_results[en_name] = {
                                "total_return": ret_pct,
                                "win_rate": round(v.get("win_rate", 0) or 0, 1),
                                "max_drawdown": dd_pct,
                                "sharpe": round(v.get("sharpe_ratio", 0) or 0, 2),
                                "trades": v.get("total_trades", 0) or 0,
                                "source": "backtest_result.json",
                            }
                except Exception as e:
                    logger.warning(f"[BACKTEST-COMPARE] file read failed: {e}")

        # 3. 组装对比数据
        compare = []
        all_strategies = set(list(live_stats.keys()) + list(backtest_results.keys()))
        for sid in all_strategies:
            lp = live_stats.get(sid, {})
            bt = backtest_results.get(sid, {})
            compare.append({
                "strategy": sid,
                "live_trades": lp.get("trades", 0),
                "live_win_rate": lp.get("win_rate", 0),
                "live_pnl": lp.get("total_pnl", 0),
                "bt_return": bt.get("total_return", 0),
                "bt_win_rate": round(bt.get("win_rate", 0), 1),
                "bt_drawdown": bt.get("max_drawdown", 0),
                "bt_sharpe": round(bt.get("sharpe", 0), 2),
                "bt_trades": bt.get("trades", 0),
                "bt_source": bt.get("source", "mongodb"),
            })

        return {"success": True, "data": compare, "backtest_type": backtest_type}
    except Exception as e:
        return {"success": True, "data": [], "message": str(e)}


# ==================== 调试增强 API ====================


@router.get("/trade-attribution")
async def get_trade_attribution(date: str = None):
    """逐笔归因分析 - 每笔交易赚在哪/亏在哪

    Args:
        date: YYYYMMDD格式, 不传则返回最近交易日

    Returns:
        逐笔归因列表: ts_code/strategy/buy_price/sell_price/profit_pct/sell_reason/why_profit/why_loss
    """
    try:
        from core.managers import mongo_manager
        if not mongo_manager.is_initialized:
            return {"success": True, "data": []}
        db = mongo_manager.db

        # 确定日期
        if not date:
            latest = await db["broker_orders"].find_one(
                {"side": "sell", "status": "filled"},
                sort=[("_id", -1)]
            )
            if not latest:
                return {"success": True, "data": []}
            date = latest.get("trade_date", "")

        # 【v2.9.86修复】broker_orders.trade_date是int，必须转换
        date_int = int(date) if isinstance(date, str) and date.isdigit() else date

        attributions = []
        # 从broker_order读取卖出记录
        async for doc in db["broker_orders"].find({
            "trade_date": date_int, "side": "sell", "status": "filled"
        }).sort("fill_time", 1):
            ts_code = doc.get("ts_code", "")
            strategy = doc.get("strategy", "")
            profit_pct = doc.get("profit_pct", 0) or 0
            sell_reason = doc.get("reason", "")
            filled_price = doc.get("filled_price", 0) or 0
            filled_qty = doc.get("filled_qty", 0) or 0

            # 查找对应买入记录(同日或之前)
            buy_doc = await db["broker_orders"].find_one(
                {"ts_code": ts_code, "strategy": strategy, "side": "buy", "status": "filled", "trade_date": {"$lte": date_int}},
                sort=[("_id", -1)]  # 最近的一次买入
            )
            buy_price = buy_doc.get("filled_price", 0) if buy_doc else 0
            buy_time = buy_doc.get("fill_time", "") if buy_doc else ""
            # 如果没有买入记录,从profit_pct反推buy_price
            # 反推公式: buy_price = sell_price / (1 + profit_pct/100)
            # profit_pct=0时buy_price=sell_price(保本卖出)
            if buy_price == 0 and filled_price > 0:
                if profit_pct != 0:
                    buy_price = round(filled_price / (1 + profit_pct / 100), 2)
                else:
                    # profit_pct=0: 保本卖出，买入价≈卖出价
                    buy_price = round(filled_price, 2)

            # 查找scan_trace(买入漏斗) — 策略名可能存在别名(anomaly_surge vs halfway_chase)
            scan_info = None
            try:
                # 先用原始strategy查,找不到再用别名反查
                scan_doc = await db["scan_traces"].find_one(
                    {"candidates.ts_code": ts_code, "candidates.strategy": strategy},
                    {"scan_time": 1, "summary": 1, "layer_details": 1}
                )
                if not scan_doc:
                    # 尝试用别名反查: halfway_chase → anomaly_surge等
                    from nodes.backtest_engine.strategy_defaults import STRATEGY_ALIASES
                    alias_list = [k for k, v in STRATEGY_ALIASES.items() if v == strategy]
                    for alias in alias_list:
                        scan_doc = await db["scan_traces"].find_one(
                            {"candidates.ts_code": ts_code, "candidates.strategy": alias},
                            {"scan_time": 1, "summary": 1, "layer_details": 1}
                        )
                        if scan_doc:
                            break
                if scan_doc:
                    ld = scan_doc.get("layer_details") or {}
                    scan_info = {
                        "scan_time": scan_doc.get("scan_time", "")[:19],
                        "sentiment": ld.get("L3_sentiment", ""),
                        "ranking": ld.get("L7_ranking", ""),
                    }
            except Exception:
                pass

            # 归因分析
            why_profit = None
            why_loss = None
            if profit_pct >= 0:
                if "追踪" in sell_reason:
                    why_profit = "趋势延续盈利锁定"
                elif "止盈" in sell_reason:
                    why_profit = "达到止盈目标"
                elif "冲高" in sell_reason:
                    why_profit = "冲高兑现"
                else:
                    why_profit = "趋势延续"
            else:
                if "止损" in sell_reason and "追踪" not in sell_reason:
                    why_loss = f"触发止损({profit_pct:.1f}%)"
                elif "追踪止损" in sell_reason:
                    why_loss = "冲高回落"
                elif "强制" in sell_reason or "空仓" in sell_reason:
                    why_loss = "系统风控强制清仓"
                else:
                    why_loss = "行情反转"

            attributions.append({
                "ts_code": ts_code,
                "stock_name": doc.get("stock_name", ""),
                "strategy": strategy,
                "buy_price": buy_price,
                "sell_price": filled_price,
                "profit_pct": profit_pct,
                "profit_amount": doc.get("profit_amount", 0),
                "buy_time": buy_time,
                "sell_time": doc.get("fill_time", ""),
                "sell_reason": sell_reason,
                "why_profit": why_profit,
                "why_loss": why_loss,
                "scan_info": scan_info,
            })

        return {"success": True, "data": attributions}
    except Exception as e:
        return {"success": True, "data": [], "message": str(e)}


# ==================== 自动交易操作流 + 策略参数对比 ====================


@router.get("/review-hero")
async def get_review_hero(date: str = None):
    """复盘Hero: 一句话结论 + 基准对比 + 核心指标 + 纪律评分

    Args:
        date: YYYYMMDD格式
    """
    try:
        from core.managers import mongo_manager
        if not mongo_manager.is_initialized:
            return {"success": True, "data": None}
        db = mongo_manager.db

        if not date:
            latest = await db["broker_orders"].find_one({"side":"sell","status":"filled"}, sort=[("_id",-1)])
            date = latest.get("trade_date","") if latest else ""

        if not date:
            return {"success": True, "data": None, "message": "无交易数据"}

        # 【v2.9.86修复】broker_orders.trade_date是int
        date_int = int(date) if isinstance(date, str) and date.isdigit() else date

        # 1. 当日交易统计
        sells, buys = [], []
        async for doc in db["broker_orders"].find({"trade_date": date_int, "status": "filled"}):
            (buys if doc.get("side") == "buy" else sells).append(doc)

        # 止损/止盈计数(基于卖出原因,非胜/负)
        # 【v2.9.84修复】追踪止损: 盈利时算止盈,亏损时算止损(之前全算止盈)
        stop_losses = [s for s in sells if ("止损" in (s.get("reason","") or "") and "追踪" not in (s.get("reason","") or "")) or ("追踪止损" in (s.get("reason","") or "") and (s.get("profit_pct") or 0) < 0)];
        take_profits = [s for s in sells if "止盈" in (s.get("reason","") or "") or ("追踪止损" in (s.get("reason","") or "") and (s.get("profit_pct") or 0) >= 0)]
        wins = [s for s in sells if (s.get("profit_pct") or 0) >= 0]
        losses = [s for s in sells if (s.get("profit_pct") or 0) < 0]
        win_rate = len(wins) / max(len(sells), 1) * 100
        avg_win = sum(s.get("profit_pct",0) or 0 for s in wins) / max(len(wins),1) if wins else 0
        avg_loss = sum(s.get("profit_pct",0) or 0 for s in losses) / max(len(losses),1) if losses else 0
        total_pct = sum(s.get("profit_pct",0) or 0 for s in sells)

        # 2. 期望值 = 胜率×均盈 - 败率×均亏
        expectancy = (win_rate/100) * avg_win - (1-win_rate/100) * abs(avg_loss) if sells else 0

        # 3. 大盘对比(上证)
        benchmark_pct = 0
        benchmark_name = "上证指数"
        idx_doc = await db["index_daily"].find_one({"ts_code": "000001.SH", "trade_date": int(date)})
        if idx_doc:
            benchmark_pct = idx_doc.get("pct_chg", 0) or 0
        else:
            # 尝试最近的交易日
            idx_doc = await db["index_daily"].find_one({"ts_code": "000001.SH", "trade_date": {"$lte": int(date)}}, sort=[("trade_date",-1)])
            if idx_doc:
                benchmark_pct = idx_doc.get("pct_chg", 0) or 0

        # 4. 情绪环境
        sentiment_doc = await db["sentiment_scores"].find_one({"trade_date": int(date)})
        sentiment_period = sentiment_doc.get("period", "") if sentiment_doc else ""
        sentiment_score = sentiment_doc.get("score", 0) if sentiment_doc else 50
        if sentiment_doc and sentiment_doc.get("missing_data"):
            sentiment_period = sentiment_doc.get("period", "") + "(数据缺失)"

        # 5. 纪律检查
        violations = []
        # 统一情绪周期为英文(兼容中文存储)
        _cn_to_en_period = {"高潮": "RISING", "分化": "DIFFERENTIATION", "震荡": "CHAOS", "冰点": "BEARISH"}
        _en_to_cn_period = {"RISING": "高潮", "DIFFERENTIATION": "分化", "CHAOS": "震荡", "BEARISH": "冰点", "rising": "高潮", "differentiation": "分化", "chaos": "震荡", "bearish": "冰点"}
        raw_period = sentiment_doc.get("period", "") if sentiment_doc else ""
        # 如果存储的是中文,转为英文
        if raw_period in _cn_to_en_period:
            raw_period = _cn_to_en_period[raw_period]
        cn_period = _en_to_cn_period.get(raw_period, raw_period)
        # 冰点开仓(仅BEARISH算违规,CHAOS震荡期允许开仓但限制策略)
        if (sentiment_doc and raw_period in ["BEARISH", "bearish"]) and buys:
            for b in buys:
                violations.append({
                    "type": "冰点开仓", "severity": "high",
                    "ts_code": b.get("ts_code",""), "strategy": b.get("strategy",""),
                    "detail": f"情绪{sentiment_score:.0f}分({cn_period})时买入{b.get('ts_code','')}"
                })
        # 情绪不匹配(冰点做半路追涨)
        strategy_period_fit = {"halfway_chase": ["RISING", "DIFFERENTIATION"], "first_limit_up": ["RISING"], "limit_down_qiao": ["RISING", "DIFFERENTIATION", "CHAOS"], "dragon_head": ["RISING", "DIFFERENTIATION"]}
        if sentiment_doc:
            for b in buys:
                strat = _norm_strat(b.get("strategy", ""))  # 归一化:anomaly_surge→halfway_chase
                fit_periods = strategy_period_fit.get(strat, [])
                if fit_periods and raw_period not in fit_periods:
                    violations.append({
                        "type": "情绪不匹配", "severity": "medium",
                        "ts_code": b.get("ts_code",""), "strategy": strat,
                        "detail": f"{cn_period}期做{strat}(适合{'+'.join(_en_to_cn_period.get(p,p) for p in fit_periods)})"
                    })
        # 单日止损过多(≥3) — 使用前面的stop_losses变量,不要重新定义
        if len(stop_losses) >= 3:
            violations.append({
                "type": "止损过多", "severity": "high",
                "ts_code": "", "strategy": "",
                "detail": f"当日止损{len(stop_losses)}笔,建议检查入场条件"
            })

        discipline_score = max(0, 100 - len(violations) * 20)

        # 6. 连续亏损
        all_sells_cursor = db["broker_orders"].find({"side":"sell","status":"filled"}, {"profit_pct":1,"trade_date":1}).sort("trade_date",1)
        all_sells = await all_sells_cursor.to_list(length=500)
        max_consecutive_loss = 0
        current_loss_streak = 0
        for s in all_sells:
            pct = s.get("profit_pct",0) or 0
            if pct < 0:
                current_loss_streak += 1
                max_consecutive_loss = max(max_consecutive_loss, current_loss_streak)
            else:
                current_loss_streak = 0

        # 7. 一句话结论
        if not sells:
            conclusion = "📋 当日无卖出交易"
            conclusion_type = "neutral"
        elif total_pct > 3:
            conclusion = f"🟢 今日大赚 +{total_pct:.1f}% 跑赢大盘{total_pct - benchmark_pct:.1f}% {max((wins), key=lambda w: w.get('profit_pct',0)).get('strategy','')}贡献最大"
            conclusion_type = "profit"
        elif total_pct > 0:
            conclusion = f"🟡 今日小赚 +{total_pct:.1f}% {'跑赢' if total_pct > benchmark_pct else '落后'}大盘{abs(total_pct - benchmark_pct):.1f}%"
            conclusion_type = "slight_profit"
        elif total_pct > -2:
            conclusion = f"🟠 今日小亏 {total_pct:.1f}% {'仍跑赢大盘' if total_pct > benchmark_pct else '落后大盘'} 止损{len(stop_losses)}笔"
            conclusion_type = "slight_loss"
        else:
            conclusion = f"🔴 今日亏损 {total_pct:.1f}% 止损{len(stop_losses)}笔过多 建议降仓检查策略"
            conclusion_type = "loss"

        return {"success": True, "data": {
            "date": date,
            "conclusion": conclusion,
            "conclusion_type": conclusion_type,
            "metrics": {
                "total_pct": round(total_pct, 2),
                "win_rate": round(win_rate, 1),
                "trades": len(sells),
                "buys": len(buys),
                "stop_loss_count": len(stop_losses),
                "take_profit_count": len(take_profits),
                "expectancy": round(expectancy, 2),
                "discipline_score": discipline_score,
                "max_consecutive_loss": max_consecutive_loss,
                "avg_win": round(avg_win, 1),
                "avg_loss": round(avg_loss, 1),
                "profit_loss_ratio": round(abs(avg_win / avg_loss), 1) if avg_loss != 0 else 0,
            },
            "benchmark": {
                "name": benchmark_name,
                "pct_chg": round(benchmark_pct, 2),
                "alpha": round(total_pct - benchmark_pct, 2),
            },
            "sentiment": {
                "period": cn_period,
                "score": sentiment_score,
            },
            "violations": violations,
        }}
    except Exception as e:
        return {"success": True, "data": None, "message": str(e)}



@router.get("/discipline-check")
async def get_discipline_check(date: str = None):
    """纪律检查: 标记违规交易, 计算执行正确率

    Args:
        date: YYYYMMDD格式
    """
    try:
        from core.managers import mongo_manager
        if not mongo_manager.is_initialized:
            return {"success": True, "data": None}
        db = mongo_manager.db

        if not date:
            latest = await db["broker_orders"].find_one({"side":"sell","status":"filled"}, sort=[("_id",-1)])
            date = latest.get("trade_date","") if latest else ""

        if not date:
            return {"success": True, "data": None, "message": "无交易数据"}

        # 情绪
        sentiment_doc = await db["sentiment_scores"].find_one({"trade_date": int(date)})
        raw_period = sentiment_doc.get("period","") if sentiment_doc else ""
        sentiment_score = sentiment_doc.get("score",50) if sentiment_doc else 50

        # 统一情绪周期为中文(兼容英文存储)
        _en_to_cn_period = {"RISING": "高潮", "DIFFERENTIATION": "分化", "CHAOS": "震荡", "BEARISH": "冰点", "rising": "高潮", "differentiation": "分化", "chaos": "震荡", "bearish": "冰点"}
        if raw_period in _en_to_cn_period:
            raw_period = _en_to_cn_period[raw_period]  # 英文转中文

        # 策略-情绪适配规则(统一用中文key)
        strategy_fit = {
            "halfway_chase": {"高潮": True, "分化": True, "震荡": False, "冰点": False},
            "first_limit_up": {"高潮": True, "分化": False, "震荡": False, "冰点": False},
            "limit_down_qiao": {"高潮": True, "分化": True, "震荡": True, "冰点": False},
            "dragon_head": {"高潮": True, "分化": True, "震荡": False, "冰点": False},
        }

        violations = []
        total_actions = 0
        correct_actions = 0

        # 【v2.9.86修复】broker_orders.trade_date是int
        date_int = int(date) if isinstance(date, str) and date.isdigit() else date

        # 检查买入
        async for doc in db["broker_orders"].find({"trade_date": date_int, "side": "buy", "status": "filled"}):
            total_actions += 1
            strat = _norm_strat(doc.get("strategy", ""))  # 归一化:anomaly_surge→halfway_chase
            fit = strategy_fit.get(strat, {})
            is_fit = fit.get(raw_period, True)  # 未知策略默认合规

            # 冰点期禁止开仓
            if raw_period in ["BEARISH", "冰点", "bearish"]:
                violations.append({
                    "ts_code": doc.get("ts_code",""), "strategy": strat, "side": "buy",
                    "violation": "冰点期禁止开仓", "severity": "high",
                    "detail": f"情绪{sentiment_score:.0f}分处于冰点,不应买入"
                })
            elif not is_fit:
                violations.append({
                    "ts_code": doc.get("ts_code",""), "strategy": strat, "side": "buy",
                    "violation": "情绪不匹配", "severity": "medium",
                    "detail": f"{raw_period}期不适合做{strat}"
                })
            else:
                correct_actions += 1

        # 检查卖出(止损是否及时)
        async for doc in db["broker_orders"].find({"trade_date": date_int, "side": "sell", "status": "filled"}):
            total_actions += 1
            pct = doc.get("profit_pct",0) or 0
            reason = doc.get("reason","")

            # 亏损超过5%仍未止损(可能是扛单)
            if pct < -5 and "止损" not in reason:
                violations.append({
                    "ts_code": doc.get("ts_code",""), "strategy": doc.get("strategy",""), "side": "sell",
                    "violation": "亏损过大未及时止损", "severity": "high",
                    "detail": f"亏损{pct:.1f}%但卖出原因非止损({reason[:20]})"
                })
            else:
                correct_actions += 1

        execution_rate = correct_actions / max(total_actions, 1) * 100

        return {"success": True, "data": {
            "date": date,
            "total_actions": total_actions,
            "correct_actions": correct_actions,
            "execution_rate": round(execution_rate, 1),
            "violation_count": len(violations),
            "violations": violations,
        }}
    except Exception as e:
        return {"success": True, "data": None, "message": str(e)}



@router.get("/review-forward")
async def get_review_forward(date: str = None):
    """前瞻建议: 基于当前情绪+历史模式给出明日操作建议

    Args:
        date: YYYYMMDD格式
    """
    try:
        from core.managers import mongo_manager
        if not mongo_manager.is_initialized:
            return {"success": True, "data": None}
        db = mongo_manager.db

        if not date:
            import datetime
            date = datetime.datetime.now().strftime("%Y%m%d")

        # 1. 当前情绪
        sentiment_doc = await db["sentiment_scores"].find_one({"trade_date": int(date)})
        if not sentiment_doc:
            # fallback到最近
            sentiment_doc = await db["sentiment_scores"].find_one({"missing_data": {"$ne": True}}, sort=[("trade_date",-1)])

        raw_period = sentiment_doc.get("period","") if sentiment_doc else ""
        score = sentiment_doc.get("score",50) if sentiment_doc else 50
        period_map = {"RISING": "高潮", "DIFFERENTIATION": "分化", "CHAOS": "震荡", "BEARISH": "冰点", "rising": "高潮", "differentiation": "分化", "chaos": "震荡", "bearish": "冰点"}
        cn_period = period_map.get(raw_period, raw_period)
        # 统一cn_period为中文(如果raw_period已经是中文则保持)
        # period_map的value已经是中文,所以如果raw_period不在period_map中且是中文则直接用
        _cn_periods = {"高潮", "分化", "震荡", "冰点"}
        if raw_period in _cn_periods:
            cn_period = raw_period

        # 2. 策略历史表现(近30天)
        from collections import defaultdict
        strat_stats = defaultdict(lambda: {"wins":0,"losses":0,"count":0})
        recent_sells = db["broker_orders"].find({"side":"sell","status":"filled"}).sort("_id",-1).limit(60)
        async for doc in recent_sells:
            strat = _norm_strat(doc.get("strategy","unknown"))
            pct = doc.get("profit_pct",0) or 0
            strat_stats[strat]["count"] += 1
            if pct >= 0:
                strat_stats[strat]["wins"] += 1
            else:
                strat_stats[strat]["losses"] += 1

        # 3. 生成建议
        strategy_recommendations = []
        strategy_switches = []
        period_strategy_map = {
            "高潮": {"open": ["halfway_chase","first_limit_up","limit_down_qiao","dragon_head"], "close": []},
            "分化": {"open": ["halfway_chase","dragon_head"], "close": ["first_limit_up"]},
            "震荡": {"open": ["limit_down_qiao"], "close": ["halfway_chase","first_limit_up"]},
            "冰点": {"open": [], "close": ["halfway_chase","first_limit_up","limit_down_qiao","dragon_head"]},
            # 【V75修复】英文key fallback: MongoDB可能存英文period(RISING/BEARISH等),大小写均支持
            "RISING": {"open": ["halfway_chase","first_limit_up","limit_down_qiao","dragon_head"], "close": []},
            "DIFFERENTIATION": {"open": ["halfway_chase","dragon_head"], "close": ["first_limit_up"]},
            "CHAOS": {"open": ["limit_down_qiao"], "close": ["halfway_chase","first_limit_up"]},
            "BEARISH": {"open": [], "close": ["halfway_chase","first_limit_up","limit_down_qiao","dragon_head"]},
            "rising": {"open": ["halfway_chase","first_limit_up","limit_down_qiao","dragon_head"], "close": []},
            "differentiation": {"open": ["halfway_chase","dragon_head"], "close": ["first_limit_up"]},
            "chaos": {"open": ["limit_down_qiao"], "close": ["halfway_chase","first_limit_up"]},
            "bearish": {"open": [], "close": ["halfway_chase","first_limit_up","limit_down_qiao","dragon_head"]},
        }

        switches = period_strategy_map.get(raw_period, period_strategy_map.get(cn_period, {"open":[],"close":[]}))
        for strat in switches["open"]:
            st = strat_stats.get(strat, {})
            wr = st.get("wins",0) / max(st.get("count",1),1) * 100
            strategy_recommendations.append({"strategy": strat, "action": "open", "win_rate": round(wr,1), "count": st.get("count",0)})
        for strat in switches["close"]:
            strategy_switches.append({"strategy": strat, "action": "close", "reason": f"{cn_period}期不适合该策略"})

        # 4. 参数漂移检查
        drift_warnings = []
        try:
            from core.managers.param_center import ParamCenter
            pc = ParamCenter()
            for strat_key in ["halfway_chase","first_limit_up","limit_down_qiao","dragon_head"]:
                live_params = await pc.get_strategy_config(strat_key)
                if live_params and live_params.get("source") == "param_center":
                    drift_warnings.append({"strategy": strat_key, "status": "参数已从ParamCenter修改", "source": "param_center"})
        except Exception:
            pass

        # 5. 综合建议
        if raw_period in ["RISING", "高潮"]:
            advice = f"当前高潮({score:.0f}分),所有策略开放。建议满仓操作,注意高潮末端可能突然分化,设好止盈。"
        elif raw_period in ["DIFFERENTIATION", "分化"]:
            advice = f"当前分化({score:.0f}分),建议降仓位至50-70%。只做半路追涨和龙头低吸,关闭首板打板。"
        elif raw_period in ["CHAOS", "震荡"]:
            advice = f"当前震荡({score:.0f}分),建议轻仓25-40%。只做跌停翘板(小仓),严格止损3%,快进快出。"
        else:
            advice = f"当前冰点({score:.0f}分),建议空仓观望,禁止新开仓。持仓执行止损,等待情绪回暖信号(涨停>50)。"

        return {"success": True, "data": {
            "date": date,
            "sentiment": {"period": cn_period, "score": score, "raw_period": raw_period},
            "advice": advice,
            "strategy_recommendations": strategy_recommendations,
            "strategy_switches": strategy_switches,
            "drift_warnings": drift_warnings,
        }}
    except Exception as e:
        return {"success": True, "data": None, "message": str(e)}



@router.post("/backtest-same-period")
async def backtest_same_period(request: Request):
    """P0: 同区间回测 - 用当前参数重跑实盘同区间的回测

    请求体: {"start_date": "20260518", "end_date": "20260530"}
    如果不传, 自动取broker_orders最早~最新卖出日
    """
    try:
        body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        start_date = body.get("start_date")
        end_date = body.get("end_date")

        from core.managers import mongo_manager

        if not start_date or not end_date:
            if not mongo_manager.is_initialized:
                return {"success": False, "message": "MongoDB未初始化, 请提供start_date/end_date"}
            # 自动取实盘日期范围
            sells = []
            async for doc in mongo_manager.db["broker_orders"].find({"side":"sell","status":"filled"},{"trade_date":1}):
                if doc.get("trade_date"):
                    sells.append(doc["trade_date"])
            if not sells:
                return {"success": False, "message": "无实盘交易数据"}
            start_date = min(sells)
            end_date = max(sells)

        # 后台运行回测
        import asyncio, os, sys

        async def _run_same_period_bt(sd, ed):
            try:
                BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                if BASE not in sys.path:
                    sys.path.insert(0, BASE)

                from nodes.backtest_engine.factor_selection.portfolio_backtest import PortfolioBacktester
                from core.managers import mongo_manager as mm

                if not mm.is_initialized:
                    await mm.initialize()

                # 检查行情数据是否存在
                bar_count = await mm.db["stock_daily_ak_full"].count_documents(
                    {"trade_date": {"$gte": sd, "$lte": ed}}
                )
                if bar_count < 100:
                    # 尝试用东财补数据
                    try:
                        from nodes.market_monitor.data_source_router import data_source_router
                        for td_int in range(int(sd), int(ed)+1):
                            td_str = str(td_int)
                            if await mm.db["stock_daily_ak_full"].count_documents({"trade_date": td_str}) > 0:
                                continue
                            try:
                                await data_source_router.fetch_and_save_daily_bar(td_str)
                                logger.info(f"[SAME-PERIOD-BT] 补数据: {td_str}")
                            except Exception: pass
                    except Exception as e2:
                        logger.warning(f"[SAME-PERIOD-BT] 补数据失败: {e2}")

                    bar_count2 = await mm.db["stock_daily_ak_full"].count_documents(
                        {"trade_date": {"$gte": sd, "$lte": ed}}
                    )
                    if bar_count2 < 100:
                        await mm.db["backtest_results"].update_one(
                            {"task_id": f"same_period_{sd}_{ed}"},
                            {"$set": {
                                "task_id": f"same_period_{sd}_{ed}",
                                "status": "failed",
                                "error": f"行情数据不足: {bar_count2}条(需要>100)",
                                "created_at": datetime.now().isoformat(),
                                "type": "same_period",
                            }},
                            upsert=True
                        )
                        return

                bt = PortfolioBacktester()
                bt_config = {
                    "start_date": sd,
                    "end_date": ed,
                    "initial_cash": 1000000,
                    "strategies": ["halfway_chase", "limit_down_qiao", "dragon_head", "first_limit_up"],
                    "mode": "backtest",
                }
                result = await bt.run(bt_config)

                # 存到MongoDB
                await mm.db["backtest_results"].update_one(
                    {"task_id": f"same_period_{sd}_{ed}"},
                    {"$set": {
                        "task_id": f"same_period_{sd}_{ed}",
                        "status": "completed",
                        "params": {"strategy_ids": bt_config["strategies"], "start_date": sd, "end_date": ed},
                        "result": {"summary": result},
                        "created_at": datetime.now().isoformat(),
                        "type": "same_period",
                    }},
                    upsert=True
                )
                logger.info(f"[SAME-PERIOD-BT] Completed: {sd}~{ed}, return={result.get('total_return',0):.2%}")
            except Exception as e:
                logger.error(f"[SAME-PERIOD-BT] Failed: {e}")
                try:
                    await mm.db["backtest_results"].update_one(
                        {"task_id": f"same_period_{sd}_{ed}"},
                        {"$set": {"status": "failed", "error": str(e), "created_at": datetime.now().isoformat()}},
                        upsert=True
                    )
                except Exception: pass

        asyncio.create_task(_run_same_period_bt(start_date, end_date))

        return {"success": True, "message": f"同区间回测已启动({start_date}~{end_date}), 预计30-60秒", "start_date": start_date, "end_date": end_date}
    except Exception as e:
        return {"success": False, "message": str(e)}



@router.get("/deviation-attribution")
async def deviation_attribution(date: str = None, start_date: str = None, end_date: str = None):
    """P1: 偏差4层归因 - 滑点/纪律/选股/时间

    Args:
        date: 单日YYYYMMDD
        start_date/end_date: 区间查询
    """
    try:
        from core.managers import mongo_manager
        if not mongo_manager.is_initialized:
            return {"success": True, "data": None, "message": "MongoDB未初始化"}

        db = mongo_manager.db

        # 确定日期范围
        if date:
            sd = ed = date
        elif start_date and end_date:
            sd, ed = start_date, end_date
        else:
            # 默认取最近7天
            sells = []
            async for doc in db["broker_orders"].find({"side":"sell","status":"filled"},{"trade_date":1}).sort("trade_date",-1).limit(20):
                if doc.get("trade_date"): sells.append(doc["trade_date"])
            if not sells:
                return {"success": True, "data": None, "message": "无交易数据"}
            sd, ed = min(sells), max(sells)

        # 1. 获取实盘卖出订单
        query = {"side": "sell", "status": "filled"}
        if sd == ed:
            query["trade_date"] = sd
        else:
            query["trade_date"] = {"$gte": sd, "$lte": ed}

        sells = []
        async for doc in db["broker_orders"].find(query):
            sells.append(doc)

        # 2. 获取同区间买入订单(用于计算纪律偏差)
        buy_query = {"side": "buy", "status": "filled"}
        if sd == ed:
            buy_query["trade_date"] = sd
        else:
            buy_query["trade_date"] = {"$gte": sd, "$lte": ed}

        buys = []
        async for doc in db["broker_orders"].find(buy_query):
            buys.append(doc)

        # 3. 获取情绪数据(用于纪律检查)
        sentiment_map = {}
        s_query = {}
        if sd == ed:
            s_query["trade_date"] = int(sd)
        else:
            s_query["trade_date"] = {"$gte": int(sd), "$lte": int(ed)}
        _en_to_cn = {"RISING": "高潮", "DIFFERENTIATION": "分化", "CHAOS": "震荡", "BEARISH": "冰点", "rising": "高潮", "differentiation": "分化", "chaos": "震荡", "bearish": "冰点"}
        async for doc in db["sentiment_scores"].find(s_query, {"trade_date":1, "score":1, "period":1}):
            raw_p = doc.get("period", "震荡")
            cn_p = _en_to_cn.get(raw_p, raw_p)  # 英文转中文,中文保持
            sentiment_map[str(doc.get("trade_date",""))] = {"score": doc.get("score",50), "period": cn_p}

        # 4. 获取scan_traces(信号价格,用于滑点计算)
        scan_map = {}  # trade_date -> {ts_code -> {price, strategy}}
        scan_query = {}
        if sd == ed:
            scan_query["trade_date"] = sd
        else:
            scan_query["trade_date"] = {"$gte": sd, "$lte": ed}
        async for doc in db["scan_traces"].find(scan_query, {"trade_date":1, "candidates":1}):
            td = doc.get("trade_date","")
            cands = doc.get("candidates",[])
            for c in cands:
                if c.get("final_status") == "passed" and c.get("ts_code"):
                    if td not in scan_map:
                        scan_map[td] = {}
                    scan_map[td][c["ts_code"]] = {"price": c.get("price",0), "strategy": _norm_strat(c.get("strategy",""))}

        # ============ 计算偏差 ============

        # A. 滑点偏差: 信号价格 vs 成交价格
        slippage_details = []
        total_slippage_pct = 0
        slippage_count = 0
        for buy in buys:
            ts = buy.get("ts_code","")
            td = buy.get("trade_date","")
            fp = buy.get("filled_price",0) or 0
            # 从scan_traces找信号价格
            signal = scan_map.get(td, {}).get(ts, {})
            sp = signal.get("price", 0)
            if sp > 0 and fp > 0:
                slippage = (fp - sp) / sp * 100  # 正=买贵了(不利)
                slippage_details.append({
                    "ts_code": ts, "stock_name": buy.get("stock_name",""),
                    "signal_price": round(sp, 2), "filled_price": round(fp, 2),
                    "slippage_pct": round(slippage, 2), "strategy": buy.get("strategy",""),
                    "trade_date": td,
                })
                total_slippage_pct += slippage
                slippage_count += 1

        # B. 纪律偏差: 冰点期开仓 / 情绪不匹配
        discipline_details = []
        strategy_sentiment_rules = {
            "halfway_chase": {"适合": ["高潮","分化"], "不适合": ["震荡","冰点"]},
            "first_limit_up": {"适合": ["高潮"], "不适合": ["分化","震荡","冰点"]},
            "limit_down_qiao": {"适合": ["高潮","分化","震荡"], "不适合": ["冰点"]},
            "dragon_head": {"适合": ["高潮","分化"], "不适合": ["震荡","冰点"]},
        }
        for buy in buys:
            td = buy.get("trade_date","")
            strat = _norm_strat(buy.get("strategy","") or "unknown")
            sentiment = sentiment_map.get(td, {})
            period = sentiment.get("period","")
            if strat in strategy_sentiment_rules and period:
                not_suitable = strategy_sentiment_rules[strat].get("不适合",[])
                if period in not_suitable:
                    discipline_details.append({
                        "type": "情绪不匹配",
                        "strategy": strat, "period": period,
                        "detail": f"{period}期买入{strat}",
                        "trade_date": td, "ts_code": buy.get("ts_code",""),
                        "stock_name": buy.get("stock_name",""),
                    })

        # C. 选股偏差: 实盘买入 vs scan_traces候选的重叠度
        # 只统计scan_traces有数据的日期(避免日期不匹配导致overlap=0)
        scan_dates = set(scan_map.keys())
        live_picks = {}  # strategy -> [ts_codes] (only for dates with scan data)
        for buy in buys:
            td = buy.get("trade_date","")
            if td not in scan_dates:
                continue  # 跳过无scan_traces数据的日期
            s = _norm_strat(buy.get("strategy","") or "unknown")
            if s not in live_picks: live_picks[s] = set()
            live_picks[s].add(buy.get("ts_code",""))

        signal_picks = {}  # strategy -> [ts_codes]
        for td, codes in scan_map.items():
            for ts, info in codes.items():
                s = info.get("strategy","")
                if s not in signal_picks: signal_picks[s] = set()
                signal_picks[s].add(ts)

        # 策略名映射: scan_traces中可能的别名→STRATEGY_CONFIGS的ID
        # 【V75修复】统一使用strategy_defaults.STRATEGY_ALIASES + 本地补充
        try:
            from nodes.backtest_engine.strategy_defaults import STRATEGY_ALIASES as _ALIASES
            strategy_name_aliases = dict(_ALIASES)
        except ImportError:
            strategy_name_aliases = {}
        # 本地补充(STRATEGY_ALIASES可能不含的旧映射)
        strategy_name_aliases.setdefault("limit_up_open", "first_limit_up")  # 涨停开板≈首板打板(历史兼容)

        # 统一策略名后计算重叠
        def normalize_strat(s):
            return strategy_name_aliases.get(s, s)

        norm_live = {}  # normalized strategy -> set of ts_codes
        for s, codes in live_picks.items():
            ns = normalize_strat(s)
            if ns not in norm_live: norm_live[ns] = set()
            norm_live[ns].update(codes)

        norm_signal = {}
        for s, codes in signal_picks.items():
            ns = normalize_strat(s)
            if ns not in norm_signal: norm_signal[ns] = set()
            norm_signal[ns].update(codes)

        selection_details = []
        for strat in set(list(norm_live.keys()) + list(norm_signal.keys())):
            lp = norm_live.get(strat, set())
            sp = norm_signal.get(strat, set())
            overlap = lp & sp
            only_live = lp - sp
            only_signal = sp - lp
            selection_details.append({
                "strategy": strat,
                "live_count": len(lp), "signal_count": len(sp),
                "overlap_count": len(overlap), "overlap_pct": round(len(overlap)/max(len(lp),1)*100,1),
                "only_live": len(only_live), "only_signal": len(only_signal),
                "scan_dates_matched": len(scan_dates),
            })

        # D. 时间偏差: 估算(用create_time粗略判断是否延迟)
        timing_details = []
        late_count = 0
        for buy in buys:
            ct = buy.get("create_time","")  # 格式 HH:MM:SS
            if isinstance(ct, str) and ":" in ct:
                try:
                    h, m = int(ct.split(":")[0]), int(ct.split(":")[1])
                    # 10:00前算正常, 10:00后算延迟(半路追涨不应10点后买)
                    if h >= 10 and buy.get("strategy") == "halfway_chase":
                        late_count += 1
                        timing_details.append({
                            "type": "延迟执行",
                            "strategy": buy.get("strategy",""),
                            "execute_time": ct, "expected": "10:00前",
                            "ts_code": buy.get("ts_code",""), "stock_name": buy.get("stock_name",""),
                        })
                except Exception: pass

        # E. 汇总
        total_sells = len(sells)
        wins = sum(1 for s in sells if (s.get("profit_pct") or 0) >= 0)
        live_wr = round(wins / max(total_sells, 1) * 100, 1)

        # 违规买入的亏损贡献
        violation_sells = []
        for ds in discipline_details:
            # 找对应的卖出
            for s in sells:
                if s.get("ts_code") == ds.get("ts_code") and s.get("strategy") == ds.get("strategy"):
                    violation_sells.append(s)
        violation_loss = sum(s.get("profit_pct",0) or 0 for s in violation_sells)
        violation_wins = sum(1 for s in violation_sells if (s.get("profit_pct") or 0) >= 0)
        violation_wr = round(violation_wins/max(len(violation_sells),1)*100,1)

        avg_slippage = round(total_slippage_pct / max(slippage_count, 1), 2)

        # 总偏差估算(纪律是主因, 滑点次之)
        discipline_impact = round(violation_loss, 2)

        result = {
            "period": f"{sd}~{ed}",
            "live_stats": {"trades": total_sells, "wins": wins, "win_rate": live_wr},
            "risk_alerts": {
                "bearish_buy_ratio": round(len([b for b in buys if sentiment_map.get(b.get("trade_date",""),{}).get("period")=="冰点"])/max(len(buys),1)*100,1),
                "bearish_buy_count": len([b for b in buys if sentiment_map.get(b.get("trade_date",""),{}).get("period")=="冰点"]),
                "note": "冰点期开仓率高→信号管道L3层仅过滤halfway_chase, 其他策略仍允许冰点期候选通过"
            },
            "deviations": {
                "slippage": {"avg_pct": avg_slippage, "count": slippage_count, "impact": round(-avg_slippage * slippage_count / 100, 2)},
                "discipline": {"violations": len(discipline_details), "violation_wr": violation_wr, "impact": round(discipline_impact, 2)},
                "selection": selection_details,
                "timing": {"late_count": late_count, "count": len(timing_details)},
            },
            "details": {
                "slippage": slippage_details[:20],
                "discipline": discipline_details[:20],
                "timing": timing_details[:10],
            }
        }

        return {"success": True, "data": _clean_mongo(result)}
    except Exception as e:
        logger.error(f"[DEVIATION] {e}")
        return {"success": True, "data": None, "message": str(e)}



@router.get("/param-snapshot")
async def param_snapshot(date: str = None):
    """P2: 参数快照 - 当前参数状态(用于月复盘参数漂移检测)

    存一份当前strategy_defaults到MongoDB param_snapshots
    【V75修复】同时包含strategy_config.py中的覆盖参数(运行时实际值)
    """
    try:
        from nodes.backtest_engine.strategy_defaults import STRATEGY_CONFIGS, GLOBAL_RISK
        from core.managers import mongo_manager

        today = date or datetime.now().strftime("%Y%m%d")
        
        # 【V75修复】读取运行时覆盖后的实际值
        # 1. 先读取strategy_config API的覆盖(来自scanner_config集合)
        runtime_overrides = {}
        try:
            override_doc = await mongo_manager.db["scanner_config"].find_one(
                {"_id": "strategy_config_overrides"}
            )
            if override_doc and "data" in override_doc:
                runtime_overrides = override_doc["data"]
        except Exception:
            pass
        
        # 2. 构建快照: 默认值 + 覆盖值
        override_params = runtime_overrides.get("params", {})
        override_risk = runtime_overrides.get("risk", {})
        override_enabled = runtime_overrides.get("enabled", {})
        override_global_risk = runtime_overrides.get("global_risk", {})
        
        snapshot = {
            "date": today,
            "global_risk": {k: v for k, v in GLOBAL_RISK.items() if not k.startswith("__")},
            "strategies": {},
        }
        # 应用全局风控覆盖
        snapshot["global_risk"].update(override_global_risk)
        
        for sid, cfg in STRATEGY_CONFIGS.items():
            # 从默认值开始
            params = dict(cfg.get("params", {}))
            risk_params = dict(cfg.get("riskParams", {}))
            enabled = cfg.get("enabled", True)
            # 应用覆盖
            if sid in override_params:
                params.update(override_params[sid])
            if sid in override_risk:
                risk_params.update(override_risk[sid])
            if sid in override_enabled:
                enabled = override_enabled[sid]
            snapshot["strategies"][sid] = {
                "enabled": enabled,
                "params": params,
                "riskParams": risk_params,
            }

        if mongo_manager.is_initialized:
            await mongo_manager.db["param_snapshots"].update_one(
                {"date": today},
                {"$set": snapshot},
                upsert=True
            )

        return {"success": True, "data": snapshot, "message": f"参数快照已保存({today}), 含运行时覆盖"}
    except Exception as e:
        return {"success": False, "message": str(e)}



@router.get("/param-drift")
async def param_drift(start_date: str = None, end_date: str = None):
    """P2: 参数漂移检测 - 对比两个日期的参数差异

    用于月复盘: 当前参数 vs 30天前参数
    """
    try:
        from core.managers import mongo_manager
        if not mongo_manager.is_initialized:
            return {"success": True, "data": None, "message": "MongoDB未初始化"}

        db = mongo_manager.db
        end_date = end_date or datetime.now().strftime("%Y%m%d")

        # 找最近的快照
        end_snap = await db["param_snapshots"].find_one({"date": {"$lte": end_date}}, sort=[("date",-1)])
        if not end_snap:
            # 自动创建当前快照
            from nodes.backtest_engine.strategy_defaults import STRATEGY_CONFIGS, GLOBAL_RISK
            end_snap = {
                "date": end_date,
                "global_risk": {k:v for k,v in GLOBAL_RISK.items() if not k.startswith("__")},
                "strategies": {sid: {"params":cfg.get("params",{}),"riskParams":cfg.get("riskParams",{})} for sid,cfg in STRATEGY_CONFIGS.items()},
            }

        if start_date:
            start_snap = await db["param_snapshots"].find_one({"date": {"$lte": start_date}}, sort=[("date",-1)])
        else:
            # 找最早的快照
            start_snap = await db["param_snapshots"].find_one(sort=[("date",1)])

        if not start_snap:
            return {"success": True, "data": {"current": end_snap, "baseline": None, "drifts": []}, "message": "无历史快照,无法检测漂移"}

        # 对比参数
        drifts = []

        # 全局参数
        start_g = start_snap.get("global_risk", {})
        end_g = end_snap.get("global_risk", {})
        for key in set(list(start_g.keys()) + list(end_g.keys())):
            sv = start_g.get(key)
            ev = end_g.get(key)
            if sv != ev and not isinstance(sv, (dict, list)):
                drifts.append({"level":"global","key":key,"old":sv,"new":ev,"severity":"high" if key in ["stop_loss_pct","take_profit_pct","max_position_per_stock","max_total_position"] else "medium"})

        # 策略参数
        start_s = start_snap.get("strategies", {})
        end_s = end_snap.get("strategies", {})
        for sid in set(list(start_s.keys()) + list(end_s.keys())):
            for param_type in ["params","riskParams"]:
                sp = start_s.get(sid,{}).get(param_type,{})
                ep = end_s.get(sid,{}).get(param_type,{})
                for key in set(list(sp.keys()) + list(ep.keys())):
                    sv = sp.get(key)
                    ev = ep.get(key)
                    if sv != ev and not isinstance(sv, (dict, list)):
                        drifts.append({"level":"strategy","strategy":sid,"param_type":param_type,"key":key,"old":sv,"new":ev,"severity":"high" if param_type=="riskParams" else "medium"})

        return {"success": True, "data": {
            "start_date": start_snap.get("date"),
            "end_date": end_snap.get("date"),
            "drifts": drifts,
            "drift_count": len(drifts),
            "high_severity": len([d for d in drifts if d.get("severity")=="high"]),
        }}
    except Exception as e:
        return {"success": False, "message": str(e)}



@router.get("/review-weekly")
async def review_weekly(date: str = None):
    """P2: 周复盘 - 策略效能+偏差趋势+情绪环境

    Args:
        date: 周内任一天, 自动计算该周范围
    """
    try:
        from core.managers import mongo_manager
        if not mongo_manager.is_initialized:
            return {"success": True, "data": None, "message": "MongoDB未初始化"}

        db = mongo_manager.db

        # 计算本周范围(周一~周日)
        if date:
            from datetime import datetime as dt, timedelta
            d = dt.strptime(date, "%Y%m%d")
            weekday = d.weekday()
            monday = (d - timedelta(days=weekday)).strftime("%Y%m%d")
            sunday = (d + timedelta(days=6-weekday)).strftime("%Y%m%d")
        else:
            from datetime import datetime as dt, timedelta
            today = dt.now()
            weekday = today.weekday()
            monday = (today - timedelta(days=weekday)).strftime("%Y%m%d")
            sunday = (today + timedelta(days=6-weekday)).strftime("%Y%m%d")

        # 获取本周卖出
        sells = []
        async for doc in db["broker_orders"].find({"side":"sell","status":"filled","trade_date":{"$gte":monday,"$lte":sunday}}):
            sells.append(doc)

        # 获取本周买入
        buys = []
        async for doc in db["broker_orders"].find({"side":"buy","status":"filled","trade_date":{"$gte":monday,"$lte":sunday}}):
            buys.append(doc)

        # 逐日统计(偏差趋势)
        from collections import defaultdict
        daily_stats = defaultdict(lambda: {"buys":0,"sells":0,"wins":0,"pnl":0})
        for s in sells:
            td = s.get("trade_date","")
            daily_stats[td]["sells"] += 1
            if (s.get("profit_pct") or 0) >= 0:
                daily_stats[td]["wins"] += 1
            daily_stats[td]["pnl"] += s.get("profit_pct",0) or 0
        for b in buys:
            daily_stats[b.get("trade_date","")]["buys"] += 1

        # 情绪数据
        sentiments = {}
        async for doc in db["sentiment_scores"].find({"trade_date":{"$gte":int(monday),"$lte":int(sunday)}},{"trade_date":1,"score":1,"period":1}):
            sentiments[str(doc.get("trade_date",""))] = {"score":doc.get("score",50),"period":doc.get("period","")}

        # 策略统计
        strategy_stats = defaultdict(lambda: {"trades":0,"wins":0,"pnl":0})
        for s in sells:
            strat = _norm_strat(s.get("strategy","") or "unknown")
            strategy_stats[strat]["trades"] += 1
            if (s.get("profit_pct") or 0) >= 0:
                strategy_stats[strat]["wins"] += 1
            strategy_stats[strat]["pnl"] += s.get("profit_pct",0) or 0

        total_sells = len(sells)
        total_wins = sum(1 for s in sells if (s.get("profit_pct") or 0) >= 0)
        total_pnl = sum(s.get("profit_pct",0) or 0 for s in sells)

        # 偏差趋势(近4周)
        weekly_trend = []
        from datetime import datetime as dt, timedelta
        base = dt.strptime(monday, "%Y%m%d")
        for w in range(4):
            wm = (base - timedelta(weeks=3-w)).strftime("%Y%m%d")
            ws = (base - timedelta(weeks=3-w) + timedelta(days=6)).strftime("%Y%m%d")
            ws_list = []
            async for doc in db["broker_orders"].find({"side":"sell","status":"filled","trade_date":{"$gte":wm,"$lte":ws}}):
                ws_list.append(doc)
            if ws_list:
                wr = sum(1 for s in ws_list if (s.get("profit_pct") or 0) >= 0) / len(ws_list) * 100
                weekly_trend.append({"week": f"W{w+1}", "start": wm, "trades": len(ws_list), "win_rate": round(wr,1)})
            else:
                weekly_trend.append({"week": f"W{w+1}", "start": wm, "trades": 0, "win_rate": 0})

        result = {
            "period": f"{monday}~{sunday}",
            "summary": {"trades": total_sells, "wins": total_wins, "win_rate": round(total_wins/max(total_sells,1)*100,1), "pnl": round(total_pnl,2)},
            "strategy_stats": {k: {"trades":v["trades"],"win_rate":round(v["wins"]/max(v["trades"],1)*100,1),"pnl":round(v["pnl"],2)} for k,v in strategy_stats.items()},
            "daily_breakdown": [{"date":td,"buys":v["buys"],"sells":v["sells"],"win_rate":round(v["wins"]/max(v["sells"],1)*100,1),"pnl":round(v["pnl"],2)} for td,v in sorted(daily_stats.items())],
            "sentiments": sentiments,
            "weekly_trend": weekly_trend,
        }

        return {"success": True, "data": _clean_mongo(result)}
    except Exception as e:
        logger.error(f"[REVIEW-WEEKLY] {e}")
        return {"success": True, "data": None, "message": str(e)}



@router.get("/review-monthly")
async def review_monthly(date: str = None):
    """P2: 月复盘 - 系统偏差+参数漂移+行为漂移+因子效果

    Args:
        date: 月内任一天, 自动计算该月范围
    """
    try:
        from core.managers import mongo_manager
        if not mongo_manager.is_initialized:
            return {"success": True, "data": None, "message": "MongoDB未初始化"}

        db = mongo_manager.db

        # 计算本月范围
        if date:
            month_start = date[:6] + "01"
            from datetime import datetime as dt
            d = dt.strptime(date, "%Y%m%d")
            if d.month == 12:
                month_end = f"{d.year+1}0101"
            else:
                month_end = f"{d.year}{d.month+1:02d}01"
            # 取上月末
            from datetime import datetime as dt, timedelta
            next_month = dt.strptime(month_end, "%Y%m%d")
            last_day = (next_month - timedelta(days=1)).strftime("%Y%m%d")
        else:
            from datetime import datetime as dt, timedelta
            today = dt.now()
            month_start = today.strftime("%Y%m01")
            if today.month == 12:
                next_m = dt(today.year+1, 1, 1)
            else:
                next_m = dt(today.year, today.month+1, 1)
            last_day = (next_m - timedelta(days=1)).strftime("%Y%m%d")

        # 月度统计
        sells = []
        async for doc in db["broker_orders"].find({"side":"sell","status":"filled","trade_date":{"$gte":month_start,"$lte":last_day}}):
            sells.append(doc)

        buys = []
        async for doc in db["broker_orders"].find({"side":"buy","status":"filled","trade_date":{"$gte":month_start,"$lte":last_day}}):
            buys.append(doc)

        total_sells = len(sells)
        total_wins = sum(1 for s in sells if (s.get("profit_pct") or 0) >= 0)
        total_pnl = sum(s.get("profit_pct",0) or 0 for s in sells)

        # 策略月度
        from collections import defaultdict
        strategy_stats = defaultdict(lambda: {"trades":0,"wins":0,"pnl":0,"positions":0})
        for s in sells:
            strat = _norm_strat(s.get("strategy","") or "unknown")
            strategy_stats[strat]["trades"] += 1
            if (s.get("profit_pct") or 0) >= 0:
                strategy_stats[strat]["wins"] += 1
            strategy_stats[strat]["pnl"] += s.get("profit_pct",0) or 0

        # 行为漂移: 止损执行率、冰点开仓率
        # 止损执行率分两种视角:
        # 1) 止损命中率 = 止损卖出中真正亏损的比例 (stop_loss_at_loss / stop_loss_sells)
        # 2) 止损执行力 = 亏损卖出中走了止损的比例 (stop_loss_at_loss / loss_sells)
        #    → 这反映"亏损时止损纪律的执行情况"
        # 3) 更准确的执行力 = 止损执行 / 应止损数(含跳过/延迟)
        #    → 需要audit_log数据,暂时用(2)但修正计算
        stop_loss_sells = sum(1 for s in sells if "止损" in (s.get("reason","")))
        # 区分: 真正亏损止损 vs 盈利止损(冲高回落触发追踪止损但实际盈利)
        stop_loss_at_loss = sum(1 for s in sells if "止损" in (s.get("reason","")) and (s.get("profit_pct") or 0) < 0)
        stop_loss_at_profit = sum(1 for s in sells if "止损" in (s.get("reason","")) and (s.get("profit_pct") or 0) >= 0)
        loss_sells = sum(1 for s in sells if (s.get("profit_pct") or 0) < 0)
        # 非止损亏损卖出(应止损但没走止损 → 止损纪律问题)
        loss_without_stop = sum(1 for s in sells if (s.get("profit_pct") or 0) < 0 and "止损" not in (s.get("reason","")))
        # 止损执行率 = 实际止损卖出 / (止损卖出 + 非止损亏损卖出)
        # = 亏损走止损的 / 全部亏损的 (止损纪律覆盖率)
        # 注意: 分母不是loss_sells, 而是stop_loss_at_loss + loss_without_stop
        # loss_sells = stop_loss_at_loss + loss_without_stop, 所以结果一样
        # 但计算>100%的bug来自: 追踪止损在盈利时触发也算"止损"
        # 修正: 执行率只看亏损场景

        # 冰点期开仓
        sentiment_map = {}
        _en_to_cn = {"RISING": "高潮", "DIFFERENTIATION": "分化", "CHAOS": "震荡", "BEARISH": "冰点", "rising": "高潮", "differentiation": "分化", "chaos": "震荡", "bearish": "冰点"}
        async for doc in db["sentiment_scores"].find({"trade_date":{"$gte":int(month_start),"$lte":int(last_day)}},{"trade_date":1,"period":1,"score":1}):
            raw_p = doc.get("period","")
            cn_p = _en_to_cn.get(raw_p, raw_p)
            sentiment_map[str(doc.get("trade_date",""))] = {"period":cn_p,"score":doc.get("score",50)}

        bearish_buys = 0
        for b in buys:
            td = b.get("trade_date","")
            if sentiment_map.get(td,{}).get("period") == "冰点":
                bearish_buys += 1

        # 参数漂移
        drift_data = None
        try:
            drift_resp = await param_drift(month_start, last_day)
            drift_data = drift_resp.get("data")
        except Exception: pass

        # 大盘表现
        index_data = []
        async for doc in db["index_daily"].find({"ts_code":"000001.SH","trade_date":{"$gte":int(month_start),"$lte":int(last_day)}},{"trade_date":1,"close":1,"pct_chg":1}).sort("trade_date",1):
            index_data.append({"date":str(doc["trade_date"]),"close":round(doc.get("close",0),2),"pct_chg":round(doc.get("pct_chg",0),2)})

        # 逐日breakdown
        daily_breakdown = []
        from collections import defaultdict as _dd
        daily_sells_map = _dd(list)
        daily_buys_map = _dd(list)
        for s in sells:
            daily_sells_map[str(s.get("trade_date",""))].append(s)
        for b in buys:
            daily_buys_map[str(b.get("trade_date",""))].append(b)

        all_dates = sorted(set(list(daily_sells_map.keys()) + list(daily_buys_map.keys())))
        for td in all_dates:
            ds = daily_sells_map.get(td, [])
            db_ = daily_buys_map.get(td, [])
            d_wins = sum(1 for s in ds if (s.get("profit_pct") or 0) >= 0)
            d_pnl = sum(s.get("profit_pct", 0) or 0 for s in ds)
            d_strat = _dd(lambda: {"trades":0,"wins":0,"pnl":0})
            for s in ds:
                st = _norm_strat(s.get("strategy","") or "unknown")
                d_strat[st]["trades"] += 1
                if (s.get("profit_pct") or 0) >= 0: d_strat[st]["wins"] += 1
                d_strat[st]["pnl"] += s.get("profit_pct",0) or 0
            sent = sentiment_map.get(td, {})
            daily_breakdown.append({
                "date": td, "trades": len(ds), "buys": len(db_), "sells": len(ds),
                "wins": d_wins,  # 原始胜笔数,供weekly_trend精确计算
                "win_rate": round(d_wins / max(len(ds), 1) * 100, 1),
                "pnl": round(d_pnl, 2),
                "strategy_stats": {k: {"trades":v["trades"],"win_rate":round(v["wins"]/max(v["trades"],1)*100,1),"pnl":round(v["pnl"],2)} for k,v in d_strat.items()},
                "sentiment": sent.get("period", ""), "sentiment_score": sent.get("score", 0),
            })

        # 周趋势(近4周)
        weekly_trend = []
        if daily_breakdown:
            from itertools import groupby as _gb
            import datetime as _dt2
            def _week_key(d):
                try:
                    dt2 = _dt2.datetime.strptime(d["date"], "%Y%m%d")
                    return dt2.strftime("%Y-W%W")
                except: return d["date"][:6]
            for wk, grp in _gb(daily_breakdown, key=_week_key):
                g = list(grp)
                w_trades = sum(d["trades"] for d in g)
                w_wins = sum(d.get("wins", round(d["win_rate"]/100*d["trades"])) for d in g)  # 优先用原始wins
                w_pnl = sum(d["pnl"] for d in g)
                weekly_trend.append({
                    "week": wk, "start": g[0]["date"], "end": g[-1]["date"],
                    "trades": w_trades, "win_rate": round(w_wins/max(w_trades,1)*100,1),
                    "pnl": round(w_pnl, 2), "days": len(g),
                })

        result = {
            "period": f"{month_start}~{last_day}",
            "summary": {"trades":total_sells,"wins":total_wins,"win_rate":round(total_wins/max(total_sells,1)*100,1),"pnl":round(total_pnl,2)},
            "strategy_stats": {k: {"trades":v["trades"],"win_rate":round(v["wins"]/max(v["trades"],1)*100,1),"pnl":round(v["pnl"],2)} for k,v in strategy_stats.items()},
            "behavior_drift": {
                "stop_loss_execution_rate": round(stop_loss_at_loss/max(loss_sells,1)*100,1),
                "stop_loss_at_loss": stop_loss_at_loss, "stop_loss_at_profit": stop_loss_at_profit,
                "stop_loss_triggered": stop_loss_sells,  # 止损触发笔数(含盈利时追踪止损)
                "loss_sells": loss_sells,
                "loss_without_stop": loss_without_stop,  # 未走止损的亏损笔数
                "bearish_period_buy_ratio": round(bearish_buys/max(len(buys),1)*100,1),
                "bearish_buys": bearish_buys, "total_buys": len(buys),
            },
            "daily_breakdown": daily_breakdown,
            "weekly_trend": weekly_trend,
            "param_drift": drift_data,
            "index_performance": index_data,
        }

        return {"success": True, "data": _clean_mongo(result)}
    except Exception as e:
        logger.error(f"[REVIEW-MONTHLY] {e}")
        return {"success": True, "data": None, "message": str(e)}



@router.get("/factor-effectiveness")
async def factor_effectiveness(date: str = None):
    from core.managers import mongo_manager
    """因子效果跟踪: 不同情绪阶段下各因子的胜率/盈亏变化(市场漂移检测)"""
    try:
        if not date:
            date = datetime.now().strftime("%Y%m%d")

        if not mongo_manager.is_initialized:
            return {"success": False, "message": "MongoDB未初始化"}

        db = mongo_manager.db

        # 最近30天
        end_date = int(date)
        start_date = end_date - 30

        # 1. 加载情绪数据
        sentiment_map = {}  # date -> {score, period}
        async for doc in db["sentiment_scores"].find(
            {"trade_date": {"$gte": start_date, "$lte": end_date}},
            {"_id": 0, "trade_date": 1, "score": 1, "period": 1}
        ):
            td = str(doc.get("trade_date", ""))
            raw_p = doc.get("period", "震荡")
            _en_to_cn = {"RISING": "高潮", "DIFFERENTIATION": "分化", "CHAOS": "震荡", "BEARISH": "冰点", "rising": "高潮", "differentiation": "分化", "chaos": "震荡", "bearish": "冰点"}
            cn_p = _en_to_cn.get(raw_p, raw_p)
            sentiment_map[td] = {"score": doc.get("score", 50), "period": cn_p}

        # 2. 加载scan_traces候选(含因子数据)
        factor_stats = {}  # factor_name -> {period -> {total, wins, avg_pnl}}
        factor_names = ["量比", "涨幅", "换手率", "连板数"]

        # 用scan_traces中passed的候选和对应实盘结果
        trace_dates = set()
        async for doc in db["scan_traces"].find(
            {"trade_date": {"$gte": str(start_date), "$lte": str(end_date)}},
            {"_id": 0, "candidates": 1, "trade_date": 1}
        ):
            td = doc.get("trade_date", "")
            trace_dates.add(td)
            period = sentiment_map.get(td, {}).get("period", "未知")

            for c in doc.get("candidates", []):
                if c.get("final_status") != "passed":
                    continue

                # 提取因子值(粗略用pct_chg和价格区间)
                pct_chg = c.get("pct_chg", 0) or 0
                price = c.get("price", 0) or 0
                strategy = c.get("strategy", "")

                # 因子分组(v2.9.84增强: 新增换手率/量比因子)
                turnover = c.get("turnover_rate", 0) or 0
                vol_ratio = c.get("vol_ratio", 0) or 0
                momentum_bucket = "弱(<2%)" if abs(pct_chg) < 2 else ("中(2-5%)" if abs(pct_chg) < 5 else "强(>5%)")
                gain_bucket = "小涨(<2%)" if pct_chg < 2 else ("中涨(2-5%)" if pct_chg < 5 else "大涨(>5%)")
                turnover_bucket = "低(<3%)" if turnover < 3 else ("中(3-8%)" if turnover < 8 else "高(>8%)") if turnover > 0 else "未知"
                vol_ratio_bucket = "缩量(<0.8)" if vol_ratio < 0.8 else ("正常(0.8-1.5)" if vol_ratio < 1.5 else "放量(>1.5)") if vol_ratio > 0 else "未知"
                strat_name = _norm_strat(strategy) if strategy else "unknown"

                for fname, bucket in [("动量强度", momentum_bucket), ("涨幅区间", gain_bucket),
                                       ("换手率", turnover_bucket), ("量比", vol_ratio_bucket),
                                       ("策略", strat_name)]:
                    if fname not in factor_stats:
                        factor_stats[fname] = {}
                    if period not in factor_stats[fname]:
                        factor_stats[fname][period] = {}
                    if bucket not in factor_stats[fname][period]:
                        factor_stats[fname][period][bucket] = {"total": 0, "wins": 0, "pnl_sum": 0}
                    factor_stats[fname][period][bucket]["total"] += 1

        # 【v2.9.86修复】broker_orders.trade_date是int，scan_traces是string
        start_str = str(start_date)
        end_str = str(end_date)

        # 3. 用broker_orders的买入和后续卖出结果来补充胜率
        # 简化: 用scan_traces候选的pct_chg作为近似
        buys_by_date = {}  # date -> {ts_code -> {strategy, pct_chg}}
        async for doc in db["broker_orders"].find(
            {"side": "buy", "status": "filled", "trade_date": {"$gte": start_date, "$lte": end_date}},
            {"_id": 0, "trade_date": 1, "ts_code": 1, "strategy": 1, "filled_price": 1}
        ):
            td = doc.get("trade_date", "")
            if td not in buys_by_date:
                buys_by_date[td] = {}
            buys_by_date[td][doc.get("ts_code", "")] = {
                "strategy": doc.get("strategy", ""),
                "price": doc.get("filled_price", 0)
            }

        # 用卖出profit_pct来算胜率
        sells_by_buy = {}  # (date, ts_code) -> profit_pct
        async for doc in db["broker_orders"].find(
            {"side": "sell", "status": "filled", "trade_date": {"$gte": start_date, "$lte": end_date}},
            {"_id": 0, "trade_date": 1, "ts_code": 1, "strategy": 1, "profit_pct": 1, "reason": 1}
        ):
            sells_by_buy[(doc.get("trade_date", ""), doc.get("ts_code", ""))] = doc.get("profit_pct", 0) or 0

        # 4. 补充因子胜率(用实际买卖结果)
        for td, codes in buys_by_date.items():
            period = sentiment_map.get(td, {}).get("period", "未知")
            for ts, info in codes.items():
                pnl = sells_by_buy.get((td, ts), None)
                if pnl is None:
                    continue

                strat = info.get("strategy", "") or "unknown"
                price = info.get("price", 0)

                # 因子分组
                for fname, bucket in [("策略", strat)]:
                    if fname not in factor_stats:
                        factor_stats[fname] = {}
                    if period not in factor_stats[fname]:
                        factor_stats[fname][period] = {}
                    if bucket not in factor_stats[fname][period]:
                        factor_stats[fname][period][bucket] = {"total": 0, "wins": 0, "pnl_sum": 0}
                    factor_stats[fname][period][bucket]["total"] += 1
                    if pnl > 0:
                        factor_stats[fname][period][bucket]["wins"] += 1
                    factor_stats[fname][period][bucket]["pnl_sum"] += pnl

        # 5. 计算胜率
        result = {}
        for fname, periods in factor_stats.items():
            result[fname] = {}
            for period, buckets in periods.items():
                result[fname][period] = []
                for bucket, stats in buckets.items():
                    total = stats["total"]
                    wins = stats["wins"]
                    avg_pnl = round(stats["pnl_sum"] / max(total, 1), 2)
                    wr = round(wins / max(total, 1) * 100, 1)
                    result[fname][period].append({
                        "name": bucket, "total": total, "wins": wins,
                        "win_rate": wr, "avg_pnl": avg_pnl,
                    })
                result[fname][period].sort(key=lambda x: x["total"], reverse=True)

        # 6. 市场漂移检测: 同一因子在不同阶段的胜率变化
        drift_alerts = []
        for fname, periods in factor_stats.items():
            if len(periods) < 2:
                continue
            all_buckets = set()
            for p_data in periods.values():
                all_buckets.update(p_data.keys())
            for bucket in all_buckets:
                wrs = {}
                for p, p_data in periods.items():
                    if bucket in p_data and p_data[bucket]["total"] >= 3:
                        wrs[p] = round(p_data[bucket]["wins"] / p_data[bucket]["total"] * 100, 1)
                if len(wrs) >= 2:
                    values = list(wrs.values())
                    spread = max(values) - min(values)
                    if spread > 20:  # 胜率差>20%说明市场漂移明显
                        drift_alerts.append({
                            "factor": fname, "bucket": bucket,
                            "detail": wrs, "spread": round(spread, 1),
                            "alert": f"{bucket}在不同情绪阶段胜率差{spread:.0f}%,市场漂移明显",
                        })

        # 7. 按周时间趋势: 各因子在不同周的效果变化(v2.9.86增强)
        weekly_trend = {}  # factor_name -> [{week, win_rate, total, avg_pnl}]
        # 按周分组: 每7天一组
        date_int = int(date)
        week_boundaries = []
        for w in range(4):  # 最近4周
            w_end = date_int - w * 7
            w_start = w_end - 6
            week_boundaries.append((w_start, w_end, f"W{4-w}"))

        for fname, periods in factor_stats.items():
            if fname not in weekly_trend:
                weekly_trend[fname] = []
            for w_start, w_end, w_label in week_boundaries:
                w_total = 0
                w_wins = 0
                w_pnl = 0
                for period, buckets in periods.items():
                    for bucket, stats in buckets.items():
                        w_total += stats["total"]
                        w_wins += stats["wins"]
                        w_pnl += stats["pnl_sum"]
                if w_total > 0:
                    weekly_trend[fname].append({
                        "week": w_label,
                        "win_rate": round(w_wins / w_total * 100, 1),
                        "total": w_total,
                        "avg_pnl": round(w_pnl / w_total, 2),
                    })

        # 8. 因子衰减检测: 胜率连续2周下降的因子
        decay_alerts = []
        for fname, weeks in weekly_trend.items():
            if len(weeks) >= 3:
                # 按周排序(从早到晚)
                sorted_weeks = sorted(weeks, key=lambda x: x["week"])
                # 检查最近2-3周是否持续下降
                recent = sorted_weeks[-3:]
                if (len(recent) >= 3
                    and recent[-1]["win_rate"] < recent[-2]["win_rate"]
                    and recent[-2]["win_rate"] < recent[-3]["win_rate"]
                    and recent[-3]["total"] >= 3):
                    decay_alerts.append({
                        "factor": fname,
                        "trend": [f"{w['week']}:{w['win_rate']}%({w['total']}笔)" for w in recent],
                        "drop": round(recent[-3]["win_rate"] - recent[-1]["win_rate"], 1),
                        "alert": f"{fname}胜率连续3周下降({recent[-3]['win_rate']}%→{recent[-1]['win_rate']}%),可能因子衰减",
                        "action": "建议降低该因子权重或暂停使用,回测验证后决定",
                    })

        return {
            "success": True,
            "data": {
                "factor_stats": result,
                "drift_alerts": drift_alerts,
                "weekly_trend": weekly_trend,
                "decay_alerts": decay_alerts,
                "date_range": f"{start_date}~{end_date}",
                "sentiment_days": len(sentiment_map),
            }
        }
    except Exception as e:
        logger.error(f"[FACTOR-EFFECTIVENESS] {e}")
        return {"success": True, "data": None, "message": str(e)}



@router.get("/review-closed-loop")
async def review_closed_loop(date: str = None):
    from core.managers import mongo_manager
    """闭环建议: 基于偏差归因自动生成参数调整建议和验证方案"""
    try:
        if not date:
            date = datetime.now().strftime("%Y%m%d")

        if not mongo_manager.is_initialized:
            return {"success": False, "message": "MongoDB未初始化"}

        db = mongo_manager.db

        # 1. 获取偏差归因数据
        int_date = int(date)
        end_d = int(date)
        start_d = end_d - 13  # 最近2周

        # 加载情绪
        sentiment_map = {}
        _en_to_cn = {"RISING": "高潮", "DIFFERENTIATION": "分化", "CHAOS": "震荡", "BEARISH": "冰点", "rising": "高潮", "differentiation": "分化", "chaos": "震荡", "bearish": "冰点"}
        async for doc in db["sentiment_scores"].find(
            {"trade_date": {"$gte": start_d, "$lte": end_d}},
            {"_id": 0, "trade_date": 1, "score": 1, "period": 1}
        ):
            td = str(doc.get("trade_date", ""))
            raw_p = doc.get("period", "")
            cn_p = _en_to_cn.get(raw_p, raw_p)
            doc["period"] = cn_p  # 统一为中文
            sentiment_map[td] = doc

        # 加载买卖数据
        buys = []
        sells = []
        async for doc in db["broker_orders"].find(
            {"status": "filled", "trade_date": {"$gte": str(start_d), "$lte": str(end_d)}},
            {"_id": 0, "side": 1, "strategy": 1, "ts_code": 1, "stock_name": 1,
             "filled_price": 1, "profit_pct": 1, "reason": 1, "trade_date": 1, "create_time": 1}
        ):
            if doc.get("side") == "buy":
                buys.append(doc)
            else:
                sells.append(doc)

        # 2. 诊断偏差
        suggestions = []

        # 2a. 纪律偏差 → 止损/止盈建议
        sl_sells = [s for s in sells if "止损" in (s.get("reason", "")) and (s.get("profit_pct") or 0) < 0]
        loss_sells = [s for s in sells if (s.get("profit_pct") or 0) < 0]
        if loss_sells:
            sl_rate = len(sl_sells) / len(loss_sells) * 100
            if sl_rate < 80:
                # 找出亏损最深但没止损的
                non_sl_loss = [s for s in loss_sells if "止损" not in (s.get("reason", ""))]
                non_sl_loss.sort(key=lambda x: x.get("profit_pct", 0))
                worst = non_sl_loss[:3] if non_sl_loss else []
                suggestions.append({
                    "type": "止损纪律",
                    "severity": "high" if sl_rate < 60 else "medium",
                    "diagnosis": f"止损执行率仅{sl_rate:.0f}%({len(sl_sells)}/{len(loss_sells)})",
                    "action": "收紧止损触发条件,将next_day_open_sell_pct从当前值降低0.5-1%",
                    "verification": "同区间回测验证:调整后止损执行率应>85%,且总收益不降",
                    "worst_cases": [{"ts_code": w.get("ts_code"), "name": w.get("stock_name"), "pnl": w.get("profit_pct")} for w in worst],
                })

        # 2b. 情绪偏差 → 仓位调整建议
        bearish_buys = [b for b in buys if sentiment_map.get(b.get("trade_date", ""), {}).get("period") == "冰点"]
        if len(buys) > 0 and len(bearish_buys) / len(buys) > 0.5:
            bearish_wr = len([s for s in sells if s.get("profit_pct", 0) > 0 and sentiment_map.get(s.get("trade_date", ""), {}).get("period") == "冰点"]) / max(len([s for s in sells if sentiment_map.get(s.get("trade_date", ""), {}).get("period") == "冰点"]), 1) * 100
            suggestions.append({
                "type": "情绪仓位",
                "severity": "high",
                "diagnosis": f"冰点期开仓率{len(bearish_buys)/len(buys)*100:.0f}%,冰点期胜率{bearish_wr:.0f}%",
                "action": "建议冰点期仓位系数从0.3降至0.1,或信号管道L3增加全策略冰点过滤",
                "verification": "同区间回测:冰点期仓位0.1 vs 0.3的收益对比",
            })

        # 2c. 策略偏差 → 策略参数建议
        strat_stats = {}
        for s in sells:
            strat = _norm_strat(s.get("strategy", "") or "unknown")
            if strat not in strat_stats:
                strat_stats[strat] = {"trades": 0, "wins": 0, "pnl": 0}
            strat_stats[strat]["trades"] += 1
            if (s.get("profit_pct") or 0) > 0:
                strat_stats[strat]["wins"] += 1
            strat_stats[strat]["pnl"] += (s.get("profit_pct") or 0)

        for strat, stats in strat_stats.items():
            if stats["trades"] >= 5:
                wr = stats["wins"] / stats["trades"] * 100
                avg_pnl = stats["pnl"] / stats["trades"]
                if wr < 50 and avg_pnl < 0:
                    cn_name = {"halfway_chase": "半路追涨", "limit_down_qiao": "跌停翘板", "dragon_head": "龙头低吸", "first_limit_up": "首板打板"}.get(strat, strat)
                    suggestions.append({
                        "type": "策略表现",
                        "severity": "medium",
                        "diagnosis": f"{cn_name}近2周WR={wr:.0f}% 均盈亏={avg_pnl:.2f}%",
                        "action": f"考虑暂停{cn_name}或收紧选股条件(提高流动性门槛/缩小涨幅范围)",
                        "verification": f"回测对比:{cn_name}收紧条件前后的WR和收益",
                    })

        # 2d. 滑点偏差 → 执行优化
        slippage_list = []
        for buy in buys:
            td = buy.get("trade_date", "")
            ts = buy.get("ts_code", "")
            fill_price = buy.get("filled_price", 0) or 0
            # 从scan_traces找信号价
            if fill_price > 0:
                # 简化: 用当天最高价和成交价差来估算
                slippage_list.append(fill_price)

        # 2e. 参数漂移建议
        try:
            latest_snap = await db["param_snapshots"].find_one(sort=[("date", -1)])
            if latest_snap:
                snap_date = latest_snap.get("date", "")
                if snap_date != date:
                    suggestions.append({
                        "type": "参数漂移",
                        "severity": "low",
                        "diagnosis": f"最新参数快照是{snap_date},与当前日期{date}不一致",
                        "action": "建议更新参数快照以确保漂移检测准确",
                        "verification": "点击📸保存当前参数快照",
                    })
        except Exception:
            pass

        # 3. 优先级排序
        severity_order = {"high": 0, "medium": 1, "low": 2}
        suggestions.sort(key=lambda x: severity_order.get(x.get("severity", "low"), 2))

        return {
            "success": True,
            "data": {
                "suggestions": suggestions,
                "summary": {
                    "total": len(suggestions),
                    "high": len([s for s in suggestions if s.get("severity") == "high"]),
                    "medium": len([s for s in suggestions if s.get("severity") == "medium"]),
                    "low": len([s for s in suggestions if s.get("severity") == "low"]),
                },
                "date_range": f"{start_d}~{end_d}",
            }
        }
    except Exception as e:
        logger.error(f"[REVIEW-CLOSED-LOOP] {e}")
        return {"success": True, "data": None, "message": str(e)}


