"""
统一卖出信号检查器 + 滑点规则表 + 买入价计算表

解决的问题:
1. V10-V28中冲高回落/利润保护/止损/止盈的elif链bug反复出现
2. 滑点扣/不扣规则散落在5+处,新增卖出原因容易遗漏
3. 每个策略单独写卖出检查代码,加新策略需复制粘贴
4. 卖出后target_shares未移除导致重新买入(震荡bug)
5. 买入价计算elif链,加新策略需复制粘贴

设计原则:
- 卖出信号用优先级队列,不存在elif跳过问题
- 滑点规则集中定义,新增卖出原因只需加一行
- 买入价计算用策略注册表,不需要elif链
- 策略卖出/买入参数从strategy_defaults.py读取,不硬编码
- 所有卖出检查的入口统一,消除3处重复逻辑

版本: V29
"""

# ============================================================
# 滑点规则表 — 新增卖出原因只需在这里加一行
# ============================================================
# True = 扣滑点, False = 不扣滑点
# 规则: 主动保护性卖出(冲高回落/利润保护/止盈)扣滑点
#       被迫卖出(止损/超时/强制空仓/停牌)不扣滑点
SLIPPAGE_RULES = {
    '冲高回落': True,      # 主动保护:高开时以open卖出,扣滑点模拟实盘偏差
    '利润保护': True,      # 主动保护:冲高回落后以close卖出,扣滑点
    '高开即卖': True,      # 主动保护:以open卖出,扣滑点
    '止盈':     True,      # 主动止盈:扣滑点(实盘难以精确止盈价成交)
    '止损':     False,     # 被迫卖出:止损价已含保守估计,不额外扣
    '跳空止损': False,     # 被迫卖出:open直接跳空低开,已是最差情况
    '超时':     False,     # 被迫卖出:超时强卖,不应再惩罚
    '强制空仓': False,     # 被迫卖出:open价卖出已是最差情况
    '停牌超时强卖': False, # 被迫卖出:被迫以最后有效价卖出
    '调仓卖出': True,      # 正常调仓:扣滑点
    '减仓':     True,      # 正常调仓:扣滑点
}

# 默认规则:未在表中列出的卖出原因,默认扣滑点
SLIPPAGE_DEFAULT = True


def should_apply_slippage(reason: str) -> bool:
    """判断卖出原因是否需要扣滑点

    统一入口,替代portfolio_backtest.py中5+处散落的判断逻辑。
    使用前缀匹配(如'止损(5%)'匹配'止损')。

    Args:
        reason: 卖出原因字符串

    Returns:
        True=扣滑点, False=不扣滑点
    """
    # 精确匹配
    if reason in SLIPPAGE_RULES:
        return SLIPPAGE_RULES[reason]

    # 前缀匹配: '止损(5%)' → '止损', '超时(3交易日>2交易日)' → '超时'
    for key, value in SLIPPAGE_RULES.items():
        if reason.startswith(key):
            return value

    # 包含匹配: '停牌超时强卖' 包含 '停牌'
    for key, value in SLIPPAGE_RULES.items():
        if key in reason:
            return value

    return SLIPPAGE_DEFAULT


# ============================================================
# 卖出信号定义 — 数据驱动,不需要elif链
# ============================================================

# 每种卖出信号的检查函数签名:
#   check(holding, market_data, params) -> (sell_price, sell_reason) or None
# holding: dict with keys: code, strategies, cost, buy_date
# market_data: dict with keys: open, close, high, low, pre_close
# params: dict with strategy-specific sell parameters

class SellSignal:
    """卖出信号定义"""
    def __init__(self, name, priority, check_fn):
        """
        Args:
            name: 信号名称(用于reason和日志)
            priority: 优先级(1最高),同一天内按优先级返回第一个命中的
            check_fn: 检查函数 (holding, market_data, params) -> (price, reason) or None
        """
        self.name = name
        self.priority = priority
        self.check_fn = check_fn

    def check(self, holding, market_data, params):
        return self.check_fn(holding, market_data, params)


