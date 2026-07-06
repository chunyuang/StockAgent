"""板块涨跌停阈值统一工具

所有涨跌停判断必须通过此模块, 确保全局一致性。
2026-07-06: 主板ST涨跌幅由5%调整为10%(与普通股一致)。
"""


def get_limit_threshold(ts_code: str) -> float:
    """返回涨跌停阈值百分比(正数)

    主板: 10% | 创业板/科创板: 20% | 北交所: 30%

    >>> get_limit_threshold('600036.SH')
    9.5
    >>> get_limit_threshold('300001.SZ')
    19.5
    >>> get_limit_threshold('688001.SH')
    19.5
    >>> get_limit_threshold('832000.BJ')
    29.5
    """
    code = ts_code or ""
    prefix = code.split(".")[0][:3] if "." in code else code[:3]
    suffix = code.split(".")[1] if "." in code else ""

    if prefix.startswith(('688', '30')):
        return 19.5  # 创业板/科创板: 20%
    if suffix == 'BJ':
        return 29.5  # 北交所: 30%
    return 9.5  # 主板: 10%


def is_limit_up(ts_code: str, pct_chg: float) -> bool:
    """是否涨停(按板块阈值)"""
    return pct_chg >= get_limit_threshold(ts_code)


def is_limit_down(ts_code: str, pct_chg: float) -> bool:
    """是否跌停(按板块阈值)"""
    return pct_chg <= -get_limit_threshold(ts_code)


def count_limits(stock_data: dict) -> tuple:
    """统计涨跌停数量

    Args:
        stock_data: {ts_code: {pct_chg: float, ...}, ...}

    Returns: (limit_up_count, limit_down_count)
    """
    lu, ld = 0, 0
    for code, data in stock_data.items():
        if not isinstance(data, dict):
            continue
        pct = data.get("pct_chg", data.get("auction_pct", 0))
        if not isinstance(pct, (int, float)):
            continue
        if is_limit_up(code, pct):
            lu += 1
        elif is_limit_down(code, pct):
            ld += 1
    return lu, ld
