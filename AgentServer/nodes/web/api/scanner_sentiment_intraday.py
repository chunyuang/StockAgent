#!/usr/bin/env python3
"""日内情绪时间线 - 新版多指标展示
v2.9.95: 重构数据解析, 优先读取L3_sentiment_data结构化字段
  1. 涨停/跌停柱状图(5分钟采样)
  2. 涨跌家数比+加速度面积图
  3. 情绪score+开板率参考线
  
数据源: scan_traces集合
  - 新数据(v2.9.95+): L3_sentiment_data含结构化维度数据(7维)
  - 旧数据: 从L1_force_empty文本+L3_sentiment文本正则解析
"""

import asyncio
import re
import math
from collections import OrderedDict
from typing import Dict, List, Any, Optional


def _parse_l1_limit_counts(l1_text: str) -> Dict[str, int]:
    """从L1_force_empty文本解析涨跌停数(fallback, 旧数据用)"""
    result = {"limit_up": 0, "limit_down": 0}
    if not l1_text:
        return result
    m = re.search(r'涨停(\d+)只', l1_text)
    if m:
        result["limit_up"] = int(m.group(1))
    m = re.search(r'跌停(\d+)只', l1_text)
    if m:
        result["limit_down"] = int(m.group(1))
    return result


def _parse_l3_data(doc: dict) -> Dict[str, Any]:
    """从scan_trace解析L3情绪数据 — 优先读结构化字段, fallback文本解析
    
    v2.9.95: 新数据L3_sentiment_data含完整维度:
      score, period, position_ratio, formula,
      limit_up, limit_down, up_down_ratio, momentum,
      broken, broken_rate, today_premium
    """
    ld = doc.get("layer_details", {})
    l3d = ld.get("L3_sentiment_data", {})
    l3t = ld.get("L3_sentiment", "")
    
    # 优先从结构化字段读取
    score = l3d.get("score", 0)
    period = l3d.get("period", "")
    position_ratio = l3d.get("position_ratio", 0)
    formula = l3d.get("formula", "")
    
    # 结构化维度(v2.9.95新增)
    limit_up = l3d.get("limit_up", 0)
    limit_down = l3d.get("limit_down", 0)
    up_down_ratio = l3d.get("up_down_ratio", 0)
    momentum = l3d.get("momentum", 0)
    broken = l3d.get("broken", 0)
    broken_rate = l3d.get("broken_rate", 0)
    today_premium = l3d.get("today_premium", 0)
    
    # 如果结构化字段无score, 从文本fallback
    if not score and l3t:
        m = re.search(r'情绪=([\\d.]+)分', l3t)
        if m:
            score = float(m.group(1))
        m2 = re.search(r'仓位系数=([\\d.]+)', l3t)
        if m2:
            position_ratio = float(m2.group(1))
        m3 = re.search(r'→(高潮|分化|震荡|冰点)', l3t)
        if m3:
            period = m3.group(1)
    
    return {
        "score": round(score, 1) if score else None,
        "period": period,
        "position_ratio": position_ratio,
        "formula": formula,
        "limit_up": limit_up,
        "limit_down": limit_down,
        "up_down_ratio": up_down_ratio,
        "momentum": momentum,
        "broken": broken,
        "broken_rate": broken_rate,
        "today_premium": today_premium,
    }