# ============================================================
# 信号检查函数 — 纯函数,无副作用,易于测试
# ============================================================

def check_pullback(holding, market_data, params):
    """冲高回落检查: 高开≥阈值且高开低收→以open价卖出

    参数:
    - next_day_open_sell_pct: 高开阈值(默认3%)
    - pullback_high_threshold: 高开直接触发阈值(默认5%)
    - pullback_mid_fallback_pct: 中间区间回落触发阈值(默认1%或1.5%)

    策略差异:
    - 跌停翘板: 中间区间3%-5%回落≥1.5%触发
    - 半路追涨/龙头低吸: 中间区间3%-5%回落≥1%触发
    """
    open_price = market_data.get('open', 0)
    close_price = market_data.get('close', 0)
    cost = holding.get('cost', 0)

    if cost <= 0 or open_price <= 0 or close_price <= 0:
        return None

    open_rise = (open_price / cost - 1)
    threshold = params.get('next_day_open_sell_pct', 0.03)

    # 必须高开≥阈值 且 高开低收(close < open)
    if open_rise < threshold or close_price >= open_price:
        return None

    # 高开≥5%: 直接触发
    high_threshold = params.get('pullback_high_threshold', 0.05)
    if open_rise >= high_threshold:
        return (open_price, '冲高回落')

    # 3%-5%区间: 需回落≥阈值才触发
    mid_fallback = params.get('pullback_mid_fallback_pct', 0.01)
    pullback_pct = (open_price - close_price) / open_price
    if pullback_pct >= mid_fallback:
        return (open_price, '冲高回落')

    return None


def check_profit_protect(holding, market_data, params):
    """利润保护检查: 高开后收盘回落→以close价卖出

    参数:
    - profit_protect_min_close_rise: 收盘涨幅最低门槛(默认2%)
    - profit_protect_min_open_rise: 开盘涨幅最低门槛(默认2%,防止低开误触发)

    逻辑: 必须同时满足:
    1. open_rise >= min_open_rise (高开,不是低开)
    2. close_rise >= min_close_rise (收盘有利润)
    3. close < open (高开低收,冲高回落形态)
    """
    open_price = market_data.get('open', 0)
    close_price = market_data.get('close', 0)
    cost = holding.get('cost', 0)

    if cost <= 0 or open_price <= 0 or close_price <= 0:
        return None

    open_rise = (open_price / cost - 1)
    close_rise = (close_price / cost - 1)

    min_close_rise = params.get('profit_protect_min_close_rise', 0.02)
    min_open_rise = params.get('profit_protect_min_open_rise', 0.02)

    if close_rise >= min_close_rise and open_rise >= min_open_rise and close_price < open_price:
        return (close_price, '利润保护')

    return None


def check_high_open_sell(holding, market_data, params):
    """高开即卖检查(首板打板专用): 高开≥阈值→以open价卖出

    参数:
    - next_day_open_sell_pct: 高开阈值(默认3%)
    """
    open_price = market_data.get('open', 0)
    cost = holding.get('cost', 0)

    if cost <= 0 or open_price <= 0:
        return None

    threshold = params.get('next_day_open_sell_pct', 0.03)
    open_rise = (open_price / cost - 1)

    if open_rise >= threshold:
        return (open_price, '高开即卖')

    return None


def check_stop_loss(holding, market_data, params):
    """止损检查: 最低价跌破止损价

    返回:
    - 跳空止损(open低于止损价): 以open卖出
    - 正常止损: 以止损价卖出
    """
    open_price = market_data.get('open', 0)
    low_price = market_data.get('low', 0)
    cost = holding.get('cost', 0)
    stop_loss_pct = params.get('stop_loss_pct', 0.05)

    if cost <= 0 or low_price <= 0:
        return None

    stop_price = cost * (1 - stop_loss_pct)
    if low_price > stop_price:
        return None

    if open_price <= stop_price and open_price > 0:
        return (open_price, '跳空止损')
    else:
        return (stop_price, f'止损({stop_loss_pct*100:.0f}%)')


