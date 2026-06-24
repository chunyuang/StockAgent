#!/usr/bin/env python3
"""
因子查看与管理 REST API

提供因子查看、批量查看、更新触发、更新状态、更新日志、元数据等接口。
数据源: stock_daily_ak_full + daily_basic + stock_basic (MongoDB)
因子定义: FactorLibrary (factor_library.py)
"""

import logging
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional, List

from fastapi import APIRouter, Query, HTTPException

from core.constants import C
from core.managers import mongo_manager
from nodes.backtest_engine.factor_selection.factor_library import (
    FactorLibrary, FactorCategory, FactorDefinition,
)
from .utils import sanitize_nan

logger = logging.getLogger("api.factor")

router = APIRouter(prefix="/factor", tags=["因子管理"])

# ==================== 时区 ====================
_CST = timezone(timedelta(hours=8))


def _now_cst() -> datetime:
    return datetime.now(_CST)


def _today_str() -> str:
    """当前交易日期字符串 YYYYMMDD"""
    return _now_cst().strftime("%Y%m%d")


def _normalize_date(date_input):
    """
    返回 trade_date int 格式 (MongoDB中实际存为int)。
    """
    if date_input is None:
        try:
            return int(_today_str())
        except Exception:
            return None
    try:
        return int(date_input)
    except (ValueError, TypeError):
        return date_input


# ==================== 因子分类映射 ====================

# FactorCategory → 简化分类(realtime/daily/basic/composite)
_CATEGORY_TO_SIMPLE = {
    FactorCategory.MOMENTUM: "daily",
    FactorCategory.VALUE: "basic",
    FactorCategory.QUALITY: "basic",
    FactorCategory.GROWTH: "basic",
    FactorCategory.VOLATILITY: "daily",
    FactorCategory.LIQUIDITY: "daily",
    FactorCategory.TECHNICAL: "realtime",
}

# 因子 data_source → 更新类型(intraday/daily/static)
_DATA_SOURCE_TO_UPDATE_TYPE = {
    "daily": "intraday",       # 来自日线行情,盘中可实时更新
    "daily_basic": "daily",    # 来自每日指标,盘后更新
    "fina": "static",          # 来自财务数据,季度更新
}

# 因子字段名 → MongoDB集合映射 (覆盖默认推断)
# daily_basic 独有的因子字段，需要从 daily_basic 集合读取
_FACTOR_FIELD_SOURCES = {
    "pe_ttm": C.DAILY_BASIC,
    "pb": C.DAILY_BASIC,
    "ps_ttm": C.DAILY_BASIC,
    "dv_ttm": C.DAILY_BASIC,
    "total_mv": C.DAILY_BASIC,
    "circ_mv": C.DAILY_BASIC,
    "turnover_20d": C.DAILY_BASIC,
}

# daily_basic 和 stock_daily_ak_full 都有的字段，但应优先从 daily_basic 读取
_DAILY_BASIC_PRIORITY_FIELDS = {
    "turnover_rate", "volume_ratio", "circ_mv",
}


def _get_factor_collection(factor_def: FactorDefinition) -> str:
    """判断因子值应该从哪个MongoDB集合读取"""
    name = factor_def.name
    if name in _FACTOR_FIELD_SOURCES:
        return _FACTOR_FIELD_SOURCES[name]
    data_source = factor_def.data_source
    if data_source == "daily_basic":
        return C.DAILY_BASIC
    return C.STOCK_DAILY


# ==================== 核心查询逻辑 ====================

