"""
回测日志查询 API

从本地 .jsonl 文件读取结构化日志，支持按天/策略/类型筛选。
"""

import os
import json
import logging
from fastapi import APIRouter, Query, HTTPException

logger = logging.getLogger(__name__)
router = APIRouter(tags=["backtest-logs"])

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))), 'logs', 'backtest')

@router.get("/logs/{task_id}")
async def get_backtest_logs(
    task_id: str,
    day: str = Query("all", description="交易日序号(1-based)或all"),
    strategy: str = Query(None, description="策略名筛选"),
    section: str = Query(None, description="日志类型: init/market/filter/trade/position/result/daily/other"),
    search: str = Query(None, description="全文搜索"),
    offset: int = Query(0, ge=0, description="分页偏移"),
    limit: int = Query(200, ge=1, le=2000, description="每页条数"),
    tail: int = Query(None, ge=1, le=500, description="只取末尾N条(与offset互斥)"),
    format: str = Query("json", description="json=结构化, raw=ANSI原文"),
):
    """查询回测日志 - 从本地.jsonl文件读取，支持筛选"""

    # 安全检查task_id，防止路径遍历
    if not task_id.replace('_', '').replace('-', '').isalnum():
        raise HTTPException(status_code=400, detail="Invalid task_id")

    jsonl_path = os.path.join(LOG_DIR, f"{task_id}.jsonl")

    # 如果.jsonl不存在，尝试从.log解析
    if not os.path.exists(jsonl_path):
        log_path = os.path.join(LOG_DIR, f"{task_id}.log")
        if os.path.exists(log_path):
            return await _parse_log_file(log_path, task_id, day, strategy, section, search, offset, limit, tail)
        raise HTTPException(status_code=404, detail=f"No logs found for task {task_id}")

    # 读取JSONL
    records = []
    try:
        with open(jsonl_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read log file: {e}")

    # 筛选
    filtered = records

    if day != "all":
        try:
            day_num = int(day)
            filtered = [r for r in filtered if r.get("day") == day_num]
        except ValueError:
            pass

    if strategy:
        filtered = [r for r in filtered if r.get("strategy") == strategy]

    if section:
        filtered = [r for r in filtered if r.get("section") == section]

    if search:
        search_lower = search.lower()
        filtered = [r for r in filtered if search_lower in r.get("text", "").lower()]

    # 构建天数索引
    days_info = []
    seen_days = {}
    for r in records:
        d = r.get("day", 0)
        if d > 0 and d not in seen_days:
            seen_days[d] = r.get("date", "")
            days_info.append({"day": d, "date": r.get("date", ""), "lines": 0})
        if d > 0:
            for di in days_info:
                if di["day"] == d:
                    di["lines"] += 1
                    break

    # tail模式
    if tail:
        filtered = filtered[-tail:]
        total = len(filtered)
        result_logs = filtered
    else:
        total = len(filtered)
        result_logs = filtered[offset:offset + limit]

    # format=raw时返回ANSI原文
    if format == "raw":
        raw_path = os.path.join(LOG_DIR, f"{task_id}.log")
        raw_lines = []
        if os.path.exists(raw_path):
            try:
                with open(raw_path, 'r', encoding='utf-8', errors='replace') as f:
                    all_lines = f.readlines()
                # 简单返回对应范围
                start = min(offset, len(all_lines))
                end = min(offset + limit, len(all_lines))
                raw_lines = [l.rstrip('\n') for l in all_lines[start:end]]
            except Exception:
                pass
        return {
            "task_id": task_id,
            "total_lines": len(all_lines) if os.path.exists(raw_path) else 0,
            "raw_lines": raw_lines,
        }

    return {
        "task_id": task_id,
        "total_lines": len(records),
        "filtered_total": total,
        "days": days_info,
        "strategies": list(set(r.get("strategy") for r in records if r.get("strategy"))),
        "sections": list(set(r.get("section") for r in records if r.get("section"))),
        "offset": offset if tail is None else None,
        "limit": limit,
        "logs": result_logs,
    }


async def _parse_log_file(log_path: str, task_id: str, day: str, strategy: str,
                           section: str, search: str, offset: int, limit: int,
                           tail: int) -> dict:
    """从.log文件解析日志（兼容旧格式，无.jsonl时使用）"""
    import re

    records = []
    current_day = 0
    current_date = ""

    with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            # 去ANSI
            clean = re.sub(r'\x1b\[[0-9;]*m', '', line)

            # 提取SEQ
            seq_match = re.search(r'SEQ:(\d+)', clean)
            seq = int(seq_match.group(1)) if seq_match else i

            # 提取时间
            time_match = re.search(r'\[(\d{2}:\d{2}:\d{2})\]', clean)
            time_str = time_match.group(1) if time_match else ""

            # 检测天数
            day_match = re.search(r'第\s*(\d+)/\d+\s*天', clean)
            if day_match:
                current_day = int(day_match.group(1))
            date_match = re.search(r'处理日期[:\s]*(\d{8})', clean)
            if date_match:
                current_date = date_match.group(1)

            # 分类
            sec = "other"
            if any(k in clean for k in ['🔧INIT', '代码版本', '回测任务启动', '全局参数', '功能开关']):
                sec = 'init'
            elif any(k in clean for k in ['🌡️', '涨跌停统计', '情绪周期评分', '大盘平均']):
                sec = 'market'
            elif any(k in clean for k in ['🔍', '📌', '🎯', '条件1', '条件2', '条件3', '条件4', '筛选过程', '参数配置', '最终候选']):
                sec = 'filter'
            elif any(k in clean for k in ['🔹 买入', '🔻 卖出', '📝', '调仓记录', '调仓操作']):
                sec = 'trade'
            elif any(k in clean for k in ['💵', '💼', '当日持仓', '现金剩余']):
                sec = 'position'
            elif any(k in clean for k in ['📈RESULT', '📊', '总计', '交易明细', '胜率', '收益率', '回撤', '夏普']):
                sec = 'result'
            elif any(k in clean for k in ['📅', '第', '天']):
                sec = 'daily'

            # 提取策略名
            strat = None
            for name in ['半路追涨', '首板打板', '涨停开板', '龙头低吸', '跌停翘板']:
                if f'【{name}】' in clean:
                    strat = name
                    break

            # 提取level
            level = "INFO"
            if '✅' in clean or '📈' in clean:
                level = "SUCCESS"
            elif '⚠️' in clean:
                level = "WARNING"
            elif '❌' in clean:
                level = "ERROR"

            # 提取消息文本（去掉时间戳和元数据前缀）
            text = re.sub(r'^\[[\d:]+\]\s*\[[^\]]*\]\s*\[SEQ:\d+\]\s*\[TASK:[^\]]+\]\s*\[[^\]]*\]\s*', '', clean)

            records.append({
                "seq": seq,
                "time": time_str,
                "level": level,
                "day": current_day,
                "date": current_date,
                "section": sec,
                "strategy": strat,
                "text": text.strip(),
            })

    # 筛选
    filtered = records
    if day != "all":
        try:
            day_num = int(day)
            filtered = [r for r in filtered if r.get("day") == day_num]
        except ValueError:
            pass
    if strategy:
        filtered = [r for r in filtered if r.get("strategy") == strategy]
    if section:
        filtered = [r for r in filtered if r.get("section") == section]
    if search:
        search_lower = search.lower()
        filtered = [r for r in filtered if search_lower in r.get("text", "").lower()]

    # 天数索引
    days_info = []
    seen = {}
    for r in records:
        d = r.get("day", 0)
        if d > 0 and d not in seen:
            seen[d] = True
            days_info.append({"day": d, "date": r.get("date", "")})

    total = len(filtered)
    if tail:
        result_logs = filtered[-tail:]
    else:
        result_logs = filtered[offset:offset + limit]

    return {
        "task_id": task_id,
        "total_lines": len(records),
        "filtered_total": total,
        "days": days_info,
        "strategies": list(set(r.get("strategy") for r in records if r.get("strategy"))),
        "sections": list(set(r.get("section") for r in records if r.get("section"))),
        "offset": offset if tail is None else None,
        "limit": limit,
        "logs": result_logs,
    }


@router.get("/logs/{task_id}/summary")
async def get_backtest_log_summary(task_id: str):
    """获取日志摘要 - 天数/策略/section分布"""
    if not task_id.replace('_', '').replace('-', '').isalnum():
        raise HTTPException(status_code=400, detail="Invalid task_id")

    jsonl_path = os.path.join(LOG_DIR, f"{task_id}.jsonl")
    log_path = os.path.join(LOG_DIR, f"{task_id}.log")

    if not os.path.exists(jsonl_path) and not os.path.exists(log_path):
        raise HTTPException(status_code=404, detail=f"No logs found for task {task_id}")

    # 用主API获取，只要摘要信息
    result = await get_backtest_logs(
        task_id=task_id, day="all", limit=0  # 0条=只要摘要
    )
    return {
        "task_id": result["task_id"],
        "total_lines": result["total_lines"],
        "days": result["days"],
        "strategies": result["strategies"],
        "sections": result["sections"],
    }
