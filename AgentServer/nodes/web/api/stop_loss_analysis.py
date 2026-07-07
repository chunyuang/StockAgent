"""
止损止盈分析 API — 展示策略配置、实盘执行、回测对比、优化前后切换
用于交易归档页面下的止损止盈子页面
"""
import logging
from typing import List, Optional
from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from core.managers import mongo_manager

router = APIRouter(prefix="/stop-loss-analysis", tags=["StopLossAnalysis"])
logger = logging.getLogger("api.stop_loss_analysis")

COL_ORDERS = "broker_orders"

# ==================== 回测止损止盈流程 ====================

BACKTEST_FLOW = {
    "title": "回测引擎止损止盈流程",
    "engine": "portfolio_backtest.py → _check_stop_loss_take_profit()",
    "check_frequency": "每日调仓时检查(使用当日OHLCV)",
    "steps": [
        {
            "step": 1,
            "name": "T+1门控",
            "desc": "当日买入的股票不可止损/止盈卖出(T+1规则)",
            "code": "buy_dt == trade_date → skip",
        },
        {
            "step": 2,
            "name": "冲高回落/利润保护/高开即卖",
            "desc": "开盘价检查: 高开后回落→以开盘价卖出; 利润保护→以收盘价卖出",
            "code": "_check_early_sell_signals() → open_p / close_p",
            "sub_rules": [
                "冲高回落: 开盘涨幅≥阈值 + 收盘回落→以open卖出",
                "利润保护: 开盘涨≥2%+收盘涨≥2%+收盘<开盘→以close卖出",
                "高开即卖: 首板策略开盘涨幅≥阈值→以open卖出",
                "利润锁定: 盘中冲高≥6%+回撤≥2.5%→以close卖出(不扣滑点)",
            ],
        },
        {
            "step": 3,
            "name": "跳空止损",
            "desc": "开盘价≤止损价→以开盘价卖出",
            "code": "open_p <= stop_price → 以open卖出",
        },
        {
            "step": 4,
            "name": "固定止损",
            "desc": "盘中最低价≤止损价→以止损价卖出(不扣滑点)",
            "code": "low_p <= stop_price → 以stop_price卖出",
        },
        {
            "step": 5,
            "name": "止盈",
            "desc": "盘中最高价≥止盈价→以止盈价卖出",
            "code": "high_p >= tp_price → 以tp_price卖出",
        },
        {
            "step": 6,
            "name": "追踪止损(跨日)",
            "desc": "多日持仓: 峰值利润回撤≥容忍幅度→以收盘价卖出",
            "code": "hold_days>1 + peak_profit - current >= trailing_pct → 以close卖出",
            "note": "与实盘对齐: 调用calc_tiered_trailing_pct()计算策略级回撤容忍",
        },
        {
            "step": 7,
            "name": "超时强卖",
            "desc": "持仓天数≥max_hold_days→以收盘价卖出",
            "code": "trade_days_held >= max_hold → 以close卖出",
        },
        {
            "step": 8,
            "name": "龙头5天低利润",
            "desc": "龙头低吸策略: 持仓≥5天且利润<3%→以收盘价卖出",
            "code": "dragon_head + hold>=5 + profit<3% → 以close卖出",
        },
    ],
    "features": [
        "✅ 止损/止盈卖出不扣滑点(止损价已保守)",
        "✅ 追踪止损调用实盘同一函数calc_tiered_trailing_pct()",
        "✅ 策略级参数从strategy_defaults.py读取(单一来源)",
        "❌ 不支持ATR自适应止损(回测使用固定stop_loss_pct)",
        "❌ 不支持分批止盈(回测全仓卖出)",
        "❌ 不支持跳空分级观察期(回测直接以open卖出)",
        "❌ 不支持高盈利紧缩(回测不检查HIGH_PROFIT_TIGHTEN)",
    ],
    "gaps_with_live": [
        "ATR自适应: 实盘有, 回测无 → 需要对齐",
        "分批止盈: 实盘有, 回测无 → 需要对齐",
        "跳空分级观察: 实盘有, 回测无 → 需要对齐",
        "高盈利紧缩: 实盘有, 回测无 → 需要对齐",
    ],
}

