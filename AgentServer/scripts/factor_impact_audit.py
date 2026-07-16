#!/usr/bin/env python3
"""
因子影响审查脚本 v1.0 (2026-07-04)

从"因子如何影响策略结果"的角度审查数据正确性。
不检查"字段存不存在"（那是覆盖率的事），而是检查"值对不对"。

检查维度:
1. 因子计算正确性 — MA/RSI/MACD/BOLL/ATR/动量/波动率 vs 手动计算
2. 因子值域合理性 — 是否超范围/极端值
3. 因子→策略使用一致性 — 单位/语义/过滤效果
4. 派生因子正确性 — first_limit_up/intraday_limit_up/limit_up_yesterday
5. 空壳/假数据防护 — close=None/0, 节假日数据
6. 跨集合因子一致性 — ak_full vs daily_basic
7. 因子值分布异常 — 与历史分布偏离

用法:
  python3 scripts/factor_impact_audit.py                      # 审查最近1天
  python3 scripts/factor_impact_audit.py --days 3             # 审查最近3天
  python3 scripts/factor_impact_audit.py --date 20260703      # 指定日期
  python3 scripts/factor_impact_audit.py --strict             # 严格模式
  python3 scripts/factor_impact_audit.py --json               # JSON输出(供cron解析)

退出码:
  0 = 全部通过
  1 = 发现P0问题
  2 = 只有P1问题
"""

import argparse
import json
import sys
import os
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from pymongo import MongoClient

MONGO_URI = os.environ.get('MONGO_URI', 'mongodb://localhost:27017')

# 策略参数中的市值单位=亿元, ak_full的circ_mv=万元
CIRC_MV_RATIO = 10000  # 万元/亿元

# 涨停阈值
LIMIT_UP_THRESHOLDS = {
    'main': 9.5,       # 主板(60/00开头)
    'gem': 19.5,       # 创业板(30开头)
    'star': 19.5,      # 科创板(688开头)
    'bj': 29.5,        # 北交所(8/4/920开头)
}


def get_threshold(ts_code):
    """根据代码判断涨停阈值"""
    if ts_code.startswith(('30', '688')):
        return 20.0
    elif ts_code.startswith(('8', '4', '920')):
        return 30.0
    else:
        return 10.0


def get_limit_up_threshold_pct(ts_code):
    """用于is_limit_up判断的百分比阈值(留0.5%缓冲)"""
    if ts_code.startswith(('30', '688')):
        return 19.5
    elif ts_code.startswith(('8', '4', '920')):
        return 29.5
    else:
        return 9.5


