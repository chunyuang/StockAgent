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
from datetime import datetime
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class ReplayDataProvider:
    """从MongoDB历史数据生成模拟实时行情"""

    def __init__(self, mongo_client=None):
        self._client = mongo_client
        self._db = None
        self._cache: Dict[str, dict] = {}  # trade_date -> {ts_code: realtime_data}
        self._current_date: Optional[str] = None

    @property
    def db(self):
        if self._db is None:
            from pymongo import MongoClient
            if self._client is None:
                self._client = MongoClient('localhost', 27017)
            self._db = self._client['stock_agent']
        return self._db

    def get_replay_data(self, trade_date: str) -> Dict[str, dict]:
        """获取指定日期的模拟实时行情

        将stock_daily_ak_full日线数据转为scanner期望的格式:
        {ts_code: {price, pct_chg, turnover_rate, volume_ratio, pe, pb, ...}}

        同时从daily_basic补充PE/PB/换手率/流通市值等字段
        """
        if trade_date in self._cache:
            return self._cache[trade_date]

        logger.info(f"[REPLAY] 加载 {trade_date} 历史数据...")

        # 1. 日线数据
        daily_col = self.db['stock_daily_ak_full']
        daily_data = {}
        for doc in daily_col.find({'trade_date': trade_date}):
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

        # 2. daily_basic补充PE/PB/换手率/流通市值
        basic_col = self.db['daily_basic']
        for doc in basic_col.find({'trade_date': trade_date}):
            code = doc.get('ts_code', '')
            if code in daily_data:
                daily_data[code].update({
                    'pe': doc.get('pe_ttm'),
                    'pb': doc.get('pb'),
                    'turnover_rate': doc.get('turnover_rate'),
                    'float_mv': doc.get('circ_mv'),  # 流通市值(万元)
                    'total_mv': doc.get('total_mv'),
                })

        # 3. 涨停池/跌停池
        limit_up_col = self.db.get('limit_pool_up')
        limit_down_col = self.db.get('limit_pool_down')

        limit_up_list = []
        if limit_up_col:
            for doc in limit_up_col.find({'trade_date': trade_date}):
                code = doc.get('ts_code', '')
                item = {
                    'ts_code': code,
                    'name': daily_data.get(code, {}).get('name', doc.get('name', '')),
                    'pct_chg': daily_data.get(code, {}).get('pct_chg', 10.0),
                    'limit_times': doc.get('limit_times', 1),
                    'fd_amount': doc.get('fd_amount', 0),  # 封单金额(万)
                    'up_stat': doc.get('up_stat', ''),
                    'limit': doc.get('limit', 0),
                }
                limit_up_list.append(item)

        limit_down_list = []
        if limit_down_col:
            for doc in limit_down_col.find({'trade_date': trade_date}):
                code = doc.get('ts_code', '')
                item = {
                    'ts_code': code,
                    'name': daily_data.get(code, {}).get('name', doc.get('name', '')),
                    'pct_chg': daily_data.get(code, {}).get('pct_chg', -10.0),
                    'limit_times': doc.get('limit_times', 1),
                    'fd_amount': doc.get('fd_amount', 0),
                }
                limit_down_list.append(item)

        # 4. 计算量比 (volume_ratio) — 简化: 用当日vol / 5日均vol
        # 从最近5天数据计算
        from datetime import timedelta
        vol_cache = {}
        for doc in daily_col.find({'trade_date': trade_date}):
            vol_cache[doc.get('ts_code', '')] = doc.get('vol', 0)

        # 取前5天数据
        prev_vols = {}  # ts_code -> [vol1, vol2, ...]
        # 简化：用trade_cal找前5个交易日
        cal_col = self.db.get('trade_cal')
        if cal_col:
            prev_dates = []
            for doc in cal_col.find({'is_open': 1, 'cal_date': {'$lt': trade_date}}).sort('cal_date', -1).limit(5):
                prev_dates.append(doc['cal_date'])

            if prev_dates:
                for doc in daily_col.find({'trade_date': {'$in': prev_dates}}):
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
                data['volume_ratio'] = 1.0  # 默认

        self._cache[trade_date] = {
            'realtime': daily_data,
            'limit_up': limit_up_list,
            'limit_down': limit_down_list,
            'broken': [],  # 炸板池暂无历史数据
            'total_stocks': len(daily_data),
        }

        self._current_date = trade_date
        logger.info(
            f"[REPLAY] 加载完成: {trade_date} | "
            f"{len(daily_data)}只股票 | "
            f"涨停{len(limit_up_list)} | 跌停{len(limit_down_list)}"
        )

        return self._cache[trade_date]

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

    def clear_cache(self):
        """清除缓存"""
        self._cache.clear()
        self._current_date = None