async def _get_merged_stock_data(ts_code: str, trade_date) -> dict:
    """
    合并 stock_daily_ak_full + daily_basic 数据

    Args:
        ts_code: 股票代码
        trade_date: 交易日期字符串 (如 "20260602")

    Returns:
        {"daily": {...}, "daily_basic": {...}, "stock_name": "..."}
    """
    result = {"daily": None, "daily_basic": None, "stock_name": ""}
    
    # trade_date兼容int/string( MongoDB存的是int)
    if trade_date is None:
        td_int = None
        td_query = None
    elif isinstance(trade_date, int):
        td_int = trade_date
        td_query = {"$in": [td_int, str(td_int)]}
    else:
        td_int = int(str(trade_date).replace("-", "").replace("/", ""))
        td_query = {"$in": [td_int, trade_date]}

    # 1. 查 stock_daily_ak_full
    daily = await mongo_manager.find_one(
        C.STOCK_DAILY,
        {"ts_code": ts_code, "trade_date": td_query},
    )
    if daily:
        daily.pop("_id", None)
        result["daily"] = daily

    # 2. 查 daily_basic
    daily_basic = await mongo_manager.find_one(
        C.DAILY_BASIC,
        {"ts_code": ts_code, "trade_date": td_query},
    )
    if daily_basic:
        daily_basic.pop("_id", None)
        result["daily_basic"] = daily_basic

    # 3. 查 stock_name
    stock_info = await mongo_manager.find_one(
        C.STOCK_BASIC,
        {"ts_code": ts_code},
        projection={"name": 1},
    )
    if stock_info:
        result["stock_name"] = stock_info.get("name", "")

    return result


async def _get_latest_trade_date(ts_code: str, before_date) -> Optional[int]:
    """获取某只股票在before_date之前的最近交易日期"""
    try:
        before = int(before_date) if before_date else None
    except (ValueError, TypeError):
        before = before_date
    doc = await mongo_manager.find_one(
        C.STOCK_DAILY,
        {"ts_code": ts_code, "trade_date": {"$lte": before}} if before else {"ts_code": ts_code},
        sort=[("trade_date", -1)],
    )
    if not doc:
        return None
    try:
        return int(doc["trade_date"])
    except (ValueError, TypeError):
        return doc["trade_date"]


def _extract_factor_value(factor_def: FactorDefinition, merged_data: dict):
    """
    从合并数据中提取因子值

    Args:
        factor_def: FactorDefinition 实例 (含 required_fields)
        merged_data: _get_merged_stock_data 的返回值

    Returns:
        (value, source_collection) 或 (None, collection_name)
    """
    collection = _get_factor_collection(factor_def)
    required_fields = factor_def.required_fields

    # 确定优先读取的数据源
    if collection == C.DAILY_BASIC:
        # 优先从 daily_basic 读取，fallback 到 daily
        data = merged_data.get("daily_basic") or merged_data.get("daily") or {}
    else:
        # 优先从 daily 读取，fallback 到 daily_basic
        data = merged_data.get("daily") or merged_data.get("daily_basic") or {}

    # 尝试从 required_fields 中获取值
    for field in required_fields:
        if field in data and data[field] is not None:
            val = data[field]
            # 处理 numpy 类型
            try:
                if hasattr(val, 'item'):
                    val = val.item()
            except Exception:
                pass
            return val, collection

    # 如果主数据源没找到，尝试另一个数据源
    if collection == C.DAILY_BASIC and merged_data.get("daily"):
        alt_data = merged_data["daily"]
        for field in required_fields:
            if field in alt_data and alt_data[field] is not None:
                val = alt_data[field]
                try:
                    if hasattr(val, 'item'):
                        val = val.item()
                except Exception:
                    pass
                return val, C.STOCK_DAILY
    elif collection == C.STOCK_DAILY and merged_data.get("daily_basic"):
        alt_data = merged_data["daily_basic"]
        for field in required_fields:
            if field in alt_data and alt_data[field] is not None:
                val = alt_data[field]
                try:
                    if hasattr(val, 'item'):
                        val = val.item()
                except Exception:
                    pass
                return val, C.DAILY_BASIC

    return None, collection