# ==================== 实盘止损止盈流程 ====================

LIVE_FLOW = {
    "title": "实盘止损止盈流程(优化后)",
    "engine": "position_manager.py + position_checker.py + risk_loop_runner.py",
    "check_frequency": "1秒级(风控线程) + 30秒级(快速检查) + 5分钟级(完整检查)",
    "steps": [
        {
            "step": 1,
            "name": "T+1门控",
            "desc": "当日买入的股票不可止损/止盈卖出(T+1规则)",
            "code": "available_qty == 0 → skip",
        },
        {
            "step": 2,
            "name": "跌停不可卖处理",
            "desc": "当前价触及跌停板→挂起pending_sells, 等可卖时再执行",
            "code": "_handle_limit_down() → pending_sells",
            "frequency": "1秒级",
        },
        {
            "step": 3,
            "name": "跳空止损(分级观察)",
            "desc": "开盘价<止损价→按跳空幅度分级处理",
            "code": "_check_gap_stop_with_tiered_observation()",
            "frequency": "1秒级",
            "sub_rules": [
                "微跳(<3%): 观察30分钟, 期间价格回升→取消止损",
                "中跳(3-5%): 观察10分钟",
                "大跳(>5%): 立即止损; 但大盘涨幅>0.5%且跳空<8%→观察5分钟",
                "极大跳(>8%): 立即止损, 不给观察期",
            ],
        },
        {
            "step": 4,
            "name": "固定止损(ATR自适应)",
            "desc": "盈亏≤-止损线→以当前价卖出",
            "code": "profit_pct <= -stop_loss_pct → 以current_price卖出",
            "frequency": "1秒级",
            "note": "v2.9.119: stop_loss_pct = min(max(策略下限, 1.2×ATR14%), 策略上限)",
        },
        {
            "step": 5,
            "name": "追踪止损(分级+紧缩)",
            "desc": "峰值利润回撤≥容忍幅度→以当前价卖出",
            "code": "_check_trailing_stop() → calc_tiered_trailing_pct()",
            "frequency": "1秒级",
            "sub_rules": [
                "激活阈值: max(策略trailing_stop_pct, 3%) (v2.9.118提高)",
                "回撤容忍: 5策略差异化偏移表 STRATEGY_TRAILING_OFFSETS",
                "高盈利紧缩: 盈利≥8%时回撤收紧到3% (v2.9.116)",
            ],
        },
        {
            "step": 6,
            "name": "分批止盈",
            "desc": "盈利≥8%且<止盈线→卖出50%仓位锁定利润",
            "code": "_check_partial_take_profit() → 卖half qty",
            "frequency": "30秒级/5分钟级",
            "note": "v2.9.118新增, 同一持仓只分批一次",
        },
        {
            "step": 7,
            "name": "止盈",
            "desc": "盈亏≥止盈线→以当前价全仓卖出",
            "code": "profit_pct >= take_profit_pct → 全仓卖出",
            "frequency": "30秒级/5分钟级",
        },
        {
            "step": 8,
            "name": "冲高回落/利润保护/利润锁定",
            "desc": "次日高开后回落/盘中冲高回撤→卖出",
            "code": "_check_intraday_rules()",
            "frequency": "5分钟级",
            "sub_rules": [
                "冲高回落: 开盘涨≥阈值+收盘回落→以开盘价卖出",
                "利润保护: 开盘涨≥2%+收盘涨≥2%+收盘<开盘→卖出",
                "利润锁定: 盘中冲高≥6%+回撤≥2.5%→以收盘价卖出",
            ],
        },
        {
            "step": 9,
            "name": "超时强卖",
            "desc": "持仓天数≥max_hold_days→以当前价卖出",
            "code": "check_timeout_sell()",
            "frequency": "5分钟级",
        },
        {
            "step": 10,
            "name": "强制空仓",
            "desc": "特殊时期(熔断/情绪极端)→所有持仓强制卖出",
            "code": "execute_sell_list_from_risk() → 全部清仓",
            "frequency": "5分钟级",
        },
    ],
    "features": [
        "✅ ATR自适应止损(v2.9.119): 1.2×ATR14%, 策略3-8%范围, 封顶6%",
        "✅ 分批止盈(v2.9.118): 盈利≥8%卖50%, 剩余继续持有",
        "✅ 跳空分级观察(v2.9.112-115): 微跳30min/中跳10min/大跳5min+大盘过滤",
        "✅ 高盈利紧缩(v2.9.116): 盈利≥8%回撤收紧到3%",
        "✅ 分级追踪止损(v2.9.114): 5策略差异化偏移",
        "✅ 追踪止损激活阈值提高(v2.9.118): 2%→3%",
        "✅ 跌停不可卖挂起(保护性)",
        "✅ 非连续竞价门控(仅早盘/午盘/尾盘可卖)",
    ],
}