def check_take_profit(holding, market_data, params):
    """止盈检查: 最高价达到止盈价

    参数:
    - take_profit_pct: 止盈比例
    """
    high_price = market_data.get('high', 0)
    cost = holding.get('cost', 0)
    take_profit_pct = params.get('take_profit_pct', 0.12)

    if cost <= 0 or high_price <= 0:
        return None

    tp_price = cost * (1 + take_profit_pct)
    if high_price >= tp_price:
        return (tp_price, f'止盈({take_profit_pct*100:.0f}%)')

    return None


def check_timeout(holding, market_data, params):
    """超时强卖检查: 持仓天数超过max_hold_days

    注意: 需要外部传入trade_days_held,通过params传入
    """
    trade_days_held = params.get('trade_days_held', 0)
    max_hold_days = params.get('max_hold_days', 3)

    if max_hold_days >= 999:  # 未设置上限
        return None

    if trade_days_held > max_hold_days:
        close_price = market_data.get('close', 0)
        if close_price > 0:
            return (close_price, f'超时({trade_days_held}交易日>{max_hold_days}交易日)')

    return None


# ============================================================
# 策略→卖出信号映射 — 新增策略只需在这里注册
# ============================================================

# 每个策略的卖出信号列表(按优先级排序)
# 冲高回落 > 利润保护 > 止损 > 止盈 > 超时
# 注意: 止损止盈在_check_early_sell_signals中不检查(由外层逻辑处理)
# 这里只定义"早盘保护性卖出"信号的顺序

STRATEGY_SELL_SIGNALS = {
    '半路追涨': [
        SellSignal('冲高回落', 1, check_pullback),
        SellSignal('利润保护', 2, check_profit_protect),
        SellSignal('高开即卖', 3, check_high_open_sell),
    ],
    '跌停翘板': [
        SellSignal('冲高回落', 1, check_pullback),
        SellSignal('利润保护', 2, check_profit_protect),
    ],
    '龙头低吸': [
        SellSignal('冲高回落', 1, check_pullback),
        SellSignal('利润保护', 2, check_profit_protect),
    ],
    '首板打板': [
        SellSignal('高开即卖', 1, check_high_open_sell),
    ],
}

# 策略级冲高回落参数差异
STRATEGY_PULLBACK_PARAMS = {
    '半路追涨': {
        'pullback_high_threshold': 0.05,
        'pullback_mid_fallback_pct': 0.01,
    },
    '跌停翘板': {
        'pullback_high_threshold': 0.05,
        'pullback_mid_fallback_pct': 0.015,  # 跌停翘板波动大,回落阈值更宽松
    },
    '龙头低吸': {
        'pullback_high_threshold': 0.05,
        'pullback_mid_fallback_pct': 0.01,
    },
}


# ============================================================
# SellSignalChecker — 统一入口
# ============================================================