def _determine_factor_status(
    value,
    target_date: str,
    merged_data: dict,
) -> str:
    """
    判断因子状态

    - fresh: 当日有值
    - stale: 无当日数据但有上期数据
    - error: 计算异常
    - missing: 数据完全缺失
    """
    if value is not None:
        # 有值，检查数据日期是否是目标日期
        daily = merged_data.get("daily")
        daily_basic = merged_data.get("daily_basic")

        data_date = None
        if daily and daily.get("trade_date"):
            data_date = str(daily["trade_date"])
        elif daily_basic and daily_basic.get("trade_date"):
            data_date = str(daily_basic["trade_date"])

        if data_date == str(target_date):
            return "fresh"
        else:
            return "stale"
    else:
        # 无值，检查是否有任何数据
        daily = merged_data.get("daily")
        daily_basic = merged_data.get("daily_basic")
        if daily or daily_basic:
            return "stale"
        return "missing"


def _get_all_factor_defs() -> List[FactorDefinition]:
    """获取所有 FactorDefinition 实例（含 required_fields）"""
    factors_info = FactorLibrary.list_factors()
    result = []
    for f_info in factors_info:
        fd = FactorLibrary.get(f_info["name"])
        if fd:
            result.append(fd)
    return result


def _simple_category(factor_category: str) -> str:
    """将 FactorCategory 枚举值转为简化分类"""
    try:
        return str(_CATEGORY_TO_SIMPLE.get(FactorCategory(factor_category), "daily"))
    except ValueError:
        return "daily"


# ==================== API 端点 ====================


@router.get("/view")
async def view_factor(
    ts_code: str = Query(..., description="股票代码, 如 000001.SZ"),
    date: Optional[str] = Query(None, description="日期 YYYYMMDD, 默认今天"),
    category: Optional[str] = Query(None, description="因子分类过滤: realtime/daily/basic/composite"),
    status: Optional[str] = Query(None, description="因子状态过滤: fresh/stale/error/missing"),
):
    """
    查看单只股票的因子数据

    合并 stock_daily_ak_full + daily_basic 数据，
    用 FactorLibrary 获取因子元数据，返回每个因子的值、状态、来源。
    """
    ts_code = ts_code.upper()
    trade_date = _normalize_date(date)

    # 获取合并数据
    merged = await _get_merged_stock_data(ts_code, trade_date)

    # 如果当日无数据，找最近的交易日
    if not merged["daily"] and not merged["daily_basic"]:
        latest_date = await _get_latest_trade_date(ts_code, trade_date)
        if latest_date:
            merged = await _get_merged_stock_data(ts_code, latest_date)
            trade_date = latest_date
        else:
            return {
                "success": True,
                "data": {
                    "ts_code": ts_code,
                    "stock_name": "",
                    "update_time": None,
                    "factors": [],
                },
                "message": "无数据",
            }

    # 获取所有因子定义
    all_factors = _get_all_factor_defs()

    # 构建因子列表
    factors = []
    for fd in all_factors:
        simple_cat = _simple_category(fd.category.value)

        # category 过滤
        if category and simple_cat != category:
            continue

        # 提取因子值
        value, source = _extract_factor_value(fd, merged)

        # 判断状态
        f_status = _determine_factor_status(value, trade_date, merged)

        # status 过滤
        if status and f_status != status:
            continue

        # 格式化值
        if value is not None:
            try:
                if isinstance(value, float):
                    value = round(value, 4)
            except Exception:
                pass

        factors.append({
            "name": fd.name,
            "display_name": fd.display_name,
            "category": simple_cat,
            "value": value,
            "source": source,
            "update_time": trade_date if value is not None else None,
            "status": f_status,
        })

    # 按 category + name 排序
    cat_order = {"realtime": 0, "daily": 1, "basic": 2, "composite": 3}
    factors.sort(key=lambda x: (cat_order.get(x["category"], 99), x["name"]))

    return {
        "success": True,
        "data": {
            "ts_code": ts_code,
            "stock_name": merged["stock_name"],
            "update_time": trade_date,
            "factors": sanitize_nan(factors),
        },
    }