# ==================== 实盘止损止盈流程(优化前) ====================

LIVE_FLOW_PRE = {
    "title": "实盘止损止盈流程(优化前)",
    "engine": "position_manager.py + position_checker.py + risk_loop_runner.py",
    "check_frequency": "1秒级(风控线程) + 30秒级(快速检查) + 5分钟级(完整检查)",
    "steps": [
        {
            "step": 1,
            "name": "T+1门控",
            "desc": "当日买入的股票不可止损/止盈卖出(T+1规则)",
            "code": "available_qty == 0 → skip",
        },
        {
            "step": 2,
            "name": "跌停不可卖处理",
            "desc": "当前价触及跌停板→挂起pending_sells, 等可卖时再执行",
            "code": "_handle_limit_down() → pending_sells",
            "frequency": "1秒级",
        },
        {
            "step": 3,
            "name": "跳空止损(立即执行)",
            "desc": "开盘价<止损价→立即以开盘价卖出, 无观察期",
            "code": "open_price < stop_price → 立即卖出",
            "frequency": "1秒级",
            "note": "优化前: 不区分跳空幅度, 不考虑大盘强弱",
        },
        {
            "step": 4,
            "name": "固定止损(固定百分比)",
            "desc": "盈亏≤-固定止损线→以当前价卖出",
            "code": "profit_pct <= -stop_loss_pct → 以current_price卖出",
            "frequency": "1秒级",
            "note": "优化前: 所有股票统一固定3%止损, 不考虑个股波动率",
        },
        {
            "step": 5,
            "name": "追踪止损(统一回撤)",
            "desc": "峰值利润回撤≥5%→以当前价卖出",
            "code": "_check_trailing_stop() → 固定5%回撤",
            "frequency": "1秒级",
            "sub_rules": [
                "激活阈值: 策略级(半路追涨2%/首板打板2%/涨停炸板5%/龙头低吸3%/跌停翘板4%), 非统一2%",
                "回撤容忍: 固定5%(无策略差异化)",
                "无高盈利紧缩机制",
            ],
        },
        {
            "step": 6,
            "name": "止盈(全仓卖出)",
            "desc": "盈亏≥止盈线→以当前价全仓卖出",
            "code": "profit_pct >= take_profit_pct → 全仓卖出",
            "frequency": "30秒级/5分钟级",
            "note": "优化前: 无分批止盈, 到达止盈线一次性全部卖出",
        },
        {
            "step": 7,
            "name": "冲高回落/利润保护",
            "desc": "次日高开后回落→卖出",
            "code": "_check_intraday_rules()",
            "frequency": "5分钟级",
            "sub_rules": [
                "冲高回落: 开盘涨≥阈值+收盘回落→以开盘价卖出",
                "利润保护: 开盘涨≥2%+收盘涨≥2%+收盘<开盘→卖出",
            ],
        },
        {
            "step": 8,
            "name": "超时强卖",
            "desc": "持仓天数≥max_hold_days→以当前价卖出",
            "code": "check_timeout_sell()",
            "frequency": "5分钟级",
        },
        {
            "step": 9,
            "name": "强制空仓",
            "desc": "特殊时期(熔断/情绪极端)→所有持仓强制卖出",
            "code": "execute_sell_list_from_risk() → 全部清仓",
            "frequency": "5分钟级",
        },
    ],
    "features": [
        "❌ 无ATR自适应止损(统一固定3%)",
        "❌ 无分批止盈(一次性全仓卖出)",
        "❌ 无跳空分级观察(立即止损)",
        "❌ 无高盈利紧缩机制",
        "❌ 无分级追踪止损(统一5%回撤)",
        "✅ 跌停不可卖挂起(保护性)",
        "✅ 非连续竞价门控(仅早盘/午盘/尾盘可卖)",
    ],
    "gaps_with_post": [
        "ATR自适应: 优化后根据个股波动率调整止损幅度",
        "分批止盈: 优化后盈利≥8%先卖50%锁定利润",
        "跳空分级观察: 优化后按跳空幅度给不同观察期",
        "高盈利紧缩: 优化后盈利≥8%回撤收紧到3%",
        "分级追踪止损: 优化后5策略差异化偏移",
    ],
}


