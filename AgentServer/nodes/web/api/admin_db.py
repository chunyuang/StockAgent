"""
MongoDB 数据库管理 API

提供数据库统计、清理、校验功能
"""

from typing import Dict, List, Any, Optional
from datetime import datetime
import logging

from fastapi import APIRouter, HTTPException, Body
from pydantic import BaseModel, Field

from core.managers import mongo_manager
from core.settings import settings


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin/db", tags=["数据库管理"])


# ========== 允许操作的集合（安全白名单） ==========
# ========== 允许操作的集合（安全白名单） ==========
# 只包含实际存在且允许用户管理的集合
ALLOWED_COLLECTIONS = [
    "stock_daily_ak_full",  # 日线行情完整版 - 存在
    "daily_basic",         # 每日基本信息 - 存在（预留）
    "index_daily",         # 指数日线 - 存在
    "stock_daily_ak_full_factors",  # 日线因子 - 存在
    "stock_1min_factors",   # 1分钟因子 - 存在
    "backtest_tasks",     # 回测任务 - 存在
    "limit_list",         # 涨跌停列表 - 存在
    "trade_cal",          # 交易日历 - 存在
    "stock_basic",        # 股票基础信息 - 存在
]


# ========== 请求/响应模型 ==========

class StatsResponse(BaseModel):
    """数据库统计响应"""
    mongodb_version: str
    collections: List[Dict[str, Any]]
    stock_daily_ak_full: Optional[Dict[str, Any]] = None
    factors: Optional[Dict[str, Any]] = None


class ClearCollectionRequest(BaseModel):
    """清空集合请求"""
    confirm: bool = Field(False, description="必须确认才能执行")


class ClearDateRangeRequest(BaseModel):
    """清空时间范围请求"""
    collection_name: str = Field(..., description="集合名称")
    start_date: int = Field(..., description="开始日期 (int格式 YYYYMMDD)")
    end_date: int = Field(..., description="结束日期 (int格式 YYYYMMDD)")
    confirm: bool = Field(False, description="必须确认才能执行")


class DeduplicateRequest(BaseModel):
    """去重请求"""
    collection_name: str = Field(..., description="集合名称")
    dry_run: bool = Field(True, description="true=只统计不删除，false=实际删除")


class CheckMissingRequest(BaseModel):
    """检查缺失数据请求"""
    date: Optional[int] = Field(None, description="检查指定日期，不指定检查最新日期")
    factors: Optional[List[str]] = Field(None, description="检查指定因子，不指定检查所有预计算因子")
    
    class Config:
        extra = 'allow'


# ========== 工具函数 ==========

def _bytes_to_human(size_bytes: int) -> str:
    """转换字节数为人性化显示"""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


# ========== API 端点 ==========


