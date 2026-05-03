"""
因子计算引擎

批量计算全市场股票的因子值，支持:
- 多数据源整合 (daily, daily_basic, fina)
- 因子标准化 (Z-Score / 排名)
- 综合打分
- Redis缓存加速：同一股票同一交易日同一因子只计算一次，后续直接命中缓存
"""

import logging
import json
import gc
import os

import numpy as np
import pandas as pd

from core.managers import mongo_manager, redis_manager

from .factor_library import FactorCategory, FactorDefinition, FactorLibrary

logger = logging.getLogger(__name__)


def log_memory_usage(prefix: str = "MEM"):
    """记录当前内存使用情况"""
    try:
        import psutil
        process = psutil.Process(os.getpid())
        mem_info = process.memory_info()
        rss_mb = mem_info.rss / 1024 / 1024
        logger.info('FACTOR_ENGINE', f"{prefix}: RSS={rss_mb:.1f}MB")
    except Exception as e:
        logger.debug('FACTOR_ENGINE', f"Failed to get memory info: {e}")


class FactorEngine:
    """
    因子计算引擎

    【双模式架构设计】
    
    ▶️ 回测模式 (MODE=backtest)
        - 直接从 MongoDB stock_daily_ak_full 集合读取预计算因子
        - 跳过实时因子计算逻辑，性能提升 10-100 倍
        - 适用于大规模历史回测，数据已由 DATA_SYNC 节点预计算完成
        - 支持所有预存因子字段 (first_limit_up/hot_sector/limit_up_yesterday 等)
        
    ▶️ 实盘模式 (MODE=live)
        - 实时调用 factor_engine.compute_factors() 计算因子
        - 支持 Redis 缓存加速（缓存键格式：factor:v1:{name}:{date}）
        - 支持滚动窗口、动态指标等实时计算需求
        - 兼容盘中选股、实时监控、动态调仓等场景
        - 缓存过期时间：24小时

    职责:
    1. 批量加载股票数据
    2. 计算因子值（实盘模式）或读取预存（回测模式）
    3. 因子标准化
    4. 综合打分
    """

    async def compute_factors(
        self,
        stocks: set[str],
        trade_date: str,
        factor_configs: list[dict],
        lookback_days: int = 120,
    ) -> pd.DataFrame:
        """
        计算所有股票的因子值

        Args:
            stocks: 股票代码集合
            trade_date: 计算日期
            factor_configs: [{"name": "momentum_20d", "weight": 0.3, "direction": "asc"}, ...]
            lookback_days: 回溯天数 (用于计算滚动指标)

        Returns:
            DataFrame, columns = ["ts_code", "factor1", "factor2", ..., "composite_score"]
        """
        if not stocks:
            return pd.DataFrame()

        stocks_list = list(stocks)
        log_memory_usage(f"[{trade_date}] 因子计算开始")
        logger.info(f"FACTOR_ENGINE: Computing factors for {len(stocks_list)} stocks on {trade_date}")

        # ==================== 双模式分支 ====================
        # 回测模式：直接从 MongoDB 读取预计算因子，跳过实时计算
        from core.settings import settings
        if settings.mode == "backtest":
            logger.info('FACTOR_ENGINE', f"✅ [回测模式] 从 MongoDB 读取预计算因子: {trade_date}")
            
            # 提取需要的因子名称
            factor_names = [cfg["name"] for cfg in factor_configs]
            projection = {"ts_code": 1, "_id": 0}
            for name in factor_names:
                projection[name] = 1
            
            # 从 MongoDB 批量读取所有股票的因子值
            cursor = mongo_manager.db["stock_daily_ak_full"].find(
                {"trade_date": int(trade_date), "ts_code": {"$in": stocks_list}},
                projection=projection
            )
            docs = await cursor.to_list(length=len(stocks_list))
            
            # 组装 DataFrame
            result = pd.DataFrame(docs)
            
            # 布尔值转浮点，保持与实盘模式输出格式一致
            for col in factor_names:
                if col in result.columns:
                    result[col] = result[col].astype(float)
            
            # 标准化 & 综合打分（保持与实盘模式相同的计算逻辑）
            result = self._normalize_factors(result, factor_configs)
            result = self._compute_composite_score(result, factor_configs)
            
            log_memory_usage(f"[{trade_date}] [回测模式] 因子读取完成")
            return result
        # ==================== 双模式分支结束 ====================

        # 1. 收集所需数据
        factor_defs = [FactorLibrary.get(cfg["name"]) for cfg in factor_configs]
        factor_defs = [f for f in factor_defs if f is not None]

        if not factor_defs:
            logger.warn('FACTOR_ENGINE', "No valid factors found")
            return pd.DataFrame({"ts_code": stocks_list})

        logger.debug(f"Loading data for {len(factor_defs)} factors...")

        # 2. 加载数据
        data = await self._load_all_data(stocks_list, trade_date, factor_defs, lookback_days)
        logger.debug("Data loaded, computing factor values...")

        # 3. 计算每个因子（带Redis缓存，相同因子同一交易日直接命中缓存）
        factor_values = {}
        for factor_def in factor_defs:
            # 生成缓存key：因子名 + 交易日，所有股票都用同一个因子同一天数据
            # 正确的缓存方法：get → cache_get, setex → cache_setex (会自动添加cache:前缀)
            cache_key = f"factor:v1:{factor_def.name}:{trade_date}"
            cached = await redis_manager.cache_get(cache_key)
            
            if cached is not None:
                # 缓存命中，直接反序列化
                try:
                    values = json.loads(cached)
                    logger.info(f"FACTOR_ENGINE: ✅ Cache hit: {factor_def.name} on {trade_date}, {len(values)} stocks")
                    factor_values[factor_def.name] = values
                    continue
                except Exception as e:
                    logger.debug('FACTOR_ENGINE', f"Cache decode failed: {e}, recomputing")
            
            # 缓存未命中，重新计算
            logger.debug('FACTOR_ENGINE', f"Cache miss: {factor_def.name} on {trade_date}, computing...")
            values = self._compute_single_factor(data, factor_def, trade_date)
            factor_values[factor_def.name] = values
            
            # 存入Redis缓存，过期时间24小时
            try:
                # 序列化为JSON
                cached_data = json.dumps(values)
                await redis_manager.cache_setex(cache_key, 86400, cached_data)
                logger.debug(f"FACTOR_ENGINE: Cached: {factor_def.name} on {trade_date}, {len(values)} stocks")
            except Exception as e:
                logger.debug('FACTOR_ENGINE', f"Cache store failed: {e}")

        # 4. 组装 DataFrame
        result = pd.DataFrame({"ts_code": stocks_list})
        for factor_name, values in factor_values.items():
            result[factor_name] = result["ts_code"].map(values)

        # 5. 标准化 & 综合打分
        result = self._normalize_factors(result, factor_configs)
        result = self._compute_composite_score(result, factor_configs)

        # 🔧 内存优化:释放不再需要的变量
        del factor_values
        del stocks_list
        gc.collect()
        log_memory_usage(f"[{trade_date}] 因子计算完成")

        return result

    async def _load_all_data(
        self,
        stocks: list[str],
        end_date: str,
        factor_defs: list[FactorDefinition],
        lookback_days: int,
    ) -> dict[str, dict[str, pd.DataFrame]]:
        """
        加载所有需要的数据

        Returns:
            {
                "daily": {ts_code: DataFrame},
                "daily_basic": {ts_code: DataFrame},
                "fina": {ts_code: DataFrame},
            }
        """
        # 确定需要的数据源
        data_sources = {f.data_source for f in factor_defs}

        # 计算开始日期：取所有因子中最大的lookback_days
        from datetime import datetime, timedelta
        end_dt = datetime.strptime(end_date, "%Y%m%d")
        max_lookback = max(f.lookback_days for f in factor_defs)
        start_dt = end_dt - timedelta(days=max_lookback * 2)  # 预留空间
        # ✅ 恢复正确的历史数据查询范围！
        # ❌ 之前的粗暴修复 start_dt = max(start_dt, end_dt) 导致：
        #    - 查询范围只有一天，所有需要历史数据的因子全变成 NaN！
        #    - MA5/MA10/MA20/动量/波动率/RSI 等全废了！
        start_date = start_dt.strftime("%Y%m%d")

        data = {}

        # 加载日线数据
        if "daily" in data_sources:
            # 【P1-1修复：用$dateRange单次查询替代逐自然日循环，避免查询非交易日】
            # 旧逻辑逐自然日循环（含周末/假期），浪费约30%查询。新逻辑一次范围查询。
            stocks_set = set(stocks)
            all_result = await mongo_manager.find_many(
                "stock_daily_ak_full",
                {
                    "trade_date": {"$gte": int(start_date), "$lte": int(end_date)},
                    "ts_code": {"$in": list(stocks_set)},
                },
                projection={
                    "ts_code": 1, "trade_date": 1,
                    "open": 1, "high": 1, "low": 1, "close": 1,
                    "vol": 1, "amount": 1, "pct_chg": 1,
                    "first_limit_up": 1, "limit_up_yesterday": 1, "limit_up_count": 1,
                    "market_leader": 1, "volume_ratio": 1, "amplitude": 1,
                    "open_below_limit": 1, "open_above_limit": 1, "limit_up_open_amount": 1, "limit_down_yesterday": 1, "volume_increase": 1,
                    "limit_up_amount": 1, "limit_down_count": 1, "circ_mv": 1, "turnover_rate": 1,
                    "pullback_ma5": 1, "sentiment_score": 1,
                    "limit_up_open_count": 1, "hot_sector": 1, "limit_up_time": 1, "limit_up_open_duration": 1,
                    "pullback_pct": 1, "pullback_days": 1, "open_above_limit_down": 1,
                    "limit_down_open_amount": 1, "rise_after_limit_down": 1,
                    "opening_pct_chg": 1,
                    "up_limit": 1, "down_limit": 1, "pre_close": 1,
                },
            )

            # 按股票分组
            stock_data = {}
            for doc in all_result:
                ts_code = doc["ts_code"]
                if ts_code not in stock_data:
                    stock_data[ts_code] = []
                stock_data[ts_code].append(doc)

            # 🔧 内存优化: 使用更小的dtype减少内存占用
            daily_data = {}
            for ts_code, docs in stock_data.items():
                df = pd.DataFrame(docs).sort_values("trade_date")
                # 优化数值类型，减少内存占用
                for col in df.columns:
                    if pd.api.types.is_float_dtype(df[col]):
                        df[col] = pd.to_numeric(df[col], downcast="float")
                    elif pd.api.types.is_integer_dtype(df[col]):
                        df[col] = pd.to_numeric(df[col], downcast="integer")
                daily_data[ts_code] = df.set_index("trade_date")
            data["daily"] = daily_data

            # 🔧 内存优化: 释放临时变量
            del all_result
            del stock_data
            gc.collect()

        # 加载 daily_basic 数据
        if "daily_basic" in data_sources:
            # 【P1-1修复：用$dateRange单次查询替代逐自然日循环】
            stocks_set = set(stocks)
            all_result = await mongo_manager.find_many(
                "daily_basic",
                {
                    "trade_date": {"$gte": int(start_date), "$lte": int(end_date)},
                    "ts_code": {"$in": list(stocks_set)},
                },
                projection={
                    "ts_code": 1, "trade_date": 1,
                    "pe": 1, "pe_ttm": 1, "pb": 1, "ps": 1, "ps_ttm": 1,
                    "dv_ratio": 1, "dv_ttm": 1,
                    "turnover_rate": 1, "turnover_rate_f": 1, "volume_ratio": 1,
                    "total_mv": 1, "circ_mv": 1,
                },
            )

            # 按股票分组
            stock_data = {}
            for doc in all_result:
                ts_code = doc["ts_code"]
                if ts_code not in stock_data:
                    stock_data[ts_code] = []
                stock_data[ts_code].append(doc)

            # 🔧 内存优化: 使用更小的dtype减少内存占用
            daily_basic_data = {}
            for ts_code, docs in stock_data.items():
                df = pd.DataFrame(docs).sort_values("trade_date")
                # 优化数值类型，减少内存占用
                for col in df.columns:
                    if pd.api.types.is_float_dtype(df[col]):
                        df[col] = pd.to_numeric(df[col], downcast="float")
                    elif pd.api.types.is_integer_dtype(df[col]):
                        df[col] = pd.to_numeric(df[col], downcast="integer")
                daily_basic_data[ts_code] = df.set_index("trade_date")
            data["daily_basic"] = daily_basic_data

            # 🔧 内存优化: 释放临时变量
            del all_result
            del stock_data
            gc.collect()

        # 加载财务数据
        if "fina" in data_sources:
            data["fina"] = await self._load_fina_data(stocks)

        return data


    async def _load_fina_data(
        self,
        stocks: list[str],
    ) -> dict[str, pd.DataFrame]:
        """加载最新财务数据"""
        # 从 fina_indicator 获取最新的财务数据
        result = await mongo_manager.find_many(
            "fina_indicator",
            {"ts_code": {"$in": stocks}},
            projection={
                "ts_code": 1, "end_date": 1,
                "roe": 1, "roa": 1,
                "grossprofit_margin": 1,
                "revenue_yoy": 1, "netprofit_yoy": 1,
            },
        )

        # 每只股票取最新的一条
        stock_data = {}
        for doc in result:
            ts_code = doc["ts_code"]
            end_date = doc.get("end_date", "")

            if ts_code not in stock_data:
                stock_data[ts_code] = doc
            elif end_date > stock_data[ts_code].get("end_date", ""):
                stock_data[ts_code] = doc

        return {
            ts_code: pd.DataFrame([doc])
            for ts_code, doc in stock_data.items()
        }

    def _compute_single_factor(
        self,
        data: dict[str, dict[str, pd.DataFrame]],
        factor_def: FactorDefinition,
        trade_date: str,
    ) -> dict[str, float]:
        """计算单个因子的值"""
        result = {}
        source_data = data.get(factor_def.data_source, {})

        for ts_code, df in source_data.items():
            try:
                if df.empty:
                    continue

                # 计算因子值
                factor_series = factor_def.compute_func(df)

                # 获取指定日期的值
                if factor_def.data_source == "fina":
                    # 财务数据取最新值
                    value = factor_series.iloc[-1] if len(factor_series) > 0 else np.nan
                else:
                    # 日线数据取指定日期（转换为int类型匹配MongoDB存储格式）
                    trade_date_int = int(trade_date)
                    if trade_date_int in factor_series.index:
                        value = factor_series.loc[trade_date_int]
                    elif len(factor_series) > 0:
                        value = factor_series.iloc[-1]
                    else:
                        value = np.nan

                # 处理 NaN
                if pd.isna(value):
                    continue

                result[ts_code] = float(value)

            except Exception as e:
                logger.debug(f"Failed to compute {factor_def.name} for {ts_code}: {e}")
                continue

        return result

    def _normalize_factors(
        self,
        df: pd.DataFrame,
        factor_configs: list[dict],
    ) -> pd.DataFrame:
        """
        因子标准化 (Z-Score)

        去极值 + 标准化
        """
        for config in factor_configs:
            factor_name = config["name"]
            if factor_name not in df.columns:
                continue

            values = df[factor_name].copy()

            # 跳过全空的因子
            if values.isna().all():
                df[f"{factor_name}_norm"] = np.nan
                continue

            # 去极值 (MAD 方法)
            # 【P2-1修复：小样本时降低MAD倍数，避免极值不被裁剪】
            # 大样本(>100)：3*1.4826*MAD ≈ 4.45σ，标准去极值
            # 小样本(<=50)：2*1.4826*MAD ≈ 2.97σ，更积极裁剪极值
            n_valid = values.dropna().count()
            mad_multiplier = 3 if n_valid > 100 else 2
            median = values.median()
            mad = (values - median).abs().median()
            if mad > 0:
                upper = median + mad_multiplier * 1.4826 * mad
                lower = median - mad_multiplier * 1.4826 * mad
                values = values.clip(lower, upper)

            # Z-Score 标准化
            mean = values.mean()
            std = values.std()
            if std > 0:
                values = (values - mean) / std
            else:
                values = 0.0

            df[f"{factor_name}_norm"] = values

        return df

    def _compute_composite_score(
        self,
        df: pd.DataFrame,
        factor_configs: list[dict],
    ) -> pd.DataFrame:
        """
        计算综合得分

        根据权重加权求和，考虑因子方向
        """
        total_weight = sum(c.get("weight", 1.0) for c in factor_configs)

        if total_weight == 0:
            df["composite_score"] = 0.5
            return df

        composite = pd.Series(0.0, index=df.index)
        valid_factors = 0

        for config in factor_configs:
            factor_name = config["name"]
            norm_col = f"{factor_name}_norm"

            if norm_col not in df.columns:
                continue

            weight = config.get("weight", 1.0) / total_weight
            direction = config.get("direction")

            # 如果没有指定方向，从因子库获取
            if direction is None:
                factor_def = FactorLibrary.get(factor_name)
                direction = factor_def.direction if factor_def else "asc"

            factor_value = df[norm_col].fillna(0)

            # direction="desc" 表示越小越好，需要取反
            if direction == "desc":
                factor_value = -factor_value

            composite += weight * factor_value
            valid_factors += 1

        if valid_factors == 0:
            df["composite_score"] = 0.5
        else:
            # 转换为 0~1 排名分
            df["composite_score"] = composite.rank(pct=True)

        return df

    def select_top_stocks(
        self,
        factor_df: pd.DataFrame,
        top_n: int = 20,
    ) -> list[str]:
        """
        选出得分最高的 N 只股票
        """
        if factor_df.empty or "composite_score" not in factor_df.columns:
            return []

        # 过滤掉 NaN
        valid_df = factor_df.dropna(subset=["composite_score"])

        if valid_df.empty:
            return []

        # 按得分排序，选 Top N
        top_stocks = valid_df.nlargest(top_n, "composite_score")["ts_code"].tolist()

        return top_stocks