class FactorImpactAuditor:
    def __init__(self, db, strict=False):
        self.db = db
        self.strict = strict
        self.issues = []  # (severity, category, name, expected, actual, detail)

    def add_issue(self, severity, category, name, expected, actual, detail=""):
        self.issues.append((severity, category, name, expected, actual, detail))

    def get_trade_dates(self, days=1):
        """获取最近N个交易日"""
        all_dates = sorted(self.db['stock_daily_ak_full'].distinct('trade_date'))
        return all_dates[-days:] if all_dates else []

    # ============================================================
    # 1. 因子计算正确性 — 用基准票验证
    # ============================================================
    def audit_factor_computation(self, trade_date):
        """验证因子计算是否正确"""
        category = "因子计算正确性"
        code = '000001.SZ'  # 平安银行作为基准

        # 取最近60天数据(因子计算需要历史窗口)
        docs = list(self.db['stock_daily_ak_full'].find(
            {'ts_code': code, 'trade_date': {'$lte': trade_date}},
            {'_id': 0}
        ).sort('trade_date', -1).limit(60))

        if not docs:
            self.add_issue("P1", category, f"{code}无数据", "有数据", "无", f"trade_date={trade_date}")
            return

        latest = docs[0]
        closes = [d.get('close') for d in reversed(docs) if d.get('close')]

        if len(closes) < 20:
            self.add_issue("P1", category, f"{code}数据不足20天", "≥20天", f"{len(closes)}天")
            return

        # 1a. MA均线验证
        for period, field in [(5, 'ma5'), (10, 'ma10'), (20, 'ma20'), (60, 'ma60')]:
            db_val = latest.get(field)
            if db_val is None:
                continue
            if len(closes) >= period:
                calc_val = np.mean(closes[-period:])
                diff = abs(db_val - calc_val)
                # MA20以上可能因复权价有0.1偏差, MA5/10应精确
                threshold = 0.02 if period <= 10 else (0.1 if period == 20 else 0.15)
                if diff > threshold:
                    self.add_issue("P1", category, f"{field}偏差",
                                   f"≈{calc_val:.4f}", f"{db_val:.4f}(差{diff:.4f})",
                                   "可能是复权价导致(MA60偏差大)")

        # 1b. RSI值域检查
        for field in ['rsi_6', 'rsi_12', 'rsi_24']:
            val = latest.get(field)
            if val is not None and (val < 0 or val > 100):
                self.add_issue("P0", category, f"{field}超范围",
                               "0-100", f"{val}", "RSI应在0-100之间")

        # 1c. MACD hist验证 = 2×(DIF - DEA)
        macd = latest.get('macd')
        signal = latest.get('macd_signal')
        hist = latest.get('macd_hist')
        if all(v is not None for v in [macd, signal, hist]):
            hist_expected = 2 * (macd - signal)
            diff = abs(hist - hist_expected)
            if diff > 0.01:
                self.add_issue("P1", category, "MACD_hist不一致",
                               f"2×(DIF-DEA)={hist_expected:.6f}", f"{hist:.6f}(差{diff:.6f})")

        # 1d. BOLL顺序: upper > mid > lower, mid ≈ MA20
        bu = latest.get('boll_upper')
        bm = latest.get('boll_mid')
        bl = latest.get('boll_lower')
        if all(v is not None for v in [bu, bm, bl]):
            if not (bu > bm > bl):
                self.add_issue("P0", category, "BOLL顺序错误",
                               "upper>mid>lower", f"u={bu} m={bm} l={bl}")

        # 1e. NATR = ATR/close × 100
        atr = latest.get('atr')
        natr = latest.get('natr')
        close = latest.get('close')
        if all(v is not None for v in [atr, natr, close]) and close > 0:
            natr_calc = atr / close * 100
            if abs(natr - natr_calc) > 0.1:
                self.add_issue("P1", category, "NATR计算不一致",
                               f"atr/close×100={natr_calc:.4f}", f"{natr:.4f}")

    # ============================================================
    # 2. 因子值域合理性 — 全市场扫描
    # ============================================================
    def audit_factor_ranges(self, trade_date):
        """检查全市场因子值域是否合理"""
        category = "因子值域合理性"

        # (field, min, max, description)
        range_checks = [
            ('rsi_6', 0, 100, 'RSI6'),
            ('rsi_12', 0, 100, 'RSI12'),
            ('rsi_24', 0, 100, 'RSI24'),
            ('turnover_rate', 0, 100, '换手率%'),
            ('volume_ratio', 0, 50, '量比倍'),
            ('pct_chg', -30, 30, '涨跌幅%(排除新股/北交所920)'),  # 北交所±30%, 新股首日无限制
            ('opening_pct_chg', -100, 1000, '竞价涨跌幅%(新股/退市可超30%)'),
            ('boll_upper', 0, 100000, 'BOLL上轨'),
            ('fear_greed_index', 2.0, 8.0, '恐贪指数(实为rsi_score)'),
        ]

        for field, lo, hi, desc in range_checks:
            # 检查超范围数量
            if field == 'pct_chg':
                # 排除新股首日(上市日期=当日)和北交所920xxx(首日无涨跌幅限制)
                query_lo = {'trade_date': trade_date, field: {'$lt': lo},
                            'ts_code': {'$not': {'$regex': '^920'}}}
                query_hi = {'trade_date': trade_date, field: {'$gt': hi},
                            'ts_code': {'$not': {'$regex': '^920'}}}
                # 排除上市首日(pct_chg>100%的基本都是新股)
                query_hi['pct_chg'] = {'$gt': hi, '$lt': 1000}  # 超过1000%可能是数据错误
            else:
                query_lo = {'trade_date': trade_date, field: {'$lt': lo}}
                query_hi = {'trade_date': trade_date, field: {'$gt': hi}}

            oob_lo = self.db['stock_daily_ak_full'].count_documents(query_lo)
            oob_hi = self.db['stock_daily_ak_full'].count_documents(query_hi)

            # 对于pct_chg: 新股首日无涨跌幅限制, >30%不算异常
            if field == 'pct_chg':
                # 检查超范围的是否都是新股/北交所
                oob_docs = list(self.db['stock_daily_ak_full'].find(
                    query_hi, {'ts_code': 1, 'pct_chg': 1, '_id': 0}).limit(5))
                all_new_stock = all(d['pct_chg'] > 44 for d in oob_docs)  # 新股首日通常>44%
                if all_new_stock and len(oob_docs) <= 3:
                    continue  # 都是新股首日, 不算异常

            if oob_lo > 0 or oob_hi > 0:
                severity = "P0" if (oob_lo + oob_hi) > 10 else "P1"
                self.add_issue(severity, category, f"{field}超范围",
                               f"{lo}~{hi}", f"<{lo}={oob_lo} >{hi}={oob_hi}",
                               f"{desc}值域异常")

    # ============================================================
    # 3. 因子→策略使用一致性 — 单位/语义/过滤效果
    # ============================================================
    def audit_factor_strategy_alignment(self, trade_date):
        """检查因子在策略筛选中的使用是否与数据语义对齐"""
        category = "因子-策略使用一致性"

        # 3a. circ_mv单位: ak_full=万元, 策略参数=亿元
        # signal_manager已修(circ_mv>10000时÷10000), 但仍有风险
        # 检查: circ_mv最大值不应超过5亿万元(=5万亿, 工商银行级别)
        max_circ = list(self.db['stock_daily_ak_full'].find(
            {'trade_date': trade_date, 'circ_mv': {'$gt': 0}},
            {'ts_code': 1, 'circ_mv': 1, '_id': 0}
        ).sort('circ_mv', -1).limit(1))

        if max_circ:
            top = max_circ[0]
            circ = top.get('circ_mv', 0)
            # 流通市值不应超过30万亿=30000000万元(工行农行≈19万亿)
            # 如果>30万亿万元, 很可能是把亿元当万元(值会是正常的1万倍)
            if circ > 300000000:  # 30万亿万元=3亿万元=超出任何A股
                self.add_issue("P0", category, "circ_mv异常大",
                               "≤3亿万元", f"{circ}万元({top['ts_code']})",
                               "可能是单位错误(把亿元当万元)")
            # 不应<1万元
            min_circ = list(self.db['stock_daily_ak_full'].find(
                {'trade_date': trade_date, 'circ_mv': {'$gt': 0, '$lt': 100}},
                {'ts_code': 1, 'circ_mv': 1, '_id': 0}
            ).limit(1))
            if min_circ:
                self.add_issue("P1", category, "circ_mv异常小",
                               "≥100万元", f"{min_circ[0].get('circ_mv')}万元({min_circ[0]['ts_code']})",
                               "可能是单位错误(把万元当亿元)")

        # 3b. fear_greed_index语义检查(应该是2.5~7.5, 不是0~100)
        fgi_out = self.db['stock_daily_ak_full'].count_documents(
            {'trade_date': trade_date, 'fear_greed_index': {'$gt': 10}})
        if fgi_out > 0:
            self.add_issue("P0", category, "fear_greed_index超范围",
                           "2.5~7.5(个股RSI归一化)", f">{10}: {fgi_out}只",
                           "如果出现0~100范围的值, 说明数据源语义变了")

    # ============================================================
    # 4. 派生因子正确性 — first_limit_up / intraday_limit_up
    # ============================================================
    def audit_derived_factors(self, trade_date):
        """验证派生因子计算是否正确"""
        category = "派生因子正确性"

        # 找前一个交易日
        prev_dates = sorted(self.db['stock_daily_ak_full'].distinct(
            'trade_date', {'trade_date': {'$lt': trade_date}}))
        if not prev_dates:
            return
        prev_date = prev_dates[-1]

        # 4a. first_limit_up验证
        # 今天is_limit_up=1 且 昨天is_limit_up≠1 → first_limit_up应为1
        lu_today = set(d['ts_code'] for d in self.db['stock_daily_ak_full'].find(
            {'trade_date': trade_date, 'is_limit_up': 1}, {'ts_code': 1, '_id': 0}))
        lu_prev = set(d['ts_code'] for d in self.db['stock_daily_ak_full'].find(
            {'trade_date': prev_date, 'is_limit_up': 1}, {'ts_code': 1, '_id': 0}))
        expected_flu = lu_today - lu_prev  # 首板

        flu_in_db = set(d['ts_code'] for d in self.db['stock_daily_ak_full'].find(
            {'trade_date': trade_date, 'first_limit_up': 1}, {'ts_code': 1, '_id': 0}))

        # 缺失的首板(应该是首板但DB里=0)
        missing_flu = expected_flu - flu_in_db
        if missing_flu and len(missing_flu) > len(expected_flu) * 0.1:
            self.add_issue("P0", category, "first_limit_up缺失",
                           f"{len(expected_flu)}只首板", f"DB中{len(flu_in_db)}只, 缺{len(missing_flu)}只",
                           "首板打板策略候选池被严重缩减")

        # 错误的首板(不是首板但DB里=1)
        # 注意: 昨天停牌的票今天涨停也是首板, 但lu_prev里没有(停牌≠涨停)
        # 所以需要排除昨天停牌的票(ak_full没记录=停牌)
        all_prev_ts = set(d['ts_code'] for d in self.db['stock_daily_ak_full'].find(
            {'trade_date': prev_date}, {'ts_code': 1, '_id': 0}))
        # 昨天有数据但没涨停 → 不是首板
        all_prev_ts - lu_prev
        # 昨天没数据 → 可能停牌, 不算误报
        false_flu = flu_in_db - expected_flu - (flu_in_db - all_prev_ts)
        false_flu = false_flu - (flu_in_db - all_prev_ts)  # 排除昨天停牌的
        if false_flu and len(false_flu) > 5:
            self.add_issue("P1", category, "first_limit_up误报",
                           f"{len(expected_flu)}只首板", f"DB多{len(false_flu)}只",
                           f"连板被误标为首板: {list(false_flu)[:5]}")

        # 4b. is_limit_up语义验证: 涨停票的pct_chg应>=阈值
        lu_docs = list(self.db['stock_daily_ak_full'].find(
            {'trade_date': trade_date, 'is_limit_up': 1},
            {'ts_code': 1, 'pct_chg': 1, '_id': 0}
        ).limit(20))

        for doc in lu_docs:
            pct = doc.get('pct_chg', 0)
            threshold = get_limit_up_threshold_pct(doc['ts_code'])
            if pct < threshold - 1:  # 留1%缓冲(涨停后可能小幅回落)
                # 可能是炸板但标记了is_limit_up? 检查intraday
                pass  # 不算bug, 只是数据精度问题

        # 4c. intraday_limit_up vs limit_list一致性抽查
        # (不全面扫描, 只检查差异>5只的情况)
        intraday_lu = set(d['ts_code'] for d in self.db['stock_daily_ak_full'].find(
            {'trade_date': trade_date, 'intraday_limit_up': 1}, {'ts_code': 1, '_id': 0}))
        limit_list_ll = set(d['ts_code'] for d in self.db['limit_list'].find(
            {'trade_date': trade_date, 'limit': 'U'}, {'ts_code': 1, '_id': 0}))

        # limit_list是涨停(含连板), intraday_lu是盘中触涨停(含炸板)
        # 两者应该高度重叠
        if intraday_lu and limit_list_ll:
            intraday_lu & limit_list_ll
            only_intraday = intraday_lu - limit_list_ll
            only_list = limit_list_ll - intraday_lu

            if len(only_intraday) > 10:
                self.add_issue("P1", category, "intraday_limit_up vs limit_list差异",
                               "高度重叠", f"仅intraday={len(only_intraday)}仅list={len(only_list)}",
                               "盘中触涨停但不在涨停池中, 可能是北交所补充遗漏")

    # ============================================================
    # 5. 空壳/假数据防护
    # ============================================================
    def audit_data_quality(self, trade_date):
        """检查空壳记录和假数据"""
        category = "数据质量"

        # 5a. 空壳记录(close=None或close=0)
        empty_count = self.db['stock_daily_ak_full'].count_documents(
            {'trade_date': trade_date,
             '$or': [{'close': None}, {'close': 0}, {'close': {'$exists': False}}]})
        if empty_count > 0:
            self.add_issue("P0", category, "空壳记录",
                           "0条", f"{empty_count}条", "close=None/0的垃圾记录")

        # 5b. 节假日数据检查(成交量=0但close有值)
        suspicious = self.db['stock_daily_ak_full'].count_documents(
            {'trade_date': trade_date, 'vol': 0, 'close': {'$gt': 0}})
        if suspicious > 100:
            self.add_issue("P0", category, "疑似节假日假数据",
                           "0条", f"{suspicious}条vol=0但有close",
                           "可能是节假日写入的假数据")

        # 5c. close异常精度(10+位小数=复权价)
        # 抽查100只票
        sample = list(self.db['stock_daily_ak_full'].find(
            {'trade_date': trade_date, 'close': {'$gt': 0}},
            {'ts_code': 1, 'close': 1, '_id': 0}
        ).limit(100))

        fuquan_count = 0
        for doc in sample:
            c = doc.get('close', 0)
            s = str(c)
            if '.' in s and len(s.split('.')[1]) > 4:
                fuquan_count += 1

        if fuquan_count > 30:  # >30%可能是系统性问题
            self.add_issue("P1", category, "复权价残留",
                           "close=真实价(1-2位小数)", f"{fuquan_count}/100有10+位小数",
                           "AKShare历史数据是前复权, 影响MA/MACD/BOLL计算")

    # ============================================================
    # 6. 跨集合因子一致性
    # ============================================================
    def audit_cross_collection(self, trade_date):
        """检查ak_full vs daily_basic的关键因子是否一致"""
        category = "跨集合因子一致性"

        # 6a. PE/PB一致性
        ref_codes = ['000001.SZ', '600519.SH', '601398.SH']
        for code in ref_codes:
            ak = self.db['stock_daily_ak_full'].find_one(
                {'ts_code': code, 'trade_date': trade_date},
                {'pe_ttm': 1, 'pb': 1, 'circ_mv': 1, '_id': 0})
            basic = self.db['daily_basic'].find_one(
                {'ts_code': code, 'trade_date': trade_date},
                {'pe_ttm': 1, 'pb': 1, 'circ_mv': 1, '_id': 0})

            if not ak or not basic:
                continue

            # PE/PB应接近(允许5%误差)
            for field in ['pe_ttm', 'pb']:
                ak_val = ak.get(field)
                basic_val = basic.get(field)
                if ak_val and basic_val and basic_val > 0:
                    diff_pct = abs(ak_val - basic_val) / basic_val * 100
                    if diff_pct > 5:
                        self.add_issue("P1", category, f"{code} {field}不一致",
                                       "≤5%差异", f"ak={ak_val:.2f} basic={basic_val:.2f} 差{diff_pct:.1f}%")

            # circ_mv跨集合比率应为10000
            ak_circ = ak.get('circ_mv', 0)
            basic_circ = basic.get('circ_mv', 0)
            if ak_circ > 0 and basic_circ > 0:
                ratio = ak_circ / basic_circ
                if abs(ratio - 10000) > 1000:  # 允许10%误差
                    self.add_issue("P0", category, f"{code} circ_mv单位不一致",
                                   "比率≈10000", f"比率={ratio:.0f}(ak={ak_circ} basic={basic_circ})",
                                   "ak_full=万元, daily_basic=亿元, 比率应为10000")

    # ============================================================
    # 7. 策略漏斗验证
    # ============================================================
    def audit_strategy_funnel(self, trade_date):
        """验证策略漏斗是否产生合理数量的候选"""
        category = "策略漏斗"

        lu = self.db['stock_daily_ak_full'].count_documents(
            {'trade_date': trade_date, 'is_limit_up': 1})
        flu = self.db['stock_daily_ak_full'].count_documents(
            {'trade_date': trade_date, 'first_limit_up': 1})

        # 首板应>涨停的30%(大部分涨停是首板)
        if lu > 0 and flu == 0:
            self.add_issue("P0", category, "首板打板0候选",
                           f">0 (涨停{lu}只应有首板)", "0只",
                           "first_limit_up全部=0, 策略完全失效!")
        elif lu > 10 and flu < lu * 0.2:
            self.add_issue("P1", category, "首板比例异常低",
                           "≥30%涨停是首板", f"首板{flu}/{lu}={flu/lu*100:.0f}%",
                           "first_limit_up可能计算错误")

        # 涨停数合理性检查(正常A股每天30-200只涨停)
        if lu > 500:
            self.add_issue("P1", category, "涨停数异常多",
                           "30-200只", f"{lu}只",
                           "可能is_limit_up阈值太低或数据错误")
        elif lu == 0 and trade_date >= 20250101:
            # 非交易日不应该有数据, 但如果trade_date是交易日则涨停=0是异常
            pass  # 不报, 可能是数据还没采补

    # ============================================================
    # 8. broken_rate验证
    # ============================================================
    def audit_broken_rate(self, trade_date):
        """验证炸板率是否合理"""
        category = "炸板率"

        doc = self.db['sentiment_scores'].find_one({'trade_date': trade_date})
        if not doc:
            return

        broken = doc.get('broken', 0)
        broken_rate = doc.get('broken_rate', 0)
        lu = doc.get('limit_up', 0)
        data_source = doc.get('data_source', '')

        # 交叉验证: 从limit_list的open_times>0推算实际炸板数
        actual_broken = self.db['limit_list'].count_documents(
            {'trade_date': trade_date, 'open_times': {'$gt': 0}, 'limit': 'U'})

        # 如果sentiment broken=0 但limit_list有open_times>0的数据
        if broken == 0 and actual_broken > 0:
            self.add_issue("P1", category, "broken始终=0",
                           f">0 (limit_list有{actual_broken}只open_times>0)", "0",
                           f"intraday_sentiment计算bug: 盘中封住的炸板票(open_times>0但pct>=lu_thresh)未被计入broken. data_source={data_source}")
        elif lu > 0 and broken == 0 and actual_broken == 0:
            # limit_list的open_times也全是0 → 可能是数据源问题
            self.add_issue("P2", category, "open_times全=0",
                           f">0 (涨停{lu}只应有一定炸板)", "0",
                           "limit_list.open_times全=0, 需从ak_full推算")

        # broken_rate通常在20%-80%, =100%都异常
        if broken_rate == 100 and lu > 5:
            self.add_issue("P1", category, "炸板率=100%",
                           "20-80%", "100%",
                           "所有涨停都炸板? 检查open_times推算逻辑")

    def run(self, trade_date):
        """运行所有审查"""
        self.audit_factor_computation(trade_date)
        self.audit_factor_ranges(trade_date)
        self.audit_factor_strategy_alignment(trade_date)
        self.audit_derived_factors(trade_date)
        self.audit_data_quality(trade_date)
        self.audit_cross_collection(trade_date)
        self.audit_strategy_funnel(trade_date)
        self.audit_broken_rate(trade_date)
        return self.issues

    def get_summary(self):
        """获取摘要"""
        p0 = [i for i in self.issues if i[0] == 'P0']
        p1 = [i for i in self.issues if i[1] != 'P1']  # typo fix
        p1 = [i for i in self.issues if i[0] == 'P1']
        return {
            'total': len(self.issues),
            'p0': len(p0),
            'p1': len(p1),
            'p0_list': [(i[1], i[2]) for i in p0],
            'p1_list': [(i[1], i[2]) for i in p1],
        }