@router.get("/stats")
async def get_database_stats():
    """
    获取数据库整体统计信息
    
    - 显示所有集合的大小和文档数
    - 特别显示 stock_daily_ak_full 的详细统计
    - 显示因子覆盖统计
    """
    # 获取 MongoDB 版本
    # 使用 mongo_manager._client 获取异步客户端
    info = await mongo_manager._client.admin.command('buildInfo')
    mongodb_version = info.get('version', 'unknown')
    
    # 获取所有集合统计
    collections = []
    db = mongo_manager._db
    
    # motor 异步方式获取集合列表
    collection_names = await db.list_collection_names()
    
    for coll_name in collection_names:
        # 获取集合统计
        try:
            # motor 使用 async 方式
            stats = await db.command("collstats", coll_name)
            collections.append({
                "name": coll_name,
                "document_count": stats.get("count", 0),
                "size_bytes": stats.get("size", 0),
                "size_human": _bytes_to_human(stats.get("size", 0)),
                "avg_document_size": stats.get("avgObjSize", 0),
            })
        except Exception as e:
            logger.warning(f"Failed to get stats for {coll_name}: {e}")
            collections.append({
                "name": coll_name,
                "document_count": 0,
                "size_bytes": 0,
                "size_human": "0 B",
                "avg_document_size": 0,
            })
    
    # 特别统计 stock_daily_ak_full
    stock_daily_ak_full_stats = None
    try:
        coll = db["stock_daily_ak_full"]
        count = await coll.count_documents({})
        
        # 获取日期范围
        if count > 0:
            # 最早日期
            min_date_result = await coll.aggregate([
                {"$group": {"_id": None, "min_date": {"$min": "$trade_date"}}}
            ]).to_list(length=1)
            max_date_result = await coll.aggregate([
                {"$group": {"_id": None, "max_date": {"$max": "$trade_date"}}}
            ]).to_list(length=1)
            
            min_date = min_date_result[0]["min_date"] if min_date_result else None
            max_date = max_date_result[0]["max_date"] if max_date_result else None
            
            # 统计不重复股票数
            stock_cursor = coll.distinct("ts_code")
            stock_count = len(await stock_cursor.to_list(length=None))
            
            # 最后更新时间（近似，用最新日期推算）
            last_update = datetime.utcnow().isoformat()
            
            stats = await db.command("collstats", "stock_daily_ak_full")
            stock_daily_ak_full_stats = {
                "document_count": count,
                "size_bytes": stats["size"],
                "size_human": _bytes_to_human(stats["size"]),
                "date_range": {
                    "min_date": min_date,
                    "max_date": max_date,
                    "total_trading_days": (max_date - min_date) // 1000 if min_date and max_date else 0,
                },
                "stock_count": stock_count,
                "last_update": last_update,
            }
    except Exception as e:
        logger.error(f"Failed to get stock_daily_ak_full stats: {e}")
    
    # 因子覆盖统计（抽样检查最新一天）
    factor_stats = None
    try:
        coll = db["stock_daily_ak_full"]
        # 获取最新一天
        latest = await coll.find({}, {"trade_date": 1}).sort([("trade_date", -1)]).limit(1).to_list(length=1)
        if latest:
            # 所有可能的预计算因子
            all_factors = [
                "limit_up_amount", "limit_down_count", "circ_mv", "turnover_rate",
                "pullback_ma5", "sentiment_score", "first_limit_up", "limit_up_yesterday",
                "limit_up_count", "market_leader", "volume_ratio", "amplitude",
                "open_below_limit", "open_above_limit", "limit_up_open_amount",
                "limit_down_yesterday", "volume_increase", "limit_up_open_count",
                "hot_sector", "limit_up_time", "limit_up_open_duration",
                "pullback_pct", "pullback_days", "open_above_limit_down",
                "limit_down_open_amount", "rise_after_limit_down",
            ]
            
            # 抽样统计覆盖情况
            factor_coverage = {}
            total_factors = len(all_factors)
            covered_factors = 0
            missing_factors = []
            
            # 抽样 100 个文档检查每个因子
            sample_docs = await coll.find().sort([("trade_date", -1)]).limit(100).to_list(length=100)
            
            for f in all_factors:
                has_count = sum(1 for doc in sample_docs if f in doc and doc[f] is not None)
                coverage_pct = has_count / len(sample_docs) * 100
                factor_coverage[f] = {
                    "total_docs": len(sample_docs),
                    "non_null_docs": has_count,
                    "coverage_pct": round(coverage_pct, 2),
                }
                if coverage_pct >= 99:
                    covered_factors += 1
                else:
                    missing_factors.append(f)
            
            factor_stats = {
                "total_factors": total_factors,
                "covered_factors": covered_factors,
                "missing_factors": missing_factors,
                "coverage": factor_coverage,
            }
    except Exception as e:
        logger.error(f"Failed to get factor stats: {e}")
    
    # 计算总体统计
    total_documents = sum(c["document_count"] for c in collections)
    total_size_bytes = sum(c["size_bytes"] for c in collections)
    
    return {
        "success": True,
        "data": {
            "mongodb_version": mongodb_version,
            "db_name": settings.mongo.database,
            "total_documents": total_documents,
            "total_size_bytes": total_size_bytes,
            "collections": collections,
            "stock_daily_ak_full": stock_daily_ak_full_stats,
            "factors": factor_stats,
        },
        "message": "数据库统计获取成功",
    }


