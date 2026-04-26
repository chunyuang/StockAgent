"""
单股回测执行器

从node.py拆分出的单股回测执行逻辑，包含行情数据获取。
"""

from datetime import datetime
from typing import Optional, Dict

import pandas as pd

from core.managers import mongo_manager, akshare_manager
from core.utils.logger import logger

from nodes.backtest_engine.factors import FactorData
from nodes.backtest_engine.backtester import VectorizedBacktester, BacktestConfig
from nodes.backtest_engine.performance import PerformanceAnalyzer


async def execute_backtest(params: dict, node_logger) -> dict:
    """
    执行单股回测

    Args:
        params: 回测参数
        node_logger: 节点logger实例

    Returns:
        回测报告
    """
    task_id = params.get("task_id", "unknown")
    ts_code = params["ts_code"]
    start_date = params["start_date"]
    end_date = params["end_date"]

    node_logger.info(f"[{task_id}] Executing backtest: {ts_code} ({start_date} ~ {end_date})")

    # 更新状态为 running
    await mongo_manager.update_one(
        "backtest_tasks",
        {"task_id": task_id},
        {"$set": {"status": "running", "started_at": datetime.utcnow()}},
    )

    # 1. 获取行情数据
    price_data = await fetch_price_data(ts_code, start_date, end_date, node_logger)

    if price_data.empty:
        raise ValueError(f"No price data found for {ts_code}")

    node_logger.info(f"[{task_id}] Loaded {len(price_data)} days of price data")

    # 2. 构建因子数据
    factor_data = FactorData(
        ts_code=ts_code,
        start_date=start_date,
        end_date=end_date,
        price_data=price_data,
    )

    # 3. 自动计算技术指标
    if params.get("auto_technical", True):
        factor_data.add_technical_indicators()

    # 4. 配置回测
    weights = params.get("factor_weights", {})
    if not weights:
        weights = {
            "tech_rsi": 0.25,
            "tech_macd_signal": 0.25,
            "tech_price_position": 0.25,
            "tech_vol_ma5": 0.25,
        }

    config = BacktestConfig(
        initial_cash=params.get("initial_cash", 1000000),
        entry_threshold=params.get("entry_threshold", 0.7),
        exit_threshold=params.get("exit_threshold", 0.3),
        position_size=params.get("position_size", 1.0),
        factor_weights=weights,
    )

    # 5. 执行回测
    backtester = VectorizedBacktester(config)
    result = backtester.run(factor_data)

    if not result.success:
        raise ValueError(result.error_message)

    # 6. 分析绩效
    analyzer = PerformanceAnalyzer()
    metrics = analyzer.analyze(result)
    report = analyzer.generate_report(result, metrics)

    node_logger.info(
        f"[{task_id}] Backtest completed: "
        f"return={metrics.total_return_pct:.2f}%, "
        f"sharpe={metrics.sharpe_ratio:.2f}, "
        f"max_dd={metrics.max_drawdown_pct:.2f}%"
    )

    return report


async def fetch_price_data(
    ts_code: str,
    start_date: str,
    end_date: str,
    node_logger,
) -> pd.DataFrame:
    """从数据库获取行情数据，不存在则自动从AKShare下载。
    查询失败时返回空DataFrame，不导致回测崩溃。
    """
    records = []
    try:
        records = await mongo_manager.find_many(
            "stock_daily_ak_full",
            {
                "ts_code": ts_code,
                "trade_date": {"$gte": int(start_date), "$lte": int(end_date)},
            },
            sort=[("trade_date", 1)],
        )
    except (ConnectionError, OSError, ValueError) as e:
        node_logger.warning(f"查询{ts_code}行情数据失败: {e}，尝试从AKShare下载")
    except Exception as e:
        node_logger.warning(f"查询{ts_code}行情数据异常: {e}，尝试从AKShare下载")

    if not records:
        node_logger.info(f"本地没有{ts_code} {start_date}~{end_date}数据,尝试从AKShare下载...")
        try:
            try:
                start_dt = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}"
                end_dt = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}"
            except (IndexError, TypeError) as e:
                node_logger.warning(f"日期格式转换失败: start={start_date}, end={end_date}, error={e}")
                return pd.DataFrame()

            df_ak = await akshare_manager.get_daily(ts_code, start_dt, end_dt)
            if df_ak.empty:
                node_logger.warning(f"AKShare没有获取到{ts_code}的数据")
                return pd.DataFrame()

            records_to_insert = []
            for _, row in df_ak.iterrows():
                trade_date = row["trade_date"].strftime("%Y%m%d") if hasattr(row["trade_date"], 'strftime') else str(row["trade_date"]).replace("-", "")
                record = {
                    "ts_code": ts_code,
                    "trade_date": trade_date,
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "vol": float(row["vol"]) if "vol" in row else float(row["volume"]),
                    "amount": float(row["amount"]),
                    "up_limit": float(row["up_limit"]) if "up_limit" in row else None,
                    "down_limit": float(row["down_limit"]) if "down_limit" in row else None,
                    "pct_chg": float(row["pct_chg"]) if "pct_chg" in row else None,
                    "source": "ak"
                }
                records_to_insert.append(record)

            if records_to_insert:
                for record in records_to_insert:
                    await mongo_manager.update_one(
                        "stock_daily_ak_full",
                        {"ts_code": record["ts_code"], "trade_date": record["trade_date"]},
                        {"$setOnInsert": record},
                        upsert=True
                    )

                node_logger.info(f"成功下载并保存{ts_code} {len(records_to_insert)}条日线数据")

                records = await mongo_manager.find_many(
                    "stock_daily_ak_full",
                    {
                        "ts_code": ts_code,
                        "trade_date": {"$gte": int(start_date), "$lte": int(end_date)},
                    },
                    sort=[("trade_date", 1)],
                )

        except Exception as e:
            node_logger.error(f"从AKShare下载{ts_code}数据失败: {e}")
            return pd.DataFrame()

    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records)
    df["trade_date"] = pd.to_datetime(df["trade_date"], format="%Y%m%d")
    df.set_index("trade_date", inplace=True)
    df.sort_index(inplace=True)

    column_map = {
        "open": "open",
        "high": "high",
        "low": "low",
        "close": "close",
        "vol": "volume",
        "amount": "amount",
        "up_limit": "up_limit",
        "down_limit": "down_limit",
    }
    df = df.rename(columns=column_map)

    required = ["open", "high", "low", "close", "volume"]
    for col in required:
        if col not in df.columns:
            if col == "volume" and "vol" in df.columns:
                df["volume"] = df["vol"]
            else:
                raise ValueError(f"Missing required column: {col}")

    return df