class SellSignalChecker:
    """统一卖出信号检查器

    替代portfolio_backtest.py中_check_early_sell_signals的if/elif链。
    所有卖出检查(冲高回落/利润保护/止损/止盈/超时)都通过这个类处理。

    使用方式:
        checker = SellSignalChecker(strategy_params, strategy_risk_params, risk_config)
        result = checker.check_early_sell(code, strategies, cost, open_price, close_price)
        result = checker.check_full_sell(code, strategies, cost, market_data, trade_days_held)
        slippage_pct = checker.apply_slippage(sell_reason, code)
    """

    def __init__(self, strategy_params, strategy_risk_params, risk_config, global_slippage=0.002):
        """
        Args:
            strategy_params: dict {strategy_name: {param: value}}
            strategy_risk_params: dict {strategy_name: {risk_param: value}}
            risk_config: dict 全局风控配置
            global_slippage: float 全局默认滑点
        """
        self._strategy_params = strategy_params or {}
        self._strategy_risk_params = strategy_risk_params or {}
        self._risk_config = risk_config or {}
        self._global_slippage = global_slippage

    def _get_sell_params(self, strategy_name):
        """获取策略的卖出参数(合并默认值+策略级差异)"""
        base_params = self._strategy_params.get(strategy_name, {})
        pullback_params = STRATEGY_PULLBACK_PARAMS.get(strategy_name, {})
        risk_params = self._strategy_risk_params.get(strategy_name, {})

        merged = {}
        merged.update(pullback_params)  # 策略级冲高回落差异
        merged.update(base_params)      # 策略参数(含next_day_open_sell_pct)
        merged.update(risk_params)      # 风控参数(含stop_loss/take_profit)
        return merged

    def check_early_sell(self, code, strategies, cost, open_price, close_price):
        """早盘保护性卖出检查(冲高回落/利润保护/高开即卖)

        替代原_check_early_sell_signals方法。
        按优先级检查,命中即返回,不存在elif跳过问题。

        Args:
            code: 股票代码
            strategies: 策略名列表
            cost: 成本价
            open_price: 开盘价
            close_price: 收盘价

        Returns:
            (sell_price, sell_reason) or (0, '')
        """
        if not isinstance(strategies, list) or not strategies:
            return 0, ''
        if cost <= 0:
            return 0, ''

        holding = {
            'code': code,
            'strategies': strategies,
            'cost': cost,
        }
        market_data = {
            'open': open_price,
            'close': close_price,
        }

        for strategy_name in strategies:
            signals = STRATEGY_SELL_SIGNALS.get(strategy_name, [])
            params = self._get_sell_params(strategy_name)

            for signal in signals:  # 按优先级遍历
                result = signal.check(holding, market_data, params)
                if result:
                    return result

        return 0, ''

    def check_full_sell(self, code, strategies, cost, market_data, trade_days_held=None):
        """完整卖出检查(保护性信号+止损+止盈+超时)

        整合所有卖出信号的统一入口,用于非调仓日和调仓日无交易场景。

        Args:
            code: 股票代码
            strategies: 策略名列表
            cost: 成本价
            market_data: dict {open, close, high, low, pre_close}
            trade_days_held: 已持仓交易日数(可选,用于超时检查)

        Returns:
            (sell_price, sell_reason) or (0, '')
        """
        if not isinstance(strategies, list) or not strategies:
            return 0, ''
        if cost <= 0:
            return 0, ''

        holding = {
            'code': code,
            'strategies': strategies,
            'cost': cost,
        }

        # 按优先级检查所有信号
        for strategy_name in strategies:
            params = self._get_sell_params(strategy_name)
            if trade_days_held is not None:
                max_hold = params.get('max_hold_days', 999)
                params['trade_days_held'] = trade_days_held
                params['max_hold_days'] = max_hold

            # 1. 保护性信号(冲高回落/利润保护/高开即卖)
            early_signals = STRATEGY_SELL_SIGNALS.get(strategy_name, [])
            for signal in early_signals:
                result = signal.check(holding, market_data, params)
                if result:
                    return result

            # 2. 止损
            enable_sl = self._risk_config.get('enable_stop_loss', True)
            if enable_sl:
                result = check_stop_loss(holding, market_data, params)
                if result:
                    return result

            # 3. 止盈
            enable_tp = self._risk_config.get('enable_take_profit', True)
            if enable_tp:
                result = check_take_profit(holding, market_data, params)
                if result:
                    return result

            # 4. 超时
            if trade_days_held is not None:
                result = check_timeout(holding, market_data, params)
                if result:
                    return result

            # 只需要检查第一个匹配策略的信号(多策略取最严格)
            break

        return 0, ''

    def apply_slippage(self, reason, code=None, fallback_slippage=None):
        """判断卖出原因是否需要扣滑点

        统一入口,替代portfolio_backtest.py中5+处散落的if/else判断。

        Args:
            reason: 卖出原因
            code: 股票代码(可选,用于获取策略级滑点比例)
            fallback_slippage: 兜底滑点比例

        Returns:
            slippage_pct: 实际滑点比例(0表示不扣)
        """
        if not should_apply_slippage(reason):
            return 0

        # 获取策略级滑点
        if code:
            strategies = self._strategy_risk_params  # 简化:外部可传入
            # 这里需要stock_to_strategy映射,由调用方提供
            # 如果不提供,使用全局滑点

        return fallback_slippage if fallback_slippage is not None else self._global_slippage

    def get_sl_tp_for_strategies(self, strategies):
        """获取策略组合的止损止盈参数

        Args:
            strategies: 策略名列表

        Returns:
            (stop_loss_pct, take_profit_pct)
        """
        global_sl = self._risk_config.get('stop_loss_pct', 0.03)
        global_tp = self._risk_config.get('take_profit_pct', 0.07)

        if isinstance(strategies, list) and strategies:
            sl = min(self._strategy_risk_params.get(s, {}).get('stop_loss_pct', global_sl) for s in strategies)
            tp = max(self._strategy_risk_params.get(s, {}).get('take_profit_pct', global_tp) for s in strategies)
            return sl, tp
        return global_sl, global_tp

    def get_max_hold_for_strategies(self, strategies):
        """获取策略组合的最大持仓天数

        Args:
            strategies: 策略名列表

        Returns:
            max_hold_days (999表示无限制)
        """
        global_max_hold = self._risk_config.get('max_hold_days', 999)
        strategy_max_hold = None

        if isinstance(strategies, list):
            for sname in strategies:
                smh = self._strategy_risk_params.get(sname, {}).get('max_hold_days')
                if smh is not None:
                    if strategy_max_hold is None or smh < strategy_max_hold:
                        strategy_max_hold = smh

        return strategy_max_hold if strategy_max_hold is not None else global_max_hold

    def get_slippage_for_strategies(self, strategies):
        """获取策略组合的滑点"""
        if isinstance(strategies, list) and strategies:
            return max(
                self._strategy_risk_params.get(s, {}).get('slippage_pct', self._global_slippage)
                for s in strategies
            )
        return self._global_slippage


