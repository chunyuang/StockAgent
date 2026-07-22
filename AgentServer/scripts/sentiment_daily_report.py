#!/usr/bin/env python3
"""
情绪每日复盘报告 - 盘后运行，生成纯文本报告

数据源:
1. sentiment_scores (盘后5维)
2. sentiment_live_log (盘中7维)  
3. broker_orders + broker_positions (交易数据)
4. forward_advice (前瞻建议)

输出: 纯文本，适合飞书/终端阅读
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
from datetime import datetime, timedelta
from collections import Counter
from pymongo import MongoClient


# ===== 中文映射 =====
PERIOD_CN = {
    'rising': '高潮', 'differentiation': '分化', 'chaos': '震荡', 'bearish': '冰点',
    'RISING': '高潮', 'DIFFERENTIATION': '分化', 'CHAOS': '震荡', 'BEARISH': '冰点',
    '高潮': '高潮', '分化': '分化', '震荡': '震荡', '冰点': '冰点',
}

PERIOD_EMOJI = {'高潮': '🔥', '分化': '⚡', '震荡': '🌀', '冰点': '🥶'}

STRATEGY_CN = {
    'halfway_chase': '半路追涨', 'first_limit_up': '首板', 'limit_down_qiao': '翘板',
    'dragon_head_low': '龙头低吸', 'dragon_head': '龙头', '炸板': '炸板',
}

DYNAMIC_MAX_POSITIONS = {
    '高潮': 10, '分化': 8, '震荡': 6, '冰点': 4,
    'rising': 10, 'differentiation': 8, 'chaos': 6, 'bearish': 4,
}

POSITION_COEFF = {  # score_range -> coeff
    (70, 999): 1.0, (55, 70): 0.7, (40, 55): 0.5, (0, 40): 0.3,
}

def score_to_coeff(score):
    for (lo, hi), coeff in POSITION_COEFF.items():
        if lo <= score < hi:
            return coeff
    return 0.3

def score_to_period_cn(score):
    if score >= 70: return '高潮'
    if score >= 55: return '分化'
    if score >= 40: return '震荡'
    return '冰点'

def score_to_period_cn_with_hint(score):
    """带偏强/偏弱提示的阶段名"""
    if score >= 70: return '高潮'
    if score >= 55: return score >= 62 and '分化偏强' or '分化'
    if score >= 40: return score >= 47 and '震荡偏强' or '震荡偏弱'
    return score >= 30 and '冰点偏暖' or '冰点'

def score_to_emoji(score):
    return PERIOD_EMOJI.get(score_to_period_cn(score), '🌀')


async def generate_report(date_str=None):
    """生成情绪复盘报告"""
    client = MongoClient('localhost', 27017)
    db = client['stock_agent']
    
    # ===== 确定日期 =====
    if date_str:
        trade_date = int(date_str)
    else:
        today = datetime.now()
        d = today
        while d.weekday() >= 5:
            d -= timedelta(days=1)
        trade_date = int(d.strftime('%Y%m%d'))
    
    date_display = str(trade_date)
    
    # ===== 1. 盘后5维 =====
    post_doc = db['sentiment_scores'].find_one({'trade_date': int(date_display)})
    post_score = post_doc.get('score', 0) if post_doc else 0
    post_period = PERIOD_CN.get(post_doc.get('period', ''), '未知') if post_doc else '无数据'
    post_lu = post_doc.get('limit_up', 0) if post_doc else 0
    post_ld = post_doc.get('limit_down', 0) if post_doc else 0
    
    # ===== 2. 盘中7维 =====
    live_logs = list(db['sentiment_live_log'].find({'trade_date': trade_date}).sort('ts', 1))
    
    if live_logs:
        scores = [l.get('score', 0) for l in live_logs]
        phases = [l.get('phase', '') for l in live_logs]
        times = [l.get('time', '') for l in live_logs]
        
        intraday_avg = sum(scores) / len(scores) if scores else 0
        intraday_min = min(scores) if scores else 0
        intraday_max = max(scores) if scores else 0
        intraday_period_cn = score_to_period_cn_with_hint(intraday_avg)
        
        # 阶段转换次数
        transitions = 0
        for i in range(1, len(phases)):
            if phases[i] != phases[i-1]:
                transitions += 1
        
        # 阶段分布
        phase_cnt = Counter(PERIOD_CN.get(p, p) for p in phases)
        total = len(phases)
        phase_dist = {k: round(v / total * 100) for k, v in phase_cnt.most_common()}
        
        # 盘中趋势: 前半vs后半
        mid = len(scores) // 2
        first_half_avg = sum(scores[:mid]) / mid if mid else 0
        second_half_avg = sum(scores[mid:]) / (len(scores) - mid) if (len(scores) - mid) else 0
        trend_diff = second_half_avg - first_half_avg
    else:
        intraday_avg = post_score
        intraday_min = intraday_max = post_score
        intraday_period_cn = post_period
        transitions = 0
        phase_dist = {}
        trend_diff = 0
    
    # ===== 3. 综合评分 =====
    overall_score = intraday_avg * 0.6 + post_score * 0.4 if live_logs else post_score
    overall_period = score_to_period_cn(overall_score)
    
    # 明日综合: 盘后50% + 盘中30% + 多日20%
    recent_docs = list(db['sentiment_scores'].find({}, sort=[('trade_date', -1)]).limit(5))
    recent_scores = [d.get('score', 0) for d in reversed(recent_docs)] if recent_docs else [post_score]
    recent_avg = sum(recent_scores) / len(recent_scores) if recent_scores else post_score
    
    tomorrow_score = post_score * 0.5 + intraday_avg * 0.3 + recent_avg * 0.2
    tomorrow_period = score_to_period_cn(tomorrow_score)
    tomorrow_coeff = score_to_coeff(tomorrow_score)
    tomorrow_max_pos = DYNAMIC_MAX_POSITIONS.get(tomorrow_period, 6)
    
    # ===== 4. 交易数据 =====
    orders = list(db['broker_orders'].find({
        'filled_time': {'$regex': f'^{date_display}'},
        'status': 'FILLED'
    }))
    
    buy_orders = [o for o in orders if o.get('side') == 'buy']
    sell_orders = [o for o in orders if o.get('side') == 'sell']
    
    total_pnl = 0
    for o in sell_orders:
        pnl = o.get('profit_loss', 0) or 0
        total_pnl += pnl
    
    # ===== 5. 持仓 =====
    positions = list(db['broker_positions'].find({'account_id': 'default', 'qty': {'$gt': 0}}))
    pos_count = len(positions)
    
    # ===== 6. 纪律检查 (简化版) =====
    violation_count = 0
    for o in buy_orders:
        trace = o.get('decision_trace', {})
        if isinstance(trace, dict):
            sent = trace.get('sentiment', {})
            if isinstance(sent, dict):
                trace_period = PERIOD_CN.get(sent.get('period', ''), '')
            else:
                trace_period = ''
        else:
            trace_period = ''
        strat = o.get('strategy', '')
        # 冰点期只有龙头低吸和翘板可开
        if trace_period == '冰点' and strat in ['halfway_chase', 'first_limit_up', '炸板']:
            violation_count += 1
    
    # ===== 组装报告 =====
    lines = []
    lines.append(f"{'='*40}")
    lines.append(f"📊 情绪日报 | {date_display}")
    lines.append(f"{'='*40}")
    
    # 今日总结
    lines.append(f"")
    lines.append(f"📋 今日总结")
    lines.append(f"  {score_to_emoji(overall_score)} 综合情绪{overall_score:.0f}分，{overall_period}期")
    
    if live_logs:
        # 一句话描述
        if overall_score >= 70:
            lines.append(f"  市场普涨，涨停潮，积极做多。")
        elif overall_score >= 55:
            lines.append(f"  市场有主线但分化，精选强势股参与。")
        elif overall_score >= 40:
            if transitions > 20:
                lines.append(f"  市场偏弱且情绪极不稳定({transitions}次转换)，轻仓防守。")
            else:
                lines.append(f"  市场偏弱，涨少跌多，轻仓防守。")
        else:
            if transitions > 20:
                lines.append(f"  市场冰冻且盘中反复摇摆({transitions}次转换)，应空仓观望。")
            else:
                lines.append(f"  市场冰冻，涨跌比极低，应空仓观望。")
    
    lines.append(f"")
    lines.append(f"  盘中7维: {intraday_avg:.0f}分({intraday_min:.0f}~{intraday_max:.0f}) {intraday_period_cn}期")
    lines.append(f"  盘后5维: {post_score:.0f}分 {post_period}期  涨停{post_lu} 跌停{post_ld}")
    lines.append(f"  综合评分: 盘中×60% + 盘后×40% = {overall_score:.0f}分")
    
    if phase_dist:
        dist_str = ' | '.join(f'{PERIOD_EMOJI.get(k, '')}{k}{v}%' for k, v in phase_dist.items())
        lines.append(f"  盘中分布: {dist_str}")
    
    if transitions > 0:
        stability = '极不稳定' if transitions > 20 else '波动较大' if transitions > 10 else '相对稳定'
        lines.append(f"  阶段转换: {transitions}次({stability})")
    
    if live_logs and abs(trend_diff) > 5:
        trend_str = f"午后走强(+{trend_diff:.0f})" if trend_diff > 0 else f"午后走弱({trend_diff:.0f})"
        lines.append(f"  盘中趋势: {trend_str}")
    
    # 交易
    if orders:
        lines.append(f"")
        lines.append(f"  交易: 买入{len(buy_orders)}笔 卖出{len(sell_orders)}笔")
        if total_pnl != 0:
            pnl_emoji = '💰' if total_pnl >= 0 else '💸'
            lines.append(f"  盈亏: {pnl_emoji} ¥{total_pnl:+,.0f}")
        if violation_count > 0:
            lines.append(f"  纪律: ⚠️ {violation_count}次违纪")
        else:
            lines.append(f"  纪律: ✅ 全部遵守")
    
    # 明日展望
    lines.append(f"")
    lines.append(f"🔮 明日展望")
    lines.append(f"  {score_to_emoji(tomorrow_score)} 明日建议: {_action_cn(tomorrow_score)}")
    lines.append(f"  综合评分: 盘后×50% + 盘中×30% + 多日×20% = {tomorrow_score:.0f}分")
    
    lines.append(f"")
    lines.append(f"  三维分析:")
    lines.append(f"    📊 盘后定调: {post_score:.0f}分 {post_period}期")
    lines.append(f"    📈 盘中趋势: {intraday_avg:.0f}分 {intraday_period_cn}期")
    
    # 多日走势
    if len(recent_scores) >= 3:
        recent_str = '→'.join(f'{s:.0f}' for s in recent_scores[-3:])
        if recent_scores[-1] < recent_scores[-2] < recent_scores[-3]:
            multi_trend = '📉 连续走低'
        elif recent_scores[-1] > recent_scores[-2] > recent_scores[-3]:
            multi_trend = '📈 连续回暖'
        else:
            multi_trend = '↔️ 震荡反复'
        lines.append(f"    📉 多日走势: {recent_str} {multi_trend}")
    
    lines.append(f"")
    lines.append(f"  仓位建议: {tomorrow_coeff*100:.0f}%  持仓上限{tomorrow_max_pos}只")
    
    # 策略开关
    lines.append(f"  策略开关:")
    for strat_key, strat_cn in STRATEGY_CN.items():
        if tomorrow_period == '冰点':
            open_flag = strat_key in ['dragon_head_low', 'limit_down_qiao']
        elif tomorrow_period == '震荡':
            open_flag = strat_key in ['dragon_head_low', 'limit_down_qiao', 'halfway_chase']
        elif tomorrow_period == '分化':
            open_flag = strat_key in ['dragon_head_low', 'halfway_chase', 'first_limit_up']
        else:  # 高潮
            open_flag = True
        icon = '✅' if open_flag else '🚫'
        reason = '' if open_flag else f'{tomorrow_period}期禁止'
        lines.append(f"    {icon} {strat_cn} {reason}")
    
    # 盘中特征补充
    if live_logs:
        lines.append(f"")
        if transitions > 20:
            lines.append(f"  ⚠️ 盘中情绪极不稳定({transitions}次转换)，明日开盘可能延续弱势")
        if intraday_avg - post_score > 15:
            lines.append(f"  ⚠️ 盘中均值({intraday_avg:.0f})显著高于盘后({post_score:.0f})，收盘走弱")
        if post_lu > 100:
            lines.append(f"  💡 涨停{post_lu}只偏多，关注明日连板机会")
        if post_ld > 100:
            lines.append(f"  ⚠️ 跌停{post_ld}只偏多，规避高位股和弱势板块")
    
    lines.append(f"")
    lines.append(f"{'='*40}")
    
    report = '\n'.join(lines)
    return report


def _action_cn(score):
    if score >= 70: return '积极做多'
    if score >= 55: return '精选参与'
    if score >= 40: return '轻仓防守'
    return '空仓观望'


if __name__ == '__main__':
    date_arg = sys.argv[1] if len(sys.argv) > 1 else None
    report = asyncio.run(generate_report(date_arg))
    print(report)