# ==================== 优化前后配置 ====================

PRE_OPTIMIZATION_CONFIG = {
    "version": "v2.9.115 (优化前)",
    "stop_loss": {
        "name": "止损",
        "type": "固定止损",
        "default_pct": 3.0,
        "strategy_pct": {
            "半路追涨": 3.0,
            "首板打板": 3.5,
            "涨停炸板": 5.0,
            "龙头低吸": 3.0,
            "跌停翘板": 5.0,
        },
        "atr_adaptive": False,
        "description": "所有股票统一固定止损百分比, 不考虑个股波动率差异",
    },
    "take_profit": {
        "name": "止盈",
        "type": "固定止盈",
        "default_pct": 7.0,
        "strategy_pct": {
            "半路追涨": 12.0,
            "首板打板": 10.0,
            "涨停炸板": 6.0,
            "龙头低吸": 30.0,
            "跌停翘板": 20.0,
        },
        "partial_take_profit": False,
        "description": "到达止盈线一次性全部卖出",
    },
    "trailing_stop": {
        "name": "追踪止损",
        "type": "统一回撤追踪",
        "base_pct": 5.0,
        "activate_threshold": {
            "半路追涨": 2.0,
            "首板打板": 2.0,
            "涨停炸板": 5.0,
            "龙头低吸": 3.0,
            "跌停翘板": 4.0,
        },
        "strategy_offsets": "无差异化(统一5%基准)",
        "high_profit_tighten": False,
        "description": "盈利达激活阈值后, 从最高价回撤5%触发卖出(涨停炸板无策略级trailing_stop_pct, 用全局5%)",
    },
    "gap_stop": {
        "name": "跳空止损",
        "type": "立即执行",
        "observation_period": "无观察期, 开盘价低于止损价立即以开盘价卖出",
        "market_filter": False,
        "description": "不区分跳空幅度, 不考虑大盘强弱, 一律立即止损",
    },
}

POST_OPTIMIZATION_CONFIG = {
    "version": "v2.9.119 (优化后)",
    "stop_loss": {
        "name": "止损",
        "type": "ATR自适应止损",
        "default_pct": 3.0,
        "atr_multiplier": 1.2,
        "atr_period": 14,
        "strategy_atr_ranges": {
            "半路追涨": {"min": 3.0, "max": 6.0},
            "首板打板": {"min": 3.5, "max": 7.0},
            "涨停炸板": {"min": 4.0, "max": 7.0},
            "龙头低吸": {"min": 3.0, "max": 7.0},
            "跌停翘板": {"min": 5.0, "max": 8.0},
        },
        "atr_adaptive": True,
        "description": "止损幅度 = min(max(策略下限, 1.2×ATR14%), 策略上限), 封顶防止高波动股单笔亏损过大",
    },
    "take_profit": {
        "name": "止盈",
        "type": "分批止盈",
        "default_pct": 7.0,
        "strategy_pct": {
            "半路追涨": 12.0,
            "首板打板": 10.0,
            "涨停炸板": 6.0,
            "龙头低吸": 30.0,
            "跌停翘板": 20.0,
        },
        "partial_take_profit": True,
        "partial_threshold": 8.0,
        "partial_ratio": 0.5,
        "description": "盈利≥8%先卖50%锁定利润, 剩余继续持有等止盈或追踪止损",
    },
    "trailing_stop": {
        "name": "追踪止损",
        "type": "分级追踪止损",
        "base_pct": 5.0,
        "min_activate_pct": 3.0,
        "activate_threshold": {
            "半路追涨": "max(2%, 3%) = 3%",
            "首板打板": "max(2%, 3%) = 3%",
            "涨停炸板": "max(5%, 3%) = 5%",
            "龙头低吸": "max(3%, 3%) = 3%",
            "跌停翘板": "max(4%, 3%) = 4%",
        },
        "strategy_offsets": {
            "首板打板": "+3/+6/+10/+13%",
            "涨停炸板": "+0/+3/+6/+9%",
            "龙头低吸": "+2/+4/+7/+10%",
            "半路追涨": "+1/+3/+6/+9%",
            "跌停翘板": "+0/+2/+5/+8%",
        },
        "high_profit_tighten": True,
        "high_profit_threshold": 8.0,
        "high_profit_tighten_pct": 3.0,
        "description": "盈利≥3%激活; 5策略差异化回撤偏移; 盈利≥8%回撤收紧到3%",
    },
    "gap_stop": {
        "name": "跳空止损",
        "type": "分级跳空止损",
        "observation_period": {
            "微跳(<3%)": "观察30分钟, 期间价格回升到止损线上方→取消止损",
            "中跳(3-5%)": "观察10分钟",
            "大跳(5-8%)": "立即止损; 但大盘涨幅>0.5%且跳空<8%→观察5分钟",
            "极大跳(≥8%)": "立即止损, 不给观察期",
        },
        "market_filter": True,
        "description": "按跳空幅度分级处理, 大盘强势时给观察期避免误杀",
    },
}


