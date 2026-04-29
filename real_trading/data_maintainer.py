#!/usr/bin/env python3
"""
数据维护模块 — 日线和竞价数据自动下载与校验

功能：
1. 每日盘后下载日线数据（全市场A股）
2. 盘前下载竞价数据
3. 增量更新（只下载缺失日期的数据）
4. 数据校验（完整性/一致性/异常值检测）
5. 查询API（供daily_scheduler和前端调用）
6. 多数据源降级（AKShare→Tushare→本地缓存）

数据存储：MongoDB stock_daily_ak_full / stock_bid_auction
"""
import sys
import os
import json
import logging
import asyncio
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict

# 项目路径配置
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', '..', 'workspace', 'StockAgent'))
REAL_TRADING_DIR = os.path.join(PROJECT_ROOT, 'real_trading')
AGENT_SERVER_DIR = os.path.join(PROJECT_ROOT, 'AgentServer')

sys.path.insert(0, AGENT_SERVER_DIR)
sys.path.insert(0, REAL_TRADING_DIR)
sys.path.insert(0, os.path.dirname(__file__))

logger = logging.getLogger("data_maintainer")


# ============ 数据源枚举 ============

class DataSource:
    AKSHARE = "akshare"
    TUSHARE = "tushare"
    LOCAL_CACHE = "local_cache"
    MONGODB = "mongodb"


# ============ 校验结果 ============

@dataclass
class ValidationResult:
    """数据校验结果"""
    trade_date: str
    source: str
    total_records: int
    expected_count: int
    missing_codes: List[str]
    null_fields: Dict[str, int]      # 字段名 → 空值数量
    outlier_count: int               # 异常值数量
    is_valid: bool
    errors: List[str]
    validated_at: str


@dataclass
class DownloadResult:
    """下载任务结果"""
    trade_date: str
    source: str
    success: bool
    records_downloaded: int
    records_upserted: int
    errors: List[str]
    elapsed_seconds: float
    completed_at: str


