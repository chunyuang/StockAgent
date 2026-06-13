#!/usr/bin/env python3
"""日内情绪时间线 - 新版多指标展示
v2.9.92: 从单一的candidates/passed线改为3指标分区展示:
  1. 涨停/跌停柱状图(5分钟采样)
  2. 涨跌家数比面积图
  3. 情绪score参考(日线值)
  
数据源: scan_traces集合, 解析L1/L3层文本获取涨跌停数和情绪分
"""
import asyncio
import re
import math
from collections import OrderedDict
from typing import Dict, List, Any, Optional


def _parse_l1_limit_counts(l1_text: str) -> Dict[str, int]:
    """从L1_force_empty文本解析涨跌停数"""
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
    """从scan_trace解析L3情绪数据"""
    ld = doc.get("layer_details", {})
    l3d = ld.get("L3_sentiment_data", {})
    l3t = ld.get("L3_sentiment", "")
    
    score = l3d.get("score", 0)
    period = l3d.get("period", "")
    position_ratio = l3d.get("position_ratio", 0)
    
    # 如果L3_sentiment_data没有score，从文本解析
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
    }


def _aggregate_to_buckets(
    raw_points: List[Dict],
    bucket_minutes: int = 5,
) -> List[Dict]:
    """将原始时间点聚合为N分钟桶, 减少数据量并使图表可读
    
    每个桶取:
    - 最后一个点的score(代表该时段收盘情绪)
    - max(limit_up), max(limit_down)(代表该时段峰值)
    - 桶内点数(反映扫描频率)
    """
    if not raw_points:
        return []
    
    bucket_ms = bucket_minutes * 60 * 1000
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
            # 向下取整到bucket边界
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
            }
        
        b = buckets[bucket_key]
        b["points"].append(p)
        b["limit_up_max"] = max(b["limit_up_max"], p.get("limit_up", 0))
        b["limit_down_max"] = max(b["limit_down_max"], p.get("limit_down", 0))
    
    # 从每个桶生成聚合点
    result = []
    for key, b in buckets.items():
        pts = b["points"]
        if not pts:
            continue
        
        # score取最后一个(代表该时段收盘情绪)
        last_pt = pts[-1]
        # limit_up/down取max(峰值更有意义)
        result.append({
            "time": last_pt["time"],  # 用桶内最后一个时间点
            "time_label": key[11:],   # HH:MM 格式
            "score": last_pt.get("score"),
            "period": last_pt.get("period", ""),
            "limit_up": b["limit_up_max"],
            "limit_down": b["limit_down_max"],
            "scan_count": len(pts),  # 该时段扫描次数
        })
    
    return result


async def get_intraday_timeline(db, date: str) -> Dict[str, Any]:
    """获取日内情绪时间线数据(新版: 多指标)"""
    
    # 1. 收集所有scan_traces, 解析涨跌停+情绪
    raw_points = []
    async for doc in db["scan_traces"].find(
        {"trade_date": int(date)},
        {"scan_time": 1, "layer_details": 1, "summary": 1, "is_debug": 1}
    ).sort("scan_time", 1):
        l1_text = doc.get("layer_details", {}).get("L1_force_empty", "")
        l3 = _parse_l3_data(doc)
        l1 = _parse_l1_limit_counts(l1_text)
        
        raw_points.append({
            "time": doc.get("scan_time", "")[:19],
            "score": l3["score"],
            "period": l3["period"],
            "position_ratio": l3["position_ratio"],
            "limit_up": l1["limit_up"],
            "limit_down": l1["limit_down"],
            "candidates": doc.get("summary", {}).get("total_candidates", 0),
            "passed": doc.get("summary", {}).get("passed", 0),
            "is_debug": doc.get("is_debug", False),
        })
    
    if not raw_points:
        return {"points": [], "trades": []}
    
    # 2. 聚合为5分钟桶
    points = _aggregate_to_buckets(raw_points, bucket_minutes=5)
    
    # 3. 计算涨跌家数比(从score反推, 或从limit_stocks)
    # 目前的scan_traces没有直接存up_down_ratio
    # 用一个近似: 从涨停/跌停数和score反推
    # score ≈ min(30,lu) + max(0,20-ld*2) + min(20,lb*2) + up_down_ratio*15 + min(15,premium)
    # 简化: 如果有up_down_ratio数据直接用,否则从limit_up/(limit_up+limit_down+1)近似
    for p in points:
        lu = p.get("limit_up", 0)
        ld = p.get("limit_down", 0)
        total = lu + ld
        if total > 0:
            # 涨跌停比例(0-1), 这是涨跌停层面的强弱比
            p["limit_ratio"] = round(lu / (lu + ld), 3) if total > 0 else 0.5
        else:
            p["limit_ratio"] = 0.5
    
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
