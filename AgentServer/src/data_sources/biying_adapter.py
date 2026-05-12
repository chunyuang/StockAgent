"""
必盈API数据源适配器

实现AsyncDataSourceAdapter接口，将必盈API接入数据源管理器。
核心优势: 纯HTTP REST(Linux原生)、无IP限制、涨停池数据丰富、五档盘口。

免费版: 200次/天 | 包年版(¥688): 不限请求, 3000次/分

已验证接口:
- /hslt/list/licence             → 股票列表
- /hslt/ztgc/日期/licence         → 涨停股池(封板资金/连板/炸板次数)
- /hslt/dtgc/日期/licence         → 跌停股池
- /hslt/zbgc/日期/licence         → 炸板股池
- /hslt/qsgc/日期/licence         → 强势股池
- /hsstock/real/time/代码/licence → 实时行情(PE/PB/换手率)
- /hsstock/real/five/代码/licence → 买卖五档
"""

import asyncio
import logging
from datetime import datetime, date
from typing import Optional, List, Dict, Any

import aiohttp

from .base import (
    AsyncDataSourceAdapter,
    DataSourceCapability,
    TokenBucket,
    StockBasicRecord,
    RealtimeQuoteRecord,
    LimitListRecord,
)

logger = logging.getLogger(__name__)