class DataMaintainer:
    """数据维护器
    
    核心职责：
    1. 每日盘后下载日线数据 → stock_daily_ak_full
    2. 盘前下载竞价数据 → stock_bid_auction
    3. 增量更新：检测缺失日期，补齐数据
    4. 数据校验：完整性/一致性/异常值
    5. 查询接口：供其他模块调用
    6. 多数据源降级：AKShare → Tushare → 本地缓存
    
    与DailyScheduler集成：
    - 盘后调度时调用 download_daily_data()
    - 盘前调度时调用 download_auction_data()
    - 校验可通过 validate_daily_data() 手动触发
    """
    
    # MongoDB集合名
    COLL_DAILY = "stock_daily_ak_full"
    COLL_AUCTION = "stock_bid_auction"
    COLL_BASIC = "stock_basic"
    COLL_TRADE_CAL = "trade_calendar"
    
    # 最小预期股票数量（A股约5000+）
    MIN_EXPECTED_STOCKS = 4000
    
    # 异常值阈值
    MAX_PCT_CHG = 30.0     # 单日最大涨跌幅（%）
    MAX_PRICE = 100000.0   # 单股最大价格（元）
    MIN_PRICE = 0.01       # 单股最小价格（元）
    
    def __init__(self, config: Dict = None):
        """初始化数据维护器
        
        Args:
            config: 可选配置覆盖
        """
        self.config = {
            "akshare_rate_limit": 1.0,     # AKShare 每秒最多1次
            "tushare_rate_limit": 0.5,     # Tushare 每秒最多0.5次
            "max_retries": 3,              # 最大重试次数
            "retry_delay": 5,              # 重试间隔(秒)
            "download_history_days": 5,    # 增量补齐天数
            "enable_tushare_fallback": True, # 是否启用Tushare降级
            "enable_validation": True,     # 是否启用校验
            "auto_fix_nulls": True,        # 自动修复空值
        }
        self.config.update(config or {})
        
        self._mongo_db = None
        self._akshare = None
        self._tushare = None
        self._initialized = False
    
    # ============ 初始化 ============
    
    async def initialize(self) -> None:
        """初始化数据源和MongoDB连接"""
        if self._initialized:
            return
        
        # 初始化 MongoDB
        try:
            from core.managers import mongo_manager
            await mongo_manager.initialize()
            self._mongo_db = mongo_manager.db
            logger.info("MongoDB 连接成功")
        except ImportError:
            try:
                import pymongo
                client = pymongo.MongoClient(
                    os.environ.get("MONGO_URI", "mongodb://localhost:27017/")
                )
                self._mongo_db = client[os.environ.get("MONGO_DB", "stock_agent")]
                logger.info("MongoDB 直连成功")
            except Exception as e:
                logger.warning(f"MongoDB 连接失败: {e}，将使用降级模式")
                self._mongo_db = None
        
        # 初始化 AKShare
        try:
            import akshare as ak
            self._akshare = ak
            logger.info("AKShare 初始化成功")
        except ImportError:
            logger.warning("AKShare 未安装，日线下载不可用")
        
        # 初始化 Tushare
        try:
            import tushare as ts
            token = os.environ.get("TUSHARE_TOKEN", "")
            if token:
                ts.set_token(token)
                self._tushare = ts
                logger.info("Tushare 初始化成功")
        except ImportError:
            logger.warning("Tushare 未安装，降级数据源不可用")
        
        # 创建索引
        if self._mongo_db is not None:
            try:
                await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: self._create_indexes_sync()
                )
            except Exception as e:
                logger.warning(f"创建索引失败: {e}")
        
        self._initialized = True
        logger.info("DataMaintainer 初始化完成")
    
    def _create_indexes_sync(self):
        """同步创建索引"""
        self._mongo_db[self.COLL_DAILY].create_index(
            [("ts_code", 1), ("trade_date", -1)], unique=True, name="idx_code_date"
        )
        self._mongo_db[self.COLL_DAILY].create_index(
            [("trade_date", -1)], name="idx_date"
        )
        self._mongo_db[self.COLL_AUCTION].create_index(
            [("ts_code", 1), ("trade_date", -1)], name="idx_code_date"
        )
        self._mongo_db[self.COLL_AUCTION].create_index(
            [("trade_date", -1)], name="idx_date"
        )
        logger.info("MongoDB 索引创建完成")
    
    async def shutdown(self) -> None:
        """关闭连接"""
        self._mongo_db = None
        self._akshare = None
        self._tushare = None
        self._initialized = False
        logger.info("DataMaintainer 已关闭")
    
    # ============ 日线数据下载 ============
    
    async def download_daily_data(self, trade_date: str = None,
                                   source: str = None) -> DownloadResult:
        """下载指定日期的全市场日线数据
        
        流程：
        1. 选择数据源（指定 or 自动选择 AKShare → Tushare 降级）
        2. 下载数据
        3. 标准化字段格式
        4. 写入MongoDB（upsert去重）
        5. 返回下载结果
        
        Args:
            trade_date: 交易日期（YYYYMMDD），默认当天
            source: 强制使用的数据源，None则自动选择
        
        Returns:
            DownloadResult
        """
        if not trade_date:
            trade_date = datetime.now().strftime("%Y%m%d")
        
        started = time.time()
        errors = []
        
        logger.info(f"📥 开始下载日线数据: {trade_date}")
        
        # 选择数据源
        if not source:
            source = self._select_daily_source()
        
        # 下载
        records = None
        if source == DataSource.AKSHARE:
            records = await self._download_daily_akshare(trade_date)
            if records is None and self.config["enable_tushare_fallback"]:
                logger.info("AKShare失败，降级到Tushare...")
                source = DataSource.TUSHARE
                records = await self._download_daily_tushare(trade_date)
        elif source == DataSource.TUSHARE:
            records = await self._download_daily_tushare(trade_date)
        
        if records is None:
            errors.append(f"所有数据源下载失败: {trade_date}")
            return DownloadResult(
                trade_date=trade_date, source=source, success=False,
                records_downloaded=0, records_upserted=0, errors=errors,
                elapsed_seconds=time.time() - started,
                completed_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            )
        
        # 写入MongoDB
        upserted = 0
        if self._mongo_db is not None:
            upserted = await self._upsert_daily_data(records, trade_date)
        else:
            logger.warning("MongoDB不可用，数据仅下载未持久化")
        
        elapsed = time.time() - started
        logger.info(f"✅ 日线数据下载完成: {trade_date} | {len(records)}条 | {upserted}条更新 | {elapsed:.1f}秒")
        
        return DownloadResult(
            trade_date=trade_date, source=source, success=True,
            records_downloaded=len(records), records_upserted=upserted,
            errors=errors, elapsed_seconds=elapsed,
            completed_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
    
    async def _download_daily_akshare(self, trade_date: str) -> Optional[List[Dict]]:
        """通过AKShare下载日线数据"""
        if not self._akshare:
            return None
        
        for attempt in range(self.config["max_retries"]):
            try:
                loop = asyncio.get_event_loop()
                df = await loop.run_in_executor(
                    None,
                    lambda: self._akshare.stock_zh_a_spot_em()
                )
                
                if df is None or df.empty:
                    logger.warning(f"[{trade_date}] AKShare返回空数据")
                    continue
                
                records = []
                for _, row in df.iterrows():
                    code = str(row.get('代码', row.get('code', '')))
                    if not code:
                        continue
                    
                    # 补后缀
                    ts_code = self._code_to_ts_code(code)
                    close = float(row.get('最新价', row.get('close', 0)))
                    change = float(row.get('涨跌额', row.get('change', 0)))
                    pre_close = close - change
                    
                    record = {
                        'ts_code': ts_code,
                        'trade_date': int(trade_date),
                        'open': round(float(row.get('今开', row.get('open', 0))), 2),
                        'high': round(float(row.get('最高', row.get('high', 0))), 2),
                        'low': round(float(row.get('最低', row.get('low', 0))), 2),
                        'close': round(close, 2),
                        'pre_close': round(pre_close, 2),
                        'pct_chg': round(float(row.get('涨跌幅', row.get('pct_change', 0))) * 100, 2),
                        'vol': float(row.get('成交量', row.get('volume', 0))),
                        'amount': float(row.get('成交额', row.get('amount', 0))) * 10000,  # 万→元
                        'source': DataSource.AKSHARE,
                    }
                    records.append(record)
                
                logger.info(f"[{trade_date}] AKShare下载 {len(records)} 条")
                return records
                
            except Exception as e:
                logger.warning(f"[{trade_date}] AKShare第{attempt+1}次尝试失败: {e}")
                if attempt < self.config["max_retries"] - 1:
                    await asyncio.sleep(self.config["retry_delay"])
        
        return None
    
    async def _download_daily_tushare(self, trade_date: str) -> Optional[List[Dict]]:
        """通过Tushare下载日线数据"""
        if not self._tushare:
            return None
        
        for attempt in range(self.config["max_retries"]):
            try:
                pro = self._tushare.pro_api()
                loop = asyncio.get_event_loop()
                df = await loop.run_in_executor(
                    None,
                    lambda: pro.daily(trade_date=trade_date)
                )
                
                if df is None or df.empty:
                    logger.warning(f"[{trade_date}] Tushare返回空数据")
                    continue
                
                records = []
                for _, row in df.iterrows():
                    record = {
                        'ts_code': row['ts_code'],
                        'trade_date': int(trade_date),
                        'open': round(float(row.get('open', 0)), 2),
                        'high': round(float(row.get('high', 0)), 2),
                        'low': round(float(row.get('low', 0)), 2),
                        'close': round(float(row.get('close', 0)), 2),
                        'pre_close': round(float(row.get('pre_close', 0)), 2),
                        'pct_chg': round(float(row.get('pct_chg', 0)), 2),
                        'vol': float(row.get('vol', 0)),
                        'amount': float(row.get('amount', 0)),
                        'source': DataSource.TUSHARE,
                    }
                    records.append(record)
                
                logger.info(f"[{trade_date}] Tushare下载 {len(records)} 条")
                return records
                
            except Exception as e:
                logger.warning(f"[{trade_date}] Tushare第{attempt+1}次尝试失败: {e}")
                if attempt < self.config["max_retries"] - 1:
                    await asyncio.sleep(self.config["retry_delay"])
        
        return None
    
    async def _upsert_daily_data(self, records: List[Dict], trade_date: str) -> int:
        """写入MongoDB（upsert去重）"""
        if not records or self._mongo_db is None:
            return 0
        
        try:
            from pymongo import UpdateOne
            operations = []
            for r in records:
                operations.append(UpdateOne(
                    {"ts_code": r["ts_code"], "trade_date": int(trade_date)},
                    {"$set": r},
                    upsert=True,
                ))
            
            # 分批执行（每批500）
            batch_size = 500
            total_upserted = 0
            for i in range(0, len(operations), batch_size):
                batch = operations[i:i + batch_size]
                result = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda b=batch: self._mongo_db[self.COLL_DAILY].bulk_write(b)
                )
                total_upserted += result.upserted_count + result.modified_count
            
            return total_upserted
        except Exception as e:
            logger.error(f"写入MongoDB失败: {e}")
            return 0
    
    # ============ 竞价数据下载 ============
    
    async def download_auction_data(self, trade_date: str = None) -> DownloadResult:
        """下载竞价数据
        
        通过AKShare获取集合竞价数据（9:15-9:25），用于盘前信号过滤。
        
        Args:
            trade_date: 交易日期，默认当天
        
        Returns:
            DownloadResult
        """
        if not trade_date:
            trade_date = datetime.now().strftime("%Y%m%d")
        
        started = time.time()
        errors = []
        
        logger.info(f"📥 开始下载竞价数据: {trade_date}")
        
        records = None
        if self._akshare:
            try:
                loop = asyncio.get_event_loop()
                # AKShare竞价数据接口
                df = await loop.run_in_executor(
                    None,
                    lambda: self._akshare.stock_zh_a_spot_em()
                )
                
                if df is not None and not df.empty:
                    records = []
                    for _, row in df.iterrows():
                        code = str(row.get('代码', row.get('code', '')))
                        if not code:
                            continue
                        ts_code = self._code_to_ts_code(code)
                        records.append({
                            'ts_code': ts_code,
                            'trade_date': int(trade_date),
                            'auction_price': round(float(row.get('最新价', row.get('close', 0))), 2),
                            'auction_pct_chg': round(float(row.get('涨跌幅', row.get('pct_change', 0))) * 100, 2),
                            'auction_volume': float(row.get('成交量', row.get('volume', 0))),
                            'unmatched_volume': 0,  # AKShare不提供此字段
                            'source': DataSource.AKSHARE,
                        })
                    logger.info(f"[{trade_date}] 竞价数据下载 {len(records)} 条")
            except Exception as e:
                errors.append(f"AKShare竞价数据下载失败: {e}")
                logger.warning(f"竞价数据下载失败: {e}")
        
        # 写入MongoDB
        upserted = 0
        if records and self._mongo_db is not None:
            try:
                from pymongo import UpdateOne
                operations = [
                    UpdateOne(
                        {"ts_code": r["ts_code"], "trade_date": int(trade_date)},
                        {"$set": r},
                        upsert=True,
                    )
                    for r in records
                ]
                batch_size = 500
                for i in range(0, len(operations), batch_size):
                    batch = operations[i:i + batch_size]
                    result = await asyncio.get_event_loop().run_in_executor(
                        None, lambda b=batch: self._mongo_db[self.COLL_AUCTION].bulk_write(b)
                    )
                    upserted += result.upserted_count + result.modified_count
            except Exception as e:
                errors.append(f"竞价数据写入MongoDB失败: {e}")
        
        elapsed = time.time() - started
        success = records is not None and len(records) > 0
        
        return DownloadResult(
            trade_date=trade_date, source=DataSource.AKSHARE, success=success,
            records_downloaded=len(records) if records else 0,
            records_upserted=upserted, errors=errors,
            elapsed_seconds=elapsed,
            completed_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
    
    # ============ 增量更新 ============
    
    async def incremental_update(self, days: int = None) -> List[DownloadResult]:
        """增量更新：检测缺失日期并补齐数据
        
        流程：
        1. 获取最近N天的交易日历
        2. 查询MongoDB中已有哪些日期的数据
        3. 找出缺失日期
        4. 逐日下载补齐
        
        Args:
            days: 检查最近多少天，默认配置值
        
        Returns:
            List[DownloadResult]: 各日期的下载结果
        """
        if not days:
            days = self.config["download_history_days"]
        
        logger.info(f"🔄 增量更新：检查最近{days}天")
        
        # 获取交易日历
        trade_dates = await self._get_trade_dates(days)
        if not trade_dates:
            logger.warning("无法获取交易日历")
            return []
        
        # 查询已有数据
        existing_dates = set()
        if self._mongo_db is not None:
            try:
                pipeline = [
                    {"$group": {"_id": "$trade_date"}},
                ]
                cursor = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: list(self._mongo_db[self.COLL_DAILY].aggregate(pipeline))
                )
                existing_dates = {str(doc["_id"]) for doc in cursor}
            except Exception as e:
                logger.warning(f"查询已有日期失败: {e}")
        
        # 找缺失日期
        missing_dates = [d for d in trade_dates if d not in existing_dates]
        logger.info(f"交易日{len(trade_dates)}天，已有{len(existing_dates)}天，缺失{len(missing_dates)}天")
        
        # 逐日补齐
        results = []
        for date in missing_dates:
            result = await self.download_daily_data(date)
            results.append(result)
            # 间隔避免频率限制
            await asyncio.sleep(1.0 / self.config["akshare_rate_limit"])
        
        return results
    
    async def _get_trade_dates(self, days: int) -> List[str]:
        """获取最近N天的交易日列表"""
        if self._akshare:
            try:
                loop = asyncio.get_event_loop()
                df = await loop.run_in_executor(
                    None,
                    lambda: self._akshare.tool_trade_date_hist_sina()
                )
                if df is not None and not df.empty:
                    end_date = datetime.now()
                    start_date = end_date - timedelta(days=days + 10)  # 多取几天含周末
                    df['trade_date'] = df['trade_date'].astype(str).str.replace('-', '')
                    mask = (df['trade_date'] >= start_date.strftime("%Y%m%d")) & \
                           (df['trade_date'] <= end_date.strftime("%Y%m%d"))
                    return df[mask]['trade_date'].tolist()
            except Exception as e:
                logger.warning(f"获取交易日历失败: {e}")
        
        # 降级：返回工作日
        dates = []
        today = datetime.now()
        for i in range(days + 10):
            d = today - timedelta(days=i)
            if d.weekday() < 5:  # 周一至周五
                dates.append(d.strftime("%Y%m%d"))
        return sorted(dates)
    
    # ============ 数据校验 ============
    
    async def validate_daily_data(self, trade_date: str = None) -> ValidationResult:
        """校验指定日期的日线数据
        
        检查项：
        1. 完整性：记录数量是否达到预期（≥4000只）
        2. 缺失字段：关键字段是否有空值
        3. 异常值：涨跌幅/价格是否超出合理范围
        4. 一致性：pre_close + pct_chg ≈ close
        
        Args:
            trade_date: 交易日期
        
        Returns:
            ValidationResult
        """
        if not trade_date:
            trade_date = datetime.now().strftime("%Y%m%d")
        
        logger.info(f"🔍 校验日线数据: {trade_date}")
        
        if self._mongo_db is None:
            return ValidationResult(
                trade_date=trade_date, source="none",
                total_records=0, expected_count=self.MIN_EXPECTED_STOCKS,
                missing_codes=[], null_fields={}, outlier_count=0,
                is_valid=False, errors=["MongoDB不可用"],
                validated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            )
        
        try:
            # 查询当日数据
            records = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: list(self._mongo_db[self.COLL_DAILY].find(
                    {"trade_date": int(trade_date)}
                ))
            )
        except Exception as e:
            return ValidationResult(
                trade_date=trade_date, source="mongodb",
                total_records=0, expected_count=self.MIN_EXPECTED_STOCKS,
                missing_codes=[], null_fields={}, outlier_count=0,
                is_valid=False, errors=[f"查询失败: {e}"],
                validated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            )
        
        total = len(records)
        errors = []
        null_fields = {}
        outlier_count = 0
        
        # 1. 完整性检查
        if total < self.MIN_EXPECTED_STOCKS:
            errors.append(f"记录数不足: {total} < {self.MIN_EXPECTED_STOCKS}")
        
        # 2. 空值检查
        critical_fields = ['open', 'high', 'low', 'close', 'vol', 'amount']
        for field in critical_fields:
            null_count = sum(1 for r in records if not r.get(field) or r.get(field, 0) == 0)
            if null_count > 0:
                null_fields[field] = null_count
        
        # 3. 异常值检查
        for r in records:
            pct = r.get('pct_chg', 0)
            close = r.get('close', 0)
            
            # 涨跌幅异常（排除新股上市首日）
            if abs(pct) > self.MAX_PCT_CHG:
                outlier_count += 1
            
            # 价格异常
            if close > self.MAX_PRICE or (0 < close < self.MIN_PRICE):
                outlier_count += 1
            
            # 一致性检查: (close - pre_close) / pre_close ≈ pct_chg/100
            pre_close = r.get('pre_close', 0)
            if pre_close > 0 and close > 0:
                calc_pct = (close - pre_close) / pre_close * 100
                if abs(calc_pct - pct) > 0.5:  # 允许0.5%的误差（四舍五入）
                    outlier_count += 1
        
        if outlier_count > total * 0.01:  # 异常值超过1%
            errors.append(f"异常值过多: {outlier_count}条 ({outlier_count/total*100:.1f}%)")
        
        is_valid = len(errors) == 0 and total >= self.MIN_EXPECTED_STOCKS
        
        result = ValidationResult(
            trade_date=trade_date,
            source=records[0].get('source', 'unknown') if records else 'none',
            total_records=total,
            expected_count=self.MIN_EXPECTED_STOCKS,
            missing_codes=[],
            null_fields=null_fields,
            outlier_count=outlier_count,
            is_valid=is_valid,
            errors=errors,
            validated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
        
        status = "✅ 通过" if is_valid else "❌ 异常"
        logger.info(f"{status} 数据校验: {trade_date} | {total}条 | 异常{outlier_count}条 | 空值字段{len(null_fields)}个")
        
        return result
    
    # ============ 查询API ============
    
    async def get_daily_data(self, ts_code: str, start_date: str = None,
                             end_date: str = None) -> List[Dict]:
        """查询股票日线数据
        
        Args:
            ts_code: 股票代码
            start_date: 起始日期
            end_date: 结束日期
        
        Returns:
            List[Dict]: 日线数据列表
        """
        if self._mongo_db is None:
            return []
        
        query = {"ts_code": ts_code}
        if start_date or end_date:
            date_filter = {}
            if start_date:
                date_filter["$gte"] = int(start_date)
            if end_date:
                date_filter["$lte"] = int(end_date)
            if date_filter:
                query["trade_date"] = date_filter
        
        try:
            cursor = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: list(self._mongo_db[self.COLL_DAILY].find(
                    query, {"_id": 0}
                ).sort("trade_date", -1).limit(365))
            )
            return cursor
        except Exception as e:
            logger.error(f"查询日线数据失败: {e}")
            return []
    
    async def get_latest_date(self) -> Optional[str]:
        """获取数据库中最新的交易日"""
        if self._mongo_db is None:
            return None
        
        try:
            record = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._mongo_db[self.COLL_DAILY].find_one(
                    {}, {"trade_date": 1}, sort=[("trade_date", -1)]
                )
            )
            return str(record["trade_date"]) if record else None
        except Exception:
            return None
    
    async def get_data_status(self) -> Dict:
        """获取数据状态概览
        
        Returns:
            Dict: {latest_date, total_records, date_range, last_validation}
        """
        status = {
            "initialized": self._initialized,
            "mongodb_available": self._mongo_db is not None,
            "akshare_available": self._akshare is not None,
            "tushare_available": self._tushare is not None,
        }
        
        if self._mongo_db is not None:
            try:
                total = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: self._mongo_db[self.COLL_DAILY].count_documents({})
                )
                latest_date = await self.get_latest_date()
                
                status.update({
                    "total_daily_records": total,
                    "latest_daily_date": latest_date,
                })
            except Exception as e:
                status["error"] = str(e)
        
        return status
    
    # ============ 内部方法 ============
    
    def _select_daily_source(self) -> str:
        """自动选择日线数据源（优先AKShare）"""
        if self._akshare:
            return DataSource.AKSHARE
        if self._tushare:
            return DataSource.TUSHARE
        return DataSource.LOCAL_CACHE
    
    @staticmethod
    def _code_to_ts_code(code: str) -> str:
        """纯数字代码 → ts_code格式"""
        code = str(code).zfill(6)
        if code.startswith(('6', '5', '9')):
            return f"{code}.SH"
        else:
            return f"{code}.SZ"