@router.get("/batch-view")
async def batch_view_factor(
    codes: Optional[str] = Query(None, description="股票代码, 逗号分隔, 如 000001.SZ,600036.SH。不传则返回全市场前N只"),
    date: Optional[str] = Query(None, description="日期 YYYYMMDD, 默认今天"),
    category: Optional[str] = Query(None, description="因子分类过滤"),
    status: Optional[str] = Query(None, description="因子状态过滤"),
    page: int = Query(1, ge=1, description="页码"),
    limit: int = Query(20, ge=1, le=100, description="每页数量"),
):
    """
    批量查看多只股票的因子数据

    返回分页的因子数据列表，每只股票一条记录。
    """
    if codes:
        ts_codes = [c.strip().upper() for c in codes.split(",") if c.strip()]
    else:
        # 不传codes时，从daily_basic取有数据的股票
        try:
            from pymongo import MongoClient
            client = MongoClient("mongodb://localhost:27017", serverSelectionTimeoutMS=3000)
            db = client["stock_agent"]
            pipeline = [
                {"$sort": {"trade_date": -1}},
                {"$group": {"_id": "$ts_code", "trade_date": {"$first": "$trade_date"}}},
                {"$sort": {"trade_date": -1}},
                {"$skip": (page - 1) * limit},
                {"$limit": limit}
            ]
            result = list(db["daily_basic"].aggregate(pipeline))
            ts_codes = [r["_id"] for r in result]
        except Exception as e:
            logger.error(f"batch-view fallback: {e}")
            ts_codes = []
    if not ts_codes:
        return {"success": True, "data": {"items": [], "total": 0}}

    trade_date = _normalize_date(date)

    # 分页
    total = len(ts_codes)
    start = (page - 1) * limit
    end = start + limit
    page_codes = ts_codes[start:end]

    all_factor_defs = _get_all_factor_defs()

    items = []
    for ts_code in page_codes:
        merged = await _get_merged_stock_data(ts_code, trade_date)

        actual_date = trade_date
        if not merged["daily"] and not merged["daily_basic"]:
            latest_date = await _get_latest_trade_date(ts_code, trade_date)
            if latest_date:
                merged = await _get_merged_stock_data(ts_code, latest_date)
                actual_date = latest_date
            else:
                items.append({
                    "ts_code": ts_code,
                    "stock_name": "",
                    "trade_date": trade_date,
                    "factor_count": 0,
                    "fresh_count": 0,
                    "stale_count": 0,
                    "missing_count": 0,
                    "factors": [],
                })
                continue

        # 构建因子列表
        factors = []
        fresh_count = 0
        stale_count = 0
        missing_count = 0

        for fd in all_factor_defs:
            simple_cat = _simple_category(fd.category.value)

            if category and simple_cat != category:
                continue

            value, source = _extract_factor_value(fd, merged)
            f_status = _determine_factor_status(value, actual_date, merged)

            if status and f_status != status:
                continue

            if f_status == "fresh":
                fresh_count += 1
            elif f_status == "stale":
                stale_count += 1
            elif f_status == "missing":
                missing_count += 1

            if value is not None:
                try:
                    if isinstance(value, float):
                        value = round(value, 4)
                except Exception:
                    pass

            factors.append({
                "name": fd.name,
                "display_name": fd.display_name,
                "category": simple_cat,
                "value": value,
                "source": source,
                "status": f_status,
            })

        items.append({
            "ts_code": ts_code,
            "stock_name": merged["stock_name"],
            "trade_date": actual_date,
            "factor_count": len(factors),
            "fresh_count": fresh_count,
            "stale_count": stale_count,
            "missing_count": missing_count,
            "factors": sanitize_nan(factors),
        })

    return {
        "success": True,
        "data": {
            "total": total,
            "page": page,
            "limit": limit,
            "items": sanitize_nan(items),
        },
    }