@router.post("/clear-collection/{collection_name}")
async def clear_collection(
    collection_name: str,
    request: ClearCollectionRequest,
):
    """
    清空指定集合
    
    - 只允许清空白名单内的集合
    - 必须 confirm=true 才能执行
    """
    # 安全检查
    if collection_name not in ALLOWED_COLLECTIONS:
        raise HTTPException(
            status_code=403,
            detail=f"不允许清空集合 {collection_name}，只允许清空: {ALLOWED_COLLECTIONS}",
        )
    
    if not request.confirm:
        return {
            "success": False,
            "message": "需要 confirm=true 确认才能执行清空操作，这是危险操作，请确认",
        }
    
    db = mongo_manager._db
    coll = db[collection_name]
    count_before = await coll.count_documents({})
    
    # 执行清空
    await coll.delete_many({})
    count_after = await coll.count_documents({})
    
    logger.info(f"[admin_db] Cleared collection {collection_name}, documents: {count_before} -> {count_after}")
    
    return {
        "success": True,
        "data": {
            "collection_name": collection_name,
            "documents_before": count_before,
            "documents_after": count_after,
        },
        "message": f"集合 {collection_name} 已成功清空，删除 {count_before} 篇文档",
    }


@router.post("/clear-date-range")
async def clear_date_range(request: ClearDateRangeRequest):
    """
    删除指定时间范围的数据
    """
    # 安全检查
    if request.collection_name not in ALLOWED_COLLECTIONS:
        raise HTTPException(
            status_code=403,
            detail=f"不允许操作集合 {request.collection_name}，只允许: {ALLOWED_COLLECTIONS}",
        )
    
    if not request.confirm:
        return {
            "success": False,
            "message": "需要 confirm=true 确认才能执行删除操作，这是危险操作，请确认",
        }
    
    db = mongo_manager._db
    coll = db[request.collection_name]
    
    # 统计将要删除
    deleted_before = await coll.count_documents({
        "trade_date": {
            "$gte": request.start_date,
            "$lte": request.end_date,
        }
    })
    
    if deleted_before == 0:
        return {
            "success": True,
            "data": {
                "collection_name": request.collection_name,
                "start_date": request.start_date,
                "end_date": request.end_date,
                "deleted_count": 0,
            },
            "message": "指定时间范围内没有文档，无需删除",
        }
    
    # 执行删除
    result = await coll.delete_many({
        "trade_date": {
            "$gte": request.start_date,
            "$lte": request.end_date,
        }
    })
    
    deleted_count = result.deleted_count
    logger.info(f"[admin_db] Deleted date range {request.start_date}-{request.end_date} from {request.collection_name}: {deleted_count} docs")
    
    return {
        "success": True,
        "data": {
            "collection_name": request.collection_name,
            "start_date": request.start_date,
            "end_date": request.end_date,
            "deleted_count": deleted_count,
        },
        "message": f"成功删除 {deleted_count} 篇文档",
    }