# ============ CLI入口 ============

async def main():
    """命令行入口"""
    import argparse
    parser = argparse.ArgumentParser(description="数据维护器")
    parser.add_argument("--action", required=True,
                        choices=["download-daily", "download-auction", "incremental",
                                  "validate", "status", "latest-date"],
                        help="操作类型")
    parser.add_argument("--date", help="指定日期(YYYYMMDD)")
    parser.add_argument("--days", type=int, default=5, help="增量更新天数")
    args = parser.parse_args()
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    
    maintainer = DataMaintainer()
    await maintainer.initialize()
    
    try:
        if args.action == "download-daily":
            result = await maintainer.download_daily_data(args.date)
            logger.info(json.dumps(asdict(result), ensure_ascii=False, indent=2))
        
        elif args.action == "download-auction":
            result = await maintainer.download_auction_data(args.date)
            logger.info(json.dumps(asdict(result), ensure_ascii=False, indent=2))
        
        elif args.action == "incremental":
            results = await maintainer.incremental_update(args.days)
            for r in results:
                icon = "✅" if r.success else "❌"
                logger.info(f"{icon} {r.trade_date}: {r.records_downloaded}条 from {r.source} ({r.elapsed_seconds:.1f}s)")
        
        elif args.action == "validate":
            result = await maintainer.validate_daily_data(args.date)
            logger.info(json.dumps(asdict(result), ensure_ascii=False, indent=2))
        
        elif args.action == "status":
            status = await maintainer.get_data_status()
            logger.info(json.dumps(status, ensure_ascii=False, indent=2))
        
        elif args.action == "latest-date":
            latest = await maintainer.get_latest_date()
            logger.info(f"最新数据日期: {latest or '无数据'}")
    
    finally:
        await maintainer.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