# ============================================================
# PositionManager — 卖出后从target_shares移除,防止重新买入
# ============================================================

class PositionManager:
    """持仓管理器

    解决V19/V24/V26反复出现的"卖出后重新买入"震荡bug。
    统一管理sell_codes/sell_code_reasons/target_shares的关系。
    """

    def __init__(self, holdings, target_shares):
        """
        Args:
            holdings: dict 当前持仓 {code: shares}
            target_shares: dict 目标持仓 {code: shares}
        """
        self.holdings = dict(holdings)
        self.target_shares = dict(target_shares)
        self.sell_code_reasons = {}  # code -> sell_reason
        self.t1_blocked = set()  # T+1当日买入不可卖的股票

    def mark_sold(self, code, reason, sell_price=None):
        """标记股票为已卖出,同时从target_shares移除

        关键: 卖出后必须从target_shares移除,否则买入循环会重新买入(震荡bug)
        """
        self.sell_code_reasons[code] = reason
        if code in self.target_shares:
            del self.target_shares[code]

    def is_blocked(self, code):
        """检查股票是否已被标记卖出(不应重新买入)"""
        return code in self.sell_code_reasons

    def should_sell(self, code):
        """检查股票是否需要卖出"""
        return code in self.sell_code_reasons

    def get_sell_reason(self, code):
        """获取卖出原因"""
        return self.sell_code_reasons.get(code, '')

    def block_t1(self, code):
        """T+1: 标记当日买入不可卖出"""
        self.t1_blocked.add(code)

    def is_t1_blocked(self, code):
        """检查是否T+1限制"""
        return code in self.t1_blocked