@router.post("/deduplicate")
async def deduplicate_collection(request: DeduplicateRequest):
    """
    清理重复数据（按 ts_code + trade_date 去重）
    
    重复定义：同一股票同一天有多个文档
    """
    # 安全检查
    if request.collection_name not in ALLOWED_COLLECTIONS:
        raise HTTPException(
            status_code=403,
            detail=f"不允许操作集合 {request.collection_name}，只允许: {ALLOWED_COLLECTIONS}",
        )
    
    db = mongo_manager._db
    coll = db[request.collection_name]
    
    # 聚合找出重复分组
    pipeline = [
        {
            "$group": {
                "_id": {"ts_code": "$ts_code", "trade_date": "$trade_date"},
                "count": {"$sum": 1},
                "ids": {"$push": "$_id"},
            }
        },
        {
            "$match": {"count": {"$gt": 1}},
        },
    ]
    
    # motor 异步 aggregate 需要 to_list
    cursor = coll.aggregate(pipeline)
    duplicate_groups = await cursor.to_list(length=None)
    
    total_duplicates = sum(g["count"] - 1 for g in duplicate_groups)
    
    if request.dry_run:
        return {
            "success": True,
            "data": {
                "collection_name": request.collection_name,
                "total_groups": len(duplicate_groups),
                "duplicate_groups": len([g for g in duplicate_groups if g["count"] > 1]),
                "total_duplicates": total_duplicates,
                "will_delete": total_duplicates,
                "actually_deleted": 0,
                "dry_run": True,
            },
            "message": f"干运行完成，找到 {len(duplicate_groups)} 组重复，共 {total_duplicates} 条重复记录",
        }
    
    # 实际删除重复 - 对每个重复分组，保留第一个，删除其余
    actually_deleted = 0
    for group in duplicate_groups:
        # 删除除了第一个之外的所有
        ids_to_delete = group["ids"][1:]
        result = await coll.delete_many({"_id": {"in": ids_to_delete}})
        actually_deleted += result.deleted_count
    
    logger.info(f"[admin_db] Deduplicated {request.collection_name}: deleted {actually_deleted} duplicates")
    
    return {
        "success": True,
        "data": {
            "collection_name": request.collection_name,
            "total_groups": len(duplicate_groups),
            "duplicate_groups": len(duplicate_groups),
            "total_duplicates": total_duplicates,
            "will_delete": total_duplicates,
            "actually_deleted": actually_deleted,
            "dry_run": False,
        },
        "message": f"去重完成，删除 {actually_deleted} 条重复记录",
    }


@router.post("/check-missing")
async def check_missing_data(request: CheckMissingRequest):
    """
    检查指定日期的因子缺失情况
    """
    db = mongo_manager._db
    coll = db["stock_daily_ak_full"]
    
    # 默认检查最新日期
    if request.date is None:
        latest = await coll.find({}, {"trade_date": 1}).sort([("trade_date", -1)]).limit(1).to_list(length=1)
        if not latest:
            return {
                "success": False,
                "message": "集合为空，没有数据可检查",
            }
        check_date = latest[0]["trade_date"]
    else:
        check_date = request.date
    
    # 获取当天所有股票
    cursor = coll.find({"trade_date": check_date})
    docs = await cursor.to_list(length=None)
    total_stocks = len(docs)
    
    if total_stocks == 0:
        return {
            "success": False,
            "message": f"日期 {check_date} 没有数据",
        }
    
    # 默认检查所有预计算因子
    default_factors = [
        "limit_up_amount", "limit_down_count", "circ_mv", "turnover_rate",
        "pullback_ma5", "sentiment_score", "first_limit_up", "limit_up_yesterday",
        "limit_up_count", "market_leader", "volume_ratio", "amplitude",
        "open_below_limit", "open_above_limit", "limit_up_open_amount",
        "limit_down_yesterday", "volume_increase", "limit_up_open_count",
        "hot_sector", "limit_up_time", "limit_up_open_duration",
        "pullback_pct", "pullback_days", "open_above_limit_down",
        "limit_down_open_amount", "rise_after_limit_down",
    ]
    factors_to_check = request.factors if request.factors else default_factors
    
    # 统计每个因子的缺失情况
    results = {}
    all_complete = True
    
    for factor in factors_to_check:
        missing = sum(1 for doc in docs if factor not in doc or doc[factor] is None)
        missing_pct = missing / total_stocks * 100
        results[factor] = {
            "total_stocks": total_stocks,
            "missing_stocks": missing,
            "missing_pct": round(missing_pct, 2),
        }
        if missing_pct > 0:
            all_complete = False
    
    return {
        "success": True,
        "data": {
            "date": check_date,
            "total_stocks": total_stocks,
            "results": results,
            "date_has_all_factors": all_complete,
        },
        "message": f"检查完成，{sum(v['missing_stocks'] for v in results.values())} 个因子缺失记录",
    }