# ==================== 响应模型 ====================

class FlowStep(BaseModel):
    step: int
    name: str
    desc: str
    code: str = ""
    frequency: str = ""
    note: str = ""
    sub_rules: List[str] = []

class FlowInfo(BaseModel):
    title: str
    engine: str
    check_frequency: str
    steps: List[FlowStep]
    features: List[str]
    gaps_with_live: List[str] = []
    gaps_with_post: List[str] = []

class ConfigItem(BaseModel):
    category: str
    name: str
    pre_optimization: dict
    post_optimization: dict

class ExecutionRecord(BaseModel):
    ts_code: str = ""
    stock_name: str = ""
    strategy: str = ""
    filled_price: float = 0
    filled_qty: int = 0
    profit_pct: float = 0
    profit_amount: float = 0
    reason: str = ""
    trade_date: int = 0
    fill_time: str = ""
    sell_type: str = ""

class StatsResponse(BaseModel):
    total_sells: int = 0
    total_pnl: float = 0
    win_rate: float = 0
    by_type: List[dict] = []


# ==================== API ====================

@router.get("/flow/backtest", response_model=FlowInfo)
async def get_backtest_flow():
    """获取回测引擎止损止盈流程"""
    return FlowInfo(**BACKTEST_FLOW)


@router.get("/flow/live", response_model=FlowInfo)
async def get_live_flow(version: str = Query(default="post", description="优化前pre/优化后post")):
    """获取实盘止损止盈流程, 默认返回优化后"""
    if version == "pre":
        return FlowInfo(**LIVE_FLOW_PRE)
    return FlowInfo(**LIVE_FLOW)


@router.get("/config", response_model=List[ConfigItem])
async def get_stop_loss_config():
    """获取止损止盈配置(优化前后对比)"""
    items = []
    for category in ["stop_loss", "take_profit", "trailing_stop", "gap_stop"]:
        pre = PRE_OPTIMIZATION_CONFIG.get(category, {})
        post = POST_OPTIMIZATION_CONFIG.get(category, {})
        items.append(ConfigItem(
            category=category,
            name=pre.get("name", category),
            pre_optimization=pre,
            post_optimization=post,
        ))
    return items