@router.post("/update")
async def trigger_factor_update(
    scope: str = Query("single", description="更新范围: single/pool/market"),
    ts_code: Optional[str] = Query(None, description="单只股票代码(scope=single时)"),
    date: Optional[str] = Query(None, description="日期 YYYYMMDD, 默认今天"),
):
    """
    触发因子更新

    根据当前时段智能判断:
    - 盘中(9:30-15:00): 只更新实时因子
    - 盘后: 全量更新

    调用 factor_auto_compute 或 FactorEngine。
    """
    trade_date = _normalize_date(date)

    # 判断当前时段
    now = _now_cst()
    hour, minute = now.hour, now.minute
    is_intraday = (hour == 9 and minute >= 30) or (10 <= hour < 15)

    # 生成任务ID
    task_id = f"factor_update_{now.strftime('%Y%m%d_%H%M%S')}"

    # 异步触发更新
    async def _run_update():
        try:
            from nodes.backtest_engine.factor_selection.factor_auto_compute import (
                auto_compute_factors,
                STRATEGY_FACTOR_FIELDS,
                TECHNICAL_FACTOR_FIELDS,
            )

            # daily_basic 专属因子（盘中不更新）
            DAILY_BASIC_ONLY_FIELDS = {
                "pe_ttm", "pb", "ps_ttm", "dv_ttm", "total_mv",
                "turnover_20d", "roe", "roa", "gross_margin",
                "revenue_growth", "profit_growth",
            }

            if is_intraday:
                fields = [f for f in STRATEGY_FACTOR_FIELDS if f not in DAILY_BASIC_ONLY_FIELDS]
            else:
                fields = STRATEGY_FACTOR_FIELDS + TECHNICAL_FACTOR_FIELDS

            if scope == "single" and ts_code:
                result = await auto_compute_factors(
                    missing_fields=fields,
                    start_date=int(trade_date),
                    end_date=int(trade_date),
                )
                logger.info(f"[FACTOR-UPDATE] 单只 {ts_code} 更新完成: {result}")
            else:
                result = await auto_compute_factors(
                    missing_fields=fields,
                    start_date=int(trade_date),
                    end_date=int(trade_date),
                )
                logger.info(f"[FACTOR-UPDATE] {scope} 更新完成: {result}")

        except Exception as e:
            logger.exception(f"[FACTOR-UPDATE] 因子更新失败: {e}")

    # 后台运行
    asyncio.create_task(_run_update())

    scope_desc = {
        "single": f"单只 {ts_code}" if ts_code else "单只(未指定代码)",
        "pool": "股票池",
        "market": "全市场",
    }

    return {
        "success": True,
        "data": {
            "task_id": task_id,
            "scope": scope,
            "trade_date": trade_date,
            "is_intraday": is_intraday,
            "update_type": "intraday_realtime" if is_intraday else "postmarket_full",
        },
        "message": f"已触发{scope_desc.get(scope, scope)}因子{'盘中实时' if is_intraday else '盘后全量'}更新，任务ID: {task_id}",
    }