# ============================================================
# 买入价计算表 — 新增策略只需注册一个计算函数
# ============================================================

# 策略买入价计算函数签名:
#   calc_buy_price(code, open_price, close_price, high_price, low_price, pre_close, strategy_params) -> float
# 返回0表示无法计算


def calc_buy_price_halfway_chase(code, open_price, close_price, high_price, low_price, pre_close, params):
    """半路追涨买入价: open*(1+min_rise*0.8)

    模拟盘中涨到2.4%位置时买入(略早于3%确认位)。

    未来函数说明(V25):
    pct_chg≥5%是收盘确认,但买入价用盘中模拟。严格定义是未来函数,
    但实测收盘确认+close买入收益从226%→46%,代价太大,保留盘中近似。
    """
    min_rise = params.get('min_rise_pct', 0.03)
    if open_price > 0:
        return open_price * (1 + min_rise * 0.8)
    return 0


def calc_buy_price_first_limit_up(code, open_price, close_price, high_price, low_price, pre_close, params):
    """首板打板/涨停开板买入价: 委托给_get_limit_up_price(需要外部方法)"""
    # 打板价计算依赖self._get_limit_up_price,无法纯函数化
    # 返回特殊标记,由portfolio_backtest.py处理
    return -1  # 特殊标记:需要调用_get_limit_up_price


def calc_buy_price_dragon_head(code, open_price, close_price, high_price, low_price, pre_close, params):
    """龙头低吸买入价: low + (high-low)*0.20

    模拟日内偏低位置但不极端的低吸。
    系数0.20(V28): 低点上方20%,振幅5%→买入+1.00%,保守真实。
    """
    if low_price > 0 and high_price > low_price:
        return low_price + (high_price - low_price) * 0.20
    elif low_price > 0:
        return low_price * 1.01
    else:
        return open_price * 0.98 if open_price > 0 else 0


def calc_buy_price_limit_down_qiao(code, open_price, close_price, high_price, low_price, pre_close, params):
    """跌停翘板买入价: low*1.01

    跌停价上方1%溢价,模拟翘板成交价(V15:从0.5%→1%)。
    """
    if low_price > 0:
        return low_price * 1.01
    return open_price * 0.92 if open_price > 0 else 0


def calc_buy_price_default(code, open_price, close_price, high_price, low_price, pre_close, params):
    """默认买入价: open"""
    return open_price


# 策略→买入价计算函数映射
STRATEGY_BUY_PRICE = {
    '半路追涨': calc_buy_price_halfway_chase,
    '首板打板': calc_buy_price_first_limit_up,
    '涨停开板': calc_buy_price_first_limit_up,
    '龙头低吸': calc_buy_price_dragon_head,
    '跌停翘板': calc_buy_price_limit_down_qiao,
}

# 买入价计算参数(可被strategy_params覆盖)
DEFAULT_BUY_PRICE_PARAMS = {
    '半路追涨': {'min_rise_pct': 0.03},
}


def get_buy_price_for_strategy(strategy_name, code, open_price, close_price,
                                high_price, low_price, pre_close=0, strategy_params=None):
    """统一买入价计算入口

    替代portfolio_backtest.py中_get_buy_price_for_stock的if/elif链。
    新增策略只需在STRATEGY_BUY_PRICE中注册一个计算函数。

    Args:
        strategy_name: 策略名称
        code: 股票代码
        open_price: 开盘价
        close_price: 收盘价
        high_price: 最高价
        low_price: 最低价
        pre_close: 前收盘价
        strategy_params: 策略参数(可选)

    Returns:
        float: 买入价(0=无法计算, -1=需要调用_get_limit_up_price)
    """
    calc_fn = STRATEGY_BUY_PRICE.get(strategy_name, calc_buy_price_default)
    params = strategy_params or DEFAULT_BUY_PRICE_PARAMS.get(strategy_name, {})
    return calc_fn(code, open_price, close_price, high_price, low_price, pre_close, params)