@router.post("/verify-integrity")
async def verify_integrity(
    body = Body(None)
):
    """
    验证数据完整性
    
    - 检查交易日历中每个交易日是否都有数据
    - 抽样检查文档是否包含所有必填字段
    """
    db = mongo_manager._db
    
    # 完全自己处理默认值
    if body is None:
        body = {}
    # Bug 修复：body.get(key) is not None 判断错误
    # 如果前端传入 start_date: null，body.get 返回 None → 使用默认值正确
    # 但是，即使前端不传键，body.get 也返回 None → 使用默认值正确
    start_date = body.get("start_date") if body.get("start_date") is not None else 20250101
    end_date = body.get("end_date") if body.get("end_date") is not None else 20261231
    sample_size = body.get("sample_size") if body.get("sample_size") is not None else 100
    
    # Bug 修复：强制转换为 int，防止字符串类型导致查询失败
    start_date = int(start_date)
    end_date = int(end_date)
    
    # 获取交易日历
    trade_cal = db["trade_cal"]
    # motor async find
    cursor = trade_cal.find(
        {
            "cal_date": {
                "$gte": start_date,
                "$lte": end_date,
            }
        },
        {
            "cal_date": 1
        }
    )
    trading_days = await cursor.to_list(length=None)
    
    trading_dates = [d["cal_date"] for d in trading_days if d.get("is_open", 1)]
    total_trading_days = len(trading_dates)
    
    if total_trading_days == 0:
        return {
            "success": False,
            "message": f"指定范围 {start_date} ~ {end_date} 没有交易日",
        }
    
    # 检查每个交易日的文档数
    coll = db["stock_daily_ak_full"]
    daily_checks = []
    complete_days = 0
    
    expected_stocks_per_day = 5000  # 预期大约 5k 只
    threshold_pct = 0.8  # 少于 80% 视为不完整
    
    for date in trading_dates:
        count = await coll.count_documents({"trade_date": date})
        expected_count = expected_stocks_per_day
        if count >= int(expected_count * threshold_pct):
            complete = True
            complete_days += 1
        else:
            complete = False
        
        daily_checks.append({
            "date": date,
            "expected_count": expected_count,
            "actual_count": count,
            "complete": complete,
            "missing_pct": round(100 - count / expected_count * 100, 2),
        })
    
    # 抽样检查必填字段
    # 必填字段列表（所有预计算因子）
    required_fields = [
        "ts_code", "trade_date", "open", "high", "low", "close", 
        "vol", "amount", "pct_chg",
        "limit_up_amount", "limit_down_count", "circ_mv", "turnover_rate",
        "pullback_ma5", "sentiment_score", "first_limit_up", 
        "limit_up_yesterday", "limit_up_count", "market_leader",
    ]
    
    total_checked = 0
    total_missing = 0
    missing_by_field: Dict[str, int] = {f: 0 for f in required_fields}
    
    # 随机抽样
    sample_pipeline = [
        {"$match": {"trade_date": {"$gte": start_date, "$lte": end_date}}},
        {"$sample": {"size": sample_size}},
    ]
    cursor = coll.aggregate(sample_pipeline)
    sample_docs = await cursor.to_list(length=sample_size)
    
    for doc in sample_docs:
        total_checked += 1
        for field in required_fields:
            if field not in doc or doc[field] is None:
                total_missing += 1
                missing_by_field[field] += 1
    
    # 总体结论
    completion_pct = complete_days / total_trading_days * 100
    is_healthy = completion_pct >= 95 and total_missing == 0
    
    return {
        "success": True,
        "data": {
            "date_range": {
                "start": start_date,
                "end": end_date,
                "total_days": total_trading_days,
                "trading_days": total_trading_days,
            },
            "trading_days_check": daily_checks,
            "field_check": {
                "total_docs_checked": total_checked,
                "total_fields_expected": total_checked * len(required_fields),
                "total_fields_missing": total_missing,
                "missing_by_field": missing_by_field,
            },
            "overall": {
                "complete_days": complete_days,
                "incomplete_days": total_trading_days - complete_days,
                "completion_pct": round(completion_pct, 2),
                "is_healthy": is_healthy,
            },
        },
        "message": f"完整性校验完成，{complete_days}/{total_trading_days} 天完整，完成度 {completion_pct:.1f}%",
    }