@router.get("/update-status")
async def get_update_status():
    """
    获取因子更新系统状态

    返回: 系统阶段、最后更新时间、成功/失败计数、数据源可用性。
    """
    now = _now_cst()
    hour, minute = now.hour, now.minute

    # 判断系统阶段
    weekday = now.weekday()
    if weekday >= 5:  # 周六日
        system_status = "holiday"
    elif (hour == 9 and minute >= 30) or (10 <= hour < 15):
        system_status = "intraday_updating"
    elif 15 <= hour < 16:
        system_status = "postmarket_updating"
    else:
        system_status = "completed"

    # 查询最新因子数据日期
    last_update_time = None
    try:
        latest = await mongo_manager.find_one(
            C.STOCK_DAILY,
            {"trade_date": {"$exists": True}},
            sort=[("trade_date", -1)],
            projection={"trade_date": 1},
        )
        if latest:
            last_update_time = str(latest["trade_date"])
    except Exception:
        pass

    # 统计因子覆盖率(当日)
    today_str = _today_str()
    success_count = 0
    fail_count = 0
    try:
        daily_count = await mongo_manager.count(C.STOCK_DAILY, {"trade_date": today_str})
        basic_count = await mongo_manager.count(C.DAILY_BASIC, {"trade_date": today_str})
        success_count = daily_count
        if daily_count > 0 and basic_count < daily_count:
            fail_count = daily_count - basic_count
    except Exception:
        pass

    # 数据源可用性
    data_sources = [
        {"name": "stock_daily_ak_full", "available": True},
        {"name": "daily_basic", "available": True},
        {"name": "stock_basic", "available": True},
    ]

    try:
        from nodes.market_monitor.data_source_router import DataSourceRouter  # noqa: F401
        data_sources.append({"name": "eastmoney_api", "available": True})
    except Exception:
        data_sources.append({"name": "eastmoney_api", "available": False})

    return {
        "success": True,
        "data": {
            "system_status": system_status,
            "current_time": now.strftime("%Y-%m-%d %H:%M:%S"),
            "last_update_time": last_update_time,
            "success_count": success_count,
            "fail_count": fail_count,
            "data_sources": data_sources,
        },
    }


@router.get("/update-logs")
async def get_update_logs(
    date: Optional[str] = Query(None, description="日期 YYYYMMDD, 默认今天"),
    limit: int = Query(50, ge=1, le=200, description="返回条数"),
):
    """
    获取因子更新日志

    返回更新失败/缺数/计算异常的记录列表。
    数据来源: stock_daily_ak_full 中因子字段为空/异常的记录。
    """
    trade_date = _normalize_date(date)

    logs = []

    # 1. 检查当日数据完整性 - stock_daily_ak_full 有记录但关键因子缺失
    try:
        missing_pct = await mongo_manager.find_many(
            C.STOCK_DAILY,
            {
                "trade_date": trade_date,
                "$or": [
                    {"pct_chg": None},
                    {"pct_chg": {"$exists": False}},
                ],
            },
            projection={"ts_code": 1, "trade_date": 1},
            limit=limit,
        )
        for doc in missing_pct:
            logs.append({
                "type": "missing_field",
                "ts_code": doc.get("ts_code", ""),
                "trade_date": trade_date,
                "field": "pct_chg",
                "message": "日线数据缺少 pct_chg 字段",
                "severity": "warning",
            })
    except Exception as e:
        logs.append({
            "type": "query_error",
            "ts_code": "",
            "trade_date": trade_date,
            "field": "stock_daily_ak_full",
            "message": f"查询日线数据失败: {e}",
            "severity": "error",
        })

    # 2. 检查 daily_basic 缺失 - stock_daily_ak_full 有但 daily_basic 没有
    try:
        pipeline = [
            {"$match": {"trade_date": trade_date}},
            {"$project": {"ts_code": 1, "_id": 0}},
            {"$lookup": {
                "from": "daily_basic",
                "let": {"tc": "$ts_code"},
                "pipeline": [
                    {"$match": {"$expr": {"$and": [
                        {"$eq": ["$ts_code", "$$tc"]},
                        {"$eq": ["$trade_date", trade_date]},
                    ]}}},
                    {"$project": {"_id": 1}},
                ],
                "as": "basic",
            }},
            {"$match": {"basic": {"$size": 0}}},
            {"$limit": limit},
        ]
        missing_basic = await mongo_manager.aggregate(C.STOCK_DAILY, pipeline)
        for doc in missing_basic:
            logs.append({
                "type": "missing_basic",
                "ts_code": doc.get("ts_code", ""),
                "trade_date": trade_date,
                "field": "daily_basic",
                "message": "当日 daily_basic 数据缺失",
                "severity": "warning",
            })
    except Exception as e:
        logs.append({
            "type": "query_error",
            "ts_code": "",
            "trade_date": trade_date,
            "field": "daily_basic",
            "message": f"聚合查询daily_basic缺失失败: {e}",
            "severity": "error",
        })

    # 3. 检查 daily_basic 中关键因子异常(PE为负/0等)
    try:
        anomalous = await mongo_manager.find_many(
            C.DAILY_BASIC,
            {
                "trade_date": trade_date,
                "$or": [
                    {"pe_ttm": {"$lt": 0}},
                    {"pb": {"$lte": 0}},
                    {"turnover_rate": {"$lte": 0}},
                ],
            },
            projection={"ts_code": 1, "pe_ttm": 1, "pb": 1, "turnover_rate": 1},
            limit=limit,
        )
        for doc in anomalous:
            issues = []
            if doc.get("pe_ttm") is not None and doc["pe_ttm"] < 0:
                issues.append(f"pe_ttm={doc['pe_ttm']}")
            if doc.get("pb") is not None and doc["pb"] <= 0:
                issues.append(f"pb={doc['pb']}")
            if doc.get("turnover_rate") is not None and doc["turnover_rate"] <= 0:
                issues.append(f"turnover_rate={doc['turnover_rate']}")

            logs.append({
                "type": "anomaly",
                "ts_code": doc.get("ts_code", ""),
                "trade_date": trade_date,
                "field": ", ".join(issues),
                "message": f"因子异常: {', '.join(issues)}",
                "severity": "info",
            })
    except Exception:
        pass

    # 按严重程度排序: error > warning > info
    severity_order = {"error": 0, "warning": 1, "info": 2}
    logs.sort(key=lambda x: severity_order.get(x.get("severity", "info"), 99))

    return {
        "success": True,
        "data": {
            "trade_date": trade_date,
            "total": len(logs),
            "logs": sanitize_nan(logs[:limit]),
        },
    }