def _aggregate_to_buckets(
    raw_points: List[Dict],
    bucket_minutes: int = 5,
) -> List[Dict]:
    """将原始时间点聚合为N分钟桶, 减少数据量并使图表可读
    
    每个桶取:
    - 最后一个点的score/period(代表该时段收盘情绪)
    - max(limit_up), max(limit_down)(代表该时段峰值)
    - 最后一个点的up_down_ratio/momentum(代表收盘时状态)
    - 桶内点数(反映扫描频率)
    """
    if not raw_points:
        return []
    
    buckets: OrderedDict[str, Dict] = OrderedDict()
    
    for p in raw_points:
        if p.get("is_debug"):
            continue
        
        time_str = p.get("time", "")
        if len(time_str) < 16:
            continue
        
        # 计算桶key: 截断到bucket_minutes分钟
        try:
            hour = int(time_str[11:13])
            minute = int(time_str[14:16])
            bucket_start_min = (minute // bucket_minutes) * bucket_minutes
            bucket_key = f"{time_str[:11]}{hour:02d}:{bucket_start_min:02d}"
        except (ValueError, IndexError):
            continue
        
        if bucket_key not in buckets:
            buckets[bucket_key] = {
                "bucket_time": bucket_key,
                "points": [],
                "limit_up_max": 0,
                "limit_down_max": 0,
                "broken_max": 0,
            }
        
        b = buckets[bucket_key]
        b["points"].append(p)
        b["limit_up_max"] = max(b["limit_up_max"], p.get("limit_up", 0))
        b["limit_down_max"] = max(b["limit_down_max"], p.get("limit_down", 0))
        b["broken_max"] = max(b["broken_max"], p.get("broken", 0))
    
    # 从每个桶生成聚合点
    result = []
    for key, b in buckets.items():
        pts = b["points"]
        if not pts:
            continue
        
        # score/period/up_down_ratio/momentum取最后一个(代表该时段收盘情绪)
        last_pt = pts[-1]
        result.append({
            "time": last_pt["time"],
            "time_label": key[11:],
            "score": last_pt.get("score"),
            "period": last_pt.get("period", ""),
            "formula": last_pt.get("formula", ""),
            "limit_up": b["limit_up_max"],         # 峰值涨停数
            "limit_down": b["limit_down_max"],      # 峰值跌停数
            "broken": b["broken_max"],              # 峰值炸板数
            "up_down_ratio": last_pt.get("up_down_ratio", 0),    # 收盘时涨跌比
            "momentum": last_pt.get("momentum", 0),              # 收盘时加速度
            "broken_rate": last_pt.get("broken_rate", 0),        # 收盘时开板率
            "today_premium": last_pt.get("today_premium", 0),    # 收盘时溢价
            "scan_count": len(pts),
        })
    
    return result


async def get_intraday_timeline(db, date: str) -> Dict[str, Any]:
    """获取日内情绪时间线数据(新版: 多指标+结构化维度)"""
    
    # 1. 收集所有scan_traces, 解析涨跌停+情绪
    raw_points = []
    async for doc in db["scan_traces"].find(
        {"trade_date": int(date)},
        {"scan_time": 1, "layer_details": 1, "summary": 1, "is_debug": 1}
    ).sort("scan_time", 1):
        l1_text = doc.get("layer_details", {}).get("L1_force_empty", "")
        l3 = _parse_l3_data(doc)
        
        # v2.9.95: 优先用L3_sentiment_data的涨跌停数, fallback到L1文本解析
        limit_up = l3.get("limit_up", 0)
        limit_down = l3.get("limit_down", 0)
        if limit_up == 0 and limit_down == 0:
            l1 = _parse_l1_limit_counts(l1_text)
            limit_up = l1["limit_up"]
            limit_down = l1["limit_down"]
        
        raw_points.append({
            "time": doc.get("scan_time", "")[:19],
            "score": l3["score"],
            "period": l3["period"],
            "position_ratio": l3["position_ratio"],
            "formula": l3.get("formula", ""),
            "limit_up": limit_up,
            "limit_down": limit_down,
            "up_down_ratio": l3.get("up_down_ratio", 0),
            "momentum": l3.get("momentum", 0),
            "broken": l3.get("broken", 0),
            "broken_rate": l3.get("broken_rate", 0),
            "today_premium": l3.get("today_premium", 0),
            "candidates": doc.get("summary", {}).get("total_candidates", 0),
            "passed": doc.get("summary", {}).get("passed", 0),
            "is_debug": doc.get("is_debug", False),
        })
    
    if not raw_points:
        return {"points": [], "trades": []}
    
    # 2. 聚合为5分钟桶
    points = _aggregate_to_buckets(raw_points, bucket_minutes=5)
    
    # 3. 补充limit_ratio(涨跌停层面的强弱比, 供前端柱状图使用)
    for p in points:
        lu = p.get("limit_up", 0)
        ld = p.get("limit_down", 0)
        total = lu + ld
        p["limit_ratio"] = round(lu / total, 3) if total > 0 else 0.5
    
    # 4. 获取当日交易记录
    trades = []
    date_int = int(date) if isinstance(date, str) and date.isdigit() else date
    async for doc in db["broker_orders"].find(
        {"trade_date": date_int, "status": "filled"},
        {"fill_time": 1, "side": 1, "ts_code": 1, "strategy": 1, 
         "filled_price": 1, "reason": 1, "profit_pct": 1}
    ).sort("fill_time", 1):
        if doc.get("side") in ("buy", "sell"):
            trades.append({
                "time": doc.get("fill_time", ""),
                "side": doc.get("side"),
                "ts_code": doc.get("ts_code", ""),
                "strategy": doc.get("strategy", ""),
                "price": doc.get("filled_price", 0),
                "reason": doc.get("reason", ""),
            })
    
    return {"points": points, "trades": trades, "raw_count": len(raw_points)}