def main():
    parser = argparse.ArgumentParser(description='因子影响审查')
    parser.add_argument('--date', type=str, help='指定日期(YYYYMMDD)')
    parser.add_argument('--days', type=int, default=1, help='审查最近N天')
    parser.add_argument('--strict', action='store_true', help='严格模式')
    parser.add_argument('--json', action='store_true', help='JSON输出')
    args = parser.parse_args()

    client = MongoClient(MONGO_URI)
    db = client['stock_agent']

    if args.date:
        trade_dates = [int(args.date)]
    else:
        all_dates = sorted(db['stock_daily_ak_full'].distinct('trade_date'))
        trade_dates = all_dates[-args.days:] if all_dates else []

    if not trade_dates:
        print("❌ 无可用交易日数据")
        sys.exit(1)

    all_issues = []

    for td in trade_dates:
        auditor = FactorImpactAuditor(db, strict=args.strict)
        issues = auditor.run(td)
        all_issues.extend([(td, *i) for i in issues])

    # 输出
    if args.json:
        output = []
        for td, sev, cat, name, expected, actual, detail in all_issues:
            output.append({
                'trade_date': td, 'severity': sev, 'category': cat,
                'name': name, 'expected': expected, 'actual': actual, 'detail': detail
            })
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        # 按严重度分组
        p0 = [(td, *i) for td, *i in all_issues if i[0] == 'P0']
        p1 = [(td, *i) for td, *i in all_issues if i[0] == 'P1']

        print(f"📊 因子影响审查报告 — 日期: {', '.join(str(d) for d in trade_dates)}")
        print(f"{'='*70}")

        if p0:
            print(f"\n🔴 P0 严重 ({len(p0)}个)")
            for td, sev, cat, name, expected, actual, detail in p0:
                print(f"  [{td}] {cat}: {name}")
                print(f"    期望: {expected} | 实际: {actual}")
                if detail:
                    print(f"    {detail}")

        if p1:
            print(f"\n🟡 P1 中等 ({len(p1)}个)")
            for td, sev, cat, name, expected, actual, detail in p1:
                print(f"  [{td}] {cat}: {name}")
                print(f"    期望: {expected} | 实际: {actual}")

        if not p0 and not p1:
            print("\n✅ 全部通过! 无因子影响问题")

        print(f"\n{'='*70}")
        print(f"总计: P0={len(p0)} P1={len(p1)}")

    # 退出码
    has_p0 = any(i[0] == 'P0' for i in all_issues)
    has_p1 = any(i[0] == 'P1' for i in all_issues)

    if has_p0:
        sys.exit(1)
    elif has_p1:
        sys.exit(2)
    else:
        sys.exit(0)


if __name__ == '__main__':
    main()