@router.get("/metadata")
async def get_factor_metadata():
    """
    获取因子元数据

    返回所有因子的分类、名称、描述、方向、数据源、更新类型。
    数据来源: FactorLibrary.list_factors() + FactorLibrary.get()
    """
    factors_info = FactorLibrary.list_factors()

    # 分类中文标签
    cat_label_map = {
        "momentum": "动量因子",
        "value": "价值因子",
        "quality": "质量因子",
        "growth": "成长因子",
        "volatility": "波动因子",
        "liquidity": "流动性因子",
        "technical": "技术因子",
    }

    # 按 category 分组
    categories_map = {}
    for f_info in factors_info:
        cat = f_info["category"]
        cat_label = cat_label_map.get(cat, cat)

        if cat not in categories_map:
            categories_map[cat] = {
                "name": cat,
                "label": cat_label,
                "factors": [],
            }

        simple_cat = _simple_category(cat)
        update_type = _DATA_SOURCE_TO_UPDATE_TYPE.get(f_info["data_source"], "daily")

        categories_map[cat]["factors"].append({
            "name": f_info["name"],
            "display_name": f_info["display_name"],
            "category": simple_cat,
            "description": f_info["description"],
            "direction": f_info["direction"],
            "data_source": f_info["data_source"],
            "update_type": update_type,
        })

    # 按固定顺序排列
    cat_order = ["momentum", "value", "quality", "growth", "volatility", "liquidity", "technical"]
    categories = []
    for cat in cat_order:
        if cat in categories_map:
            categories.append(categories_map[cat])
    # 添加可能的新分类
    for cat, data in categories_map.items():
        if cat not in cat_order:
            categories.append(data)

    return {
        "success": True,
        "data": {
            "total_factors": len(factors_info),
            "categories": categories,
        },
    }
