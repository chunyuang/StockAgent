"""
回放调试模式 — 用MongoDB历史数据模拟实时扫描

解决非开市时间无法调试的问题:
- 从stock_daily_ak_full读取指定日期的日线数据
- 转换成scanner期望的实时行情格式
- 让scan_once()以为是在真实交易时间运行

使用方式:
  POST /scanner/start  {"trade_mode": "replay", "replay_date": "20260526"}
  POST /scanner/scan-once  {"force": true, "replay_date": "20260526"}
"""

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class ReplayDataProvider:
    """从MongoDB历史数据生成模拟实时行情"""

    def __init__(self, mongo_client=None):
        self._client = mongo_client
        self._db = None
        self._cache: Dict[str, dict] = {}  # trade_date -> {ts_code: realtime_data}
        self._current_date: Optional[str] = None

    @property
    def db(self) -> Any:
        if self._db is None:
            from pymongo import MongoClient
            if self._client is None:
                self._client = MongoClient('localhost', 27017)
            self._db = self._client['stock_agent']
        return self._db

    def get_replay_data(self, trade_date: str) -> Dict[str, dict]:
        """获取指定日期的模拟实时行情(编排方法)

        将stock_daily_ak_full日线数据转为scanner期望的格式:
        {ts_code: {price, pct_chg, turnover_rate, volume_ratio, pe, pb, ...}}
        """
        if trade_date in self._cache:
            return self._cache[trade_date]

        logger.info(f"[REPLAY] 加载 {trade_date} 历史数据...")

        td_int = int(trade_date) if isinstance(trade_date, str) else trade_date

        # 1. 日线数据
        daily_data = self._load_daily_data(td_int)

        # ⚠️ 数据缺失检查
        if not daily_data:
            logger.warning(
                f"[REPLAY] ❌ {trade_date} 无数据! "
                f"MongoDB stock_daily_ak_full 中该日期0条记录。"
                f"请先补全数据: python3 scripts/eastmoney_daily_bar.py"
            )

        # 2. daily_basic补充PE/PB/换手率/流通市值
        self._enrich_daily_basic(td_int, daily_data)

        # 3. 涨停池/跌停池
        limit_up_list, limit_down_list = self._load_limit_pools(td_int, daily_data)

        # 4. 计算量比
        self._compute_volume_ratios(trade_date, td_int, daily_data)

        result = {
            'realtime': daily_data,
            'limit_up': limit_up_list,
            'limit_down': limit_down_list,
            'broken': [],
            'total_stocks': len(daily_data),
        }
        self._cache[trade_date] = result
        self._current_date = trade_date

        logger.info(
            f"[REPLAY] 加载完成: {trade_date} | "
            f"{len(daily_data)}只股票 | "
            f"涨停{len(limit_up_list)} | 跌停{len(limit_down_list)}"
        )
        return result

    def _load_daily_data(self, td_int: int) -> Dict[str, dict]:
        """从stock_daily_ak_full加载日线数据"""
        daily_col = self.db['stock_daily_ak_full']
        daily_data = {}
        for doc in daily_col.find({'trade_date': td_int}):
            code = doc.get('ts_code', '')
            if not code:
                continue
            daily_data[code] = {
                'price': doc.get('close', 0),
                'pct_chg': doc.get('pct_chg', 0),
                'open': doc.get('open', 0),
                'high': doc.get('high', 0),
                'low': doc.get('low', 0),
                'pre_close': doc.get('pre_close', 0),
                'volume': doc.get('vol', 0),
                'name': doc.get('name', ''),
            }
        return daily_data

    def _enrich_daily_basic(self, td_int: int, daily_data: Dict[str, dict]) -> None:
        """从daily_basic补充PE/PB/换手率/流通市值"""
        basic_col = self.db['daily_basic']
        for doc in basic_col.find({'trade_date': td_int}):
            code = doc.get('ts_code', '')
            if code in daily_data:
                daily_data[code].update({
                    'pe': doc.get('pe_ttm'),
                    'pb': doc.get('pb'),
                    'turnover_rate': doc.get('turnover_rate'),
                    'float_mv': doc.get('circ_mv'),
                    'total_mv': doc.get('total_mv'),
                })

    def _load_limit_pools(self, td_int: int, daily_data: Dict[str, dict]) -> tuple:
        """加载涨停池/跌停池数据"""
        limit_up_list = []
        limit_down_list = []

        if 'limit_pool_up' in self.db.list_collection_names():
            for doc in self.db['limit_pool_up'].find({'trade_date': td_int}):
                code = doc.get('ts_code', '')
                limit_up_list.append({
                    'ts_code': code,
                    'name': daily_data.get(code, {}).get('name', doc.get('name', '')),
                    'pct_chg': daily_data.get(code, {}).get('pct_chg', 10.0),
                    'limit_times': doc.get('limit_times', 1),
                    'fd_amount': doc.get('fd_amount', 0),
                    'up_stat': doc.get('up_stat', ''),
                    'limit': doc.get('limit', 0),
                })

        if 'limit_pool_down' in self.db.list_collection_names():
            for doc in self.db['limit_pool_down'].find({'trade_date': td_int}):
                code = doc.get('ts_code', '')
                limit_down_list.append({
                    'ts_code': code,
                    'name': daily_data.get(code, {}).get('name', doc.get('name', '')),
                    'pct_chg': daily_data.get(code, {}).get('pct_chg', -10.0),
                    'limit_times': doc.get('limit_times', 1),
                    'fd_amount': doc.get('fd_amount', 0),
                })

        return limit_up_list, limit_down_list

    def _compute_volume_ratios(self, trade_date, td_int: int, daily_data: Dict[str, dict]) -> None:
        """计算量比(当日vol / 5日均vol)"""
        daily_col = self.db['stock_daily_ak_full']

        # 获取前5个交易日
        prev_dates = []
        if 'trade_cal' in self.db.list_collection_names():
            for doc in self.db['trade_cal'].find(
                {'is_open': 1, 'cal_date': {'$lt': td_int}}
            ).sort('cal_date', -1).limit(5):
                prev_dates.append(doc['cal_date'])

        # 获取前5日成交量
        prev_vols: Dict[str, list] = {}
        if prev_dates:
            for doc in daily_col.find({'trade_date': {'$in': [int(d) for d in prev_dates]}}):
                code = doc.get('ts_code', '')
                if code not in prev_vols:
                    prev_vols[code] = []
                prev_vols[code].append(doc.get('vol', 0))

        # 计算量比
        for code, data in daily_data.items():
            cur_vol = data.get('volume', 0)
            pv = prev_vols.get(code, [])
            if pv and sum(pv) > 0:
                avg_vol = sum(pv) / len(pv)
                data['volume_ratio'] = round(cur_vol / avg_vol, 2) if avg_vol > 0 else 0
            else:
                data['volume_ratio'] = 1.0

    def get_realtime(self, trade_date: str) -> Dict[str, dict]:
        """获取模拟实时行情(兼容_fetch_realtime_batch返回格式)"""
        data = self.get_replay_data(trade_date)
        return data.get('realtime', {})

    def get_limit_pools(self, trade_date: str) -> dict:
        """获取模拟涨跌停池"""
        data = self.get_replay_data(trade_date)
        return {
            'limit_up': data.get('limit_up', []),
            'limit_down': data.get('limit_down', []),
            'broken': data.get('broken', []),
        }

    @property
    def is_active(self) -> bool:
        """是否处于回放模式"""
        return self._current_date is not None

    def clear_cache(self) -> None:
        """清除缓存"""
        self._cache.clear()
        self._current_date = None

# v2.9.92r: 数据缺失时返回空并记录warning