@router.get("/executions", response_model=List[ExecutionRecord])
async def get_stop_loss_executions(
    trade_date: Optional[int] = Query(default=None, description="交易日, 不传则返回全部"),
    limit: int = Query(default=200, ge=1, le=500),
):
    """获取实盘止损止盈执行记录"""
    try:
        query = {"side": "sell", "status": "filled"}
        if trade_date:
            query["trade_date"] = trade_date

        cursor = mongo_manager.db[COL_ORDERS].find(query).sort("trade_date", -1).limit(limit)
        results = []
        async for doc in cursor:
            reason = doc.get("reason", "") or ""
            results.append(ExecutionRecord(
                ts_code=doc.get("ts_code", ""),
                stock_name=doc.get("stock_name", ""),
                strategy=_strategy_cn_name(doc.get("strategy", "")),
                filled_price=doc.get("filled_price", 0) or 0,
                filled_qty=doc.get("filled_qty", 0) or 0,
                profit_pct=doc.get("profit_pct", 0) or 0,
                profit_amount=doc.get("profit_amount", 0) or 0,
                reason=reason,
                trade_date=int(doc.get("trade_date", 0) or 0),
                fill_time=str(doc.get("fill_time", "") or doc.get("created_at", "")),
                sell_type=_classify_sell_reason(reason),
            ))
        return results
    except Exception as e:
        logger.error(f"获取执行记录失败: {e}")
        return []


@router.get("/stats", response_model=StatsResponse)
async def get_stop_loss_stats(
    trade_date: Optional[int] = Query(default=None, description="交易日, 不传则返回全部"),
):
    """获取止损止盈统计"""
    try:
        query = {"side": "sell", "status": "filled"}
        if trade_date:
            query["trade_date"] = trade_date

        cursor = mongo_manager.db[COL_ORDERS].find(query)
        sells = []
        async for doc in cursor:
            reason = doc.get("reason", "") or ""
            sells.append({
                "profit_amount": doc.get("profit_amount", 0) or 0,
                "profit_pct": doc.get("profit_pct", 0) or 0,
                "sell_type": _classify_sell_reason(reason),
            })

        total = len(sells)
        total_pnl = sum(s["profit_amount"] for s in sells)
        wins = sum(1 for s in sells if s["profit_amount"] > 0)
        win_rate = (wins / total * 100) if total > 0 else 0

        type_map = {}
        for s in sells:
            st = s["sell_type"]
            if st not in type_map:
                type_map[st] = {"sell_type": st, "count": 0, "total_pnl": 0.0, "wins": 0, "avg_pct": 0.0}
            type_map[st]["count"] += 1
            type_map[st]["total_pnl"] += s["profit_amount"]
            if s["profit_amount"] > 0:
                type_map[st]["wins"] += 1
            type_map[st]["avg_pct"] += s["profit_pct"]

        by_type = []
        for st, v in sorted(type_map.items(), key=lambda x: x[1]["count"], reverse=True):
            by_type.append({
                "sell_type": st,
                "count": v["count"],
                "total_pnl": round(v["total_pnl"], 0),
                "win_rate": round(v["wins"] / v["count"] * 100, 1) if v["count"] else 0,
                "avg_pct": round(v["avg_pct"] / v["count"], 1) if v["count"] else 0,
            })

        return StatsResponse(
            total_sells=total,
            total_pnl=round(total_pnl, 0),
            win_rate=round(win_rate, 1),
            by_type=by_type,
        )
    except Exception as e:
        logger.error(f"获取统计数据失败: {e}")
        return StatsResponse()


# ==================== 工具函数 ====================

_STRATEGY_CN_MAP = {
    "halfway_chase": "半路追涨",
    "first_limit_up": "首板打板",
    "limit_up_open": "涨停炸板",
    "dragon_head": "龙头低吸",
    "limit_down_qiao": "跌停翘板",
}

def _strategy_cn_name(name: str) -> str:
    return _STRATEGY_CN_MAP.get(name, name)


def _classify_sell_reason(reason: str) -> str:
    """将卖出reason分类为标准类型"""
    if not reason:
        return "其他"
    if "跳空" in reason:
        return "跳空止损"
    if "追踪" in reason:
        return "追踪止损"
    if "分批" in reason:
        return "分批止盈"
    if "止盈" in reason:
        return "止盈"
    if "冲高" in reason or "利润保护" in reason or "利润锁定" in reason:
        return "冲高回落"
    if "强制" in reason or "空仓" in reason:
        return "强制空仓"
    if "超时" in reason or "强卖" in reason:
        return "超时强卖"
    if "止损" in reason:
        return "固定止损"
    return "其他"