class BiyingAdapter(AsyncDataSourceAdapter):
    """必盈API数据源适配器

    优先用于:
    - 涨停/跌停/炸板股池(封板资金/连板数/炸板次数 — 打板策略核心)
    - 实时行情(PE/PB/换手率 — 筛选条件)
    - 买卖五档盘口(入场时机判断)
    - 纯HTTP REST, Linux原生, 无终端依赖, 无IP限制
    """

    name = "biying"
    description = "必盈API数据平台"
    priority = 10  # 默认优先级(量脉5, 必盈10, 可配置)
    
    @property
    def source_type(self) -> str:
        return "biying"
    
    @property
    def capability(self) -> DataSourceCapability:
        return self.get_capabilities()
    
    def _get_default_priority(self) -> int:
        return self.priority

    BASE_URL = "https://api.biyingapi.com"

    def __init__(self, licence: str = None, **kwargs):
        super().__init__(**kwargs)
        self._licence = licence
        self._session: Optional[aiohttp.ClientSession] = None
        # 免费版200次/天 → 约0.0023次/秒, 但我们用令牌桶做分钟级限流
        # 策略: 每分钟最多5次(200/天 ÷ 8小时 ÷ 60分 ≈ 0.4次/分, 留余量)
        self._bucket = TokenBucket(rate=5.0 / 60, capacity=10)  # 5次/分, 突发10次
        self._daily_calls = 0
        self._daily_limit = 200
        self._daily_reset_date = None

    @property
    def licence(self):
        return self._licence

    @property
    def daily_calls(self):
        return self._daily_calls

    @property
    def daily_remaining(self):
        return max(0, self._daily_limit - self._daily_calls)

    def get_capabilities(self) -> DataSourceCapability:
        return DataSourceCapability(
            stock_basic=True,
            daily_quotes=False,       # 必盈日K需确认URL
            daily_basic=False,        # PE/PB在实时行情里有
            realtime_quotes=True,     # ✅ 核心
            financial_data=False,
            money_flow=False,         # URL待确认
            limit_data=True,          # ✅ 核心(涨停/跌停/炸板池)
            index_data=False,
            trade_calendar=False,
            news=False,
            kline=False,
        )

    async def initialize(self) -> bool:
        """初始化: 创建HTTP session"""
        if not self._licence:
            logger.error("[BIYING] 缺少licence")
            return False

        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=10),
            headers={"Accept": "application/json"},
        )

        # 验证licence: 拉股票列表
        try:
            data = await self._get("/hslt/list")
            if isinstance(data, list) and len(data) > 0:
                logger.info(f"[BIYING] 初始化成功, {len(data)}只股票, licence有效")
                return True
            else:
                logger.error(f"[BIYING] licence验证失败: {data}")
                return False
        except Exception as e:
            logger.error(f"[BIYING] 初始化失败: {e}")
            return False

    async def is_available(self) -> bool:
        """检查是否可用"""
        return self._session is not None and self._licence is not None

    async def shutdown(self):
        """关闭连接"""
        await self.close()

    async def close(self):
        """关闭连接"""
        if self._session:
            await self._session.close()
            self._session = None

    # ==================== 内部方法 ====================

    def _check_daily_limit(self):
        """检查每日调用限制"""
        today = date.today()
        if self._daily_reset_date != today:
            self._daily_calls = 0
            self._daily_reset_date = today

        if self._daily_calls >= self._daily_limit:
            logger.warning(f"[BIYING] 今日调用已达上限 {self._daily_limit}")
            return False
        return True

    async def _get(self, path: str) -> Any:
        """发送GET请求(带限流)"""
        if not self._check_daily_limit():
            return {"error": "daily_limit_exceeded"}

        await self._bucket.wait_and_acquire()

        url = f"{self.BASE_URL}{path}/{self._licence}"
        try:
            async with self._session.get(url) as resp:
                self._daily_calls += 1
                if resp.status == 200:
                    return await resp.json()
                else:
                    text = await resp.text()
                    logger.warning(f"[BIYING] HTTP {resp.status}: {path} → {text[:100]}")
                    return {"error": f"HTTP {resp.status}", "detail": text[:200]}
        except asyncio.TimeoutError:
            logger.warning(f"[BIYING] 超时: {path}")
            return {"error": "timeout"}
        except Exception as e:
            logger.warning(f"[BIYING] 请求失败: {path} → {e}")
            return {"error": str(e)}

    def _dm_to_tscode(self, dm: str) -> str:
        """必盈代码 → 标准ts_code
        
        必盈格式多种: 
        - 纯数字: 000001, 600519, 688001
        - 带前缀: sz000001, sh600519
        - 标准格式: 000001.SZ
        
        标准输出: 000001.SZ, 600519.SH, 688001.SH
        """
        if not dm:
            return ""
        if "." in dm:
            return dm  # 已经是标准格式
        if dm.startswith("sz") or dm.startswith("sh"):
            return dm[2:].upper() + "." + dm[:2].upper()
        # 纯数字 → 根据首位判断交易所
        if dm.startswith('6') or dm.startswith('9'):
            return f"{dm}.SH"
        elif dm.startswith('0') or dm.startswith('3'):
            return f"{dm}.SZ"
        elif dm.startswith('4') or dm.startswith('8'):
            return f"{dm}.BJ"
        else:
            return f"{dm}.SZ"  # 默认深证

    def _tscode_to_dm(self, ts_code: str) -> str:
        """标准ts_code → 必盈代码
        000001.SZ → 000001 (必盈用纯数字)
        """
        if "." in ts_code:
            return ts_code.split(".")[0]
        return ts_code

    # ==================== 股票列表 ====================

    async def get_stock_list(self) -> List[StockBasicRecord]:
        """获取股票列表"""
        data = await self._get("/hslt/list")
        if not isinstance(data, list):
            return []

        result = []
        for item in data:
            result.append(StockBasicRecord(
                ts_code=self._dm_to_tscode(item.get("dm", "")),
                symbol=item.get("dm", "").split(".")[-1].lstrip("szsh"),
                name=item.get("mc", ""),
                market="",  # 必盈不返回market字段
            ))
        return result

    # ==================== 涨停/跌停/炸板股池 ====================

    async def get_limit_up_pool(self, trade_date: str = None) -> List[LimitListRecord]:
        """获取涨停股池

        必盈字段: dm/mc/p/zf/cje/lt/zsz/hs/lbc/fbt/lbt/zj/zbc/tj/hy
        映射: zj→封板资金, lbc→连板数, zbc→炸板次数, fbt→首次封板时间
        """
        if not trade_date:
            trade_date = date.today().strftime("%Y-%m-%d")

        data = await self._get(f"/hslt/ztgc/{trade_date}")
        if not isinstance(data, list):
            return []

        result = []
        for item in data:
            result.append(LimitListRecord(
                ts_code=self._dm_to_tscode(item.get("dm", "")),
                trade_date=trade_date.replace("-", ""),
                name=item.get("mc", ""),
                industry=item.get("hy", ""),
                close=float(item.get("p", 0)),
                pct_chg=float(item.get("zf", 0)),
                amount=float(item.get("cje", 0)) / 1000,  # 元→千元
                float_mv=float(item.get("lt", 0)) / 1e8,  # 元→亿元
                total_mv=float(item.get("zsz", 0)) / 1e8,  # 元→亿元
                turnover_ratio=float(item.get("hs", 0)),
                fd_amount=float(item.get("zj", 0)) / 1000,  # 封板资金: 元→千元
                first_time=item.get("fbt", ""),
                last_time=item.get("lbt", ""),
                open_times=int(item.get("zbc", 0)),   # 炸板次数
                up_stat=item.get("tj", ""),
                limit_times=int(item.get("lbc", 0)),  # 连板数
                limit="U",
            ))
        return result

    async def get_limit_down_pool(self, trade_date: str = None) -> List[LimitListRecord]:
        """获取跌停股池"""
        if not trade_date:
            trade_date = date.today().strftime("%Y-%m-%d")

        data = await self._get(f"/hslt/dtgc/{trade_date}")
        if not isinstance(data, list):
            return []

        result = []
        for item in data:
            result.append(LimitListRecord(
                ts_code=self._dm_to_tscode(item.get("dm", "")),
                trade_date=trade_date.replace("-", ""),
                name=item.get("mc", ""),
                industry=item.get("hy", ""),
                close=float(item.get("p", 0)),
                pct_chg=float(item.get("zf", 0)),
                amount=float(item.get("cje", 0)) / 1000,
                float_mv=float(item.get("lt", 0)) / 1e8,
                total_mv=float(item.get("zsz", 0)) / 1e8,
                turnover_ratio=float(item.get("hs", 0)),
                fd_amount=float(item.get("zj", 0)) / 1000,
                first_time=item.get("lbt", ""),  # 跌停用最后封板时间
                last_time=item.get("lbt", ""),
                open_times=int(item.get("zbc", 0)),
                up_stat=item.get("tj", ""),
                limit_times=int(item.get("lbc", 0)),
                limit="D",
            ))
        return result

    async def get_broken_board_pool(self, trade_date: str = None) -> List[LimitListRecord]:
        """获取炸板股池(涨停后打开)"""
        if not trade_date:
            trade_date = date.today().strftime("%Y-%m-%d")

        data = await self._get(f"/hslt/zbgc/{trade_date}")
        if not isinstance(data, list):
            return []

        result = []
        for item in data:
            result.append(LimitListRecord(
                ts_code=self._dm_to_tscode(item.get("dm", "")),
                trade_date=trade_date.replace("-", ""),
                name=item.get("mc", ""),
                industry=item.get("hy", ""),
                close=float(item.get("p", 0)),
                pct_chg=float(item.get("zf", 0)),
                amount=float(item.get("cje", 0)) / 1000,
                float_mv=float(item.get("lt", 0)) / 1e8,
                total_mv=float(item.get("zsz", 0)) / 1e8,
                turnover_ratio=float(item.get("hs", 0)),
                fd_amount=0,  # 炸板无封单
                first_time=item.get("fbt", ""),
                last_time="",
                open_times=int(item.get("zbc", 0)),
                up_stat=item.get("tj", ""),
                limit_times=0,
                limit="U",  # 曾经涨停
            ))
        return result

    async def get_strong_pool(self, trade_date: str = None) -> List[Dict]:
        """获取强势股池"""
        if not trade_date:
            trade_date = date.today().strftime("%Y-%m-%d")

        data = await self._get(f"/hslt/qsgc/{trade_date}")
        if not isinstance(data, list):
            return []
        return data

    # ==================== 实时行情 ====================

    async def get_realtime_quote(self, ts_code: str) -> Optional[RealtimeQuoteRecord]:
        """获取单只股票实时行情

        必盈字段: p/o/h/l/yc/pc/zf/tr/pe/pb_ratio/cje/v/pv/tv/t
        """
        dm = self._tscode_to_dm(ts_code)
        data = await self._get(f"/hsstock/real/time/{dm}")

        if not isinstance(data, dict) or "detail" in data or "error" in data:
            return None

        return RealtimeQuoteRecord(
            ts_code=ts_code,
            close=float(data.get("p", 0)),
            open=float(data.get("o", 0)),
            high=float(data.get("h", 0)),
            low=float(data.get("l", 0)),
            pre_close=float(data.get("yc", 0)),
            pct_chg=float(data.get("pc", 0)),
            vol=float(data.get("v", 0)),
            amount=float(data.get("cje", 0)),
            # 必盈额外字段(存在extra里)
            _pe=float(data.get("pe", 0)) if data.get("pe") else None,
            _pb=float(data.get("pb_ratio", 0)) if data.get("pb_ratio") else None,
            _turnover_rate=float(data.get("tr", 0)) if data.get("tr") else None,
            _update_time=data.get("t", ""),
        )

    # ==================== 买卖五档 ====================

    async def get_order_book(self, ts_code: str) -> Optional[Dict]:
        """获取买卖五档盘口

        返回: {ask_price: [...], bid_price: [...], ask_vol: [...], bid_vol: [...], time: str}
        """
        dm = self._tscode_to_dm(ts_code)
        data = await self._get(f"/hsstock/real/five/{dm}")

        if not isinstance(data, dict) or "detail" in data or "error" in data:
            return None

        return {
            "ask_price": data.get("ps", []),  # 委卖价(5档)
            "bid_price": data.get("pb", []),  # 委买价(5档)
            "ask_vol": data.get("vs", []),    # 委卖量(5档)
            "bid_vol": data.get("vb", []),    # 委买量(5档)
            "time": data.get("t", ""),
        }

    # ==================== 批量实时行情(高效) ====================

    async def get_realtime_quotes_batch(self, ts_codes: List[str]) -> Dict[str, RealtimeQuoteRecord]:
        """批量获取实时行情(逐只调用, 200次/天需省着用)

        建议: 只对信号股/持仓股调用, 不要全市场扫
        """
        result = {}
        for ts_code in ts_codes:
            quote = await self.get_realtime_quote(ts_code)
            if quote:
                result[ts_code] = quote
        return result

    # ==================== 状态 ====================

    def get_status(self) -> Dict:
        """获取适配器状态"""
        return {
            "name": self.name,
            "description": self.description,
            "licence": self._licence[:8] + "..." if self._licence else "未配置",
            "daily_calls": self._daily_calls,
            "daily_limit": self._daily_limit,
            "daily_remaining": self.daily_remaining,
            "daily_reset": str(self._daily_reset_date) if self._daily_reset_date else "",
            "initialized": self._session is not None,
        }
