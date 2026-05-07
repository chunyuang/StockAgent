#!/usr/bin/env python3
"""
量脉API完整测试脚本 - 覆盖文档所有27个接口
使用方式: python3 test_liangmai_all_apis.py

调用方式: GET请求网关 http://124.220.44.71/api/gateway
参数: token=xxx&api=接口别名&其他参数

限流规则:
- 120次/分钟 (间隔0.5s+0.2s余量=0.7s)
- Token绑定2个IP (4291=IP超限)
- 特殊接口(all_broker/all_network)限1次/分钟
"""

import urllib.request
import json
import time
import sys

# ============ 配置 ============
TOKEN = 'ebacbad6d64444cd037ac5504b63f25d'
BASE = 'http://124.220.44.71/api/gateway'
INTERVAL = 0.7  # 秒，120次/分→0.5s+余量
TODAY = time.strftime('%Y-%m-%d')  # yyyy-MM-dd格式，量脉日期接口用
TODAY_INT = int(time.strftime('%Y%m%d'))  # yyyyMMdd格式

# ============ 调用函数 ============
def call_api(api_name, params=None, timeout=15):
    """
    调用量脉API
    
    参数:
        api_name: 接口别名(如 'hs_list_main', 'pool_limit_up')
        params: 额外参数字典(如 {'ts_code': '000001', 'date': '2026-05-06'})
        timeout: 超时秒数
    
    返回:
        (成功/失败, 数据/错误信息)
    
    示例:
        call_api('hs_list_main')
        call_api('pool_limit_up', {'date': '2026-05-06'})
        call_api('stock_realtime_multi', {'stock_codes': '000001,000002'})
        call_api('quote_bars_history', {'ts_code': '000001', 'klt': 'd', 'fqt': 'n', 'lt': '5'})
    """
    # 构建URL
    url = f'{BASE}?token={TOKEN}&api={api_name}'
    if params:
        for k, v in params.items():
            url += f'&{k}={v}'
    
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = json.loads(resp.read())
        
        # 有些接口返回 {"data": [...]}，有些直接返回 [...]
        if isinstance(data, dict) and 'data' in data:
            return True, data['data']
        if isinstance(data, dict) and 'code' in data:
            # 业务错误(如422参数错误)
            return False, f"code={data.get('code')} msg={data.get('msg', '')[:200]}"
        return True, data
    
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:300]
        if e.code == 429:
            return False, f"HTTP 429 (频率/IP限制): {body}"
        return False, f"HTTP {e.code}: {body}"
    except Exception as e:
        return False, str(e)


def test_api(name, params=None, show_sample=True, sample_count=3):
    """测试单个API并打印结果"""
    ok, data = call_api(name, params)
    
    if not ok:
        print(f"  ❌ {name}: {data}")
        return False
    
    if isinstance(data, list):
        print(f"  ✅ {name}: {len(data)}条")
        if show_sample and data:
            for r in data[:sample_count]:
                if isinstance(r, dict):
                    # 打印关键字段(截断)
                    sample = {k: v for k, v in list(r.items())[:8]}
                    print(f"     {sample}")
    elif isinstance(data, dict):
        print(f"  ✅ {name}: dict, keys={list(data.keys())[:10]}")
    else:
        print(f"  ✅ {name}: {type(data)}")
    
    return True


# ============ 测试所有接口 ============
def test_all():
    print(f"=== 量脉API完整测试 {time.strftime('%Y-%m-%d %H:%M')} ===")
    print(f"Token: ...{TOKEN[-8:]}")
    print(f"日期: {TODAY}")
    print(f"间隔: {INTERVAL}s\n")
    
    results = {}
    
    # ========== 1. 股票列表类 ==========
    print("【1. 股票列表类】")
    
    # 1.1 hs_list_main - 股票列表
    results['hs_list_main'] = test_api('hs_list_main')
    time.sleep(INTERVAL)
    
    # 1.2 ipo_calendar - 新股日历
    results['ipo_calendar'] = test_api('ipo_calendar')
    time.sleep(INTERVAL)
    
    # ========== 2. 行业概念类 ==========
    print("\n【2. 行业概念类】")
    
    # 2.1 sector_tree - 指数/行业/概念树 (数据量大，可能慢)
    results['sector_tree'] = test_api('sector_tree', show_sample=True, sample_count=2)
    time.sleep(INTERVAL)
    
    # 2.2 sector_constituents - 根据行业代码找股票 (用上证50的代码)
    results['sector_constituents'] = test_api('sector_constituents', {'code': 'sh000016'})
    time.sleep(INTERVAL)
    
    # 2.3 stock_sectors - 根据股票找行业
    results['stock_sectors'] = test_api('stock_sectors', {'ts_code': '000001'})
    time.sleep(INTERVAL)
    
    # ========== 3. 涨跌股池类 ==========
    print("\n【3. 涨跌股池类】")
    
    # 3.1 pool_limit_up - 涨停股池 (日期格式yyyy-MM-dd)
    results['pool_limit_up'] = test_api('pool_limit_up', {'date': TODAY})
    time.sleep(INTERVAL)
    
    # 3.2 pool_limit_down - 跌停股池
    results['pool_limit_down'] = test_api('pool_limit_down', {'date': TODAY})
    time.sleep(INTERVAL)
    
    # 3.3 pool_strong - 强势股池
    results['pool_strong'] = test_api('pool_strong', {'date': TODAY})
    time.sleep(INTERVAL)
    
    # 3.4 pool_subnew - 次新股池
    results['pool_subnew'] = test_api('pool_subnew', {'date': TODAY})
    time.sleep(INTERVAL)
    
    # 3.5 pool_broken_board - 炸板股池
    results['pool_broken_board'] = test_api('pool_broken_board', {'date': TODAY})
    time.sleep(INTERVAL)
    
    # ========== 4. 公司详情类 ==========
    print("\n【4. 公司详情类】")
    
    # 4.1 company_profile - 公司简介
    results['company_profile'] = test_api('company_profile', {'ts_code': '000001'}, sample_count=1)
    time.sleep(INTERVAL)
    
    # 4.2 company_index_membership - 所属指数
    results['company_index_membership'] = test_api('company_index_membership', {'ts_code': '000001'})
    time.sleep(INTERVAL)
    
    # 4.3 company_dividend - 分红
    results['company_dividend'] = test_api('company_dividend', {'ts_code': '000001'})
    time.sleep(INTERVAL)
    
    # 4.4 company_finance_metrics - 财务指标
    results['company_finance_metrics'] = test_api('company_finance_metrics', {'ts_code': '000001'}, sample_count=1)
    time.sleep(INTERVAL)
    
    # 4.5 company_quarter_profit - 季度利润
    results['company_quarter_profit'] = test_api('company_quarter_profit', {'ts_code': '000001'})
    time.sleep(INTERVAL)
    
    # 4.6 company_quarter_cashflow - 季度现金流
    results['company_quarter_cashflow'] = test_api('company_quarter_cashflow', {'ts_code': '000001'})
    time.sleep(INTERVAL)
    
    # 4.7 company_forecast - 业绩预告
    results['company_forecast'] = test_api('company_forecast', {'ts_code': '000001'})
    time.sleep(INTERVAL)
    
    # ========== 5. 行情类 (最重要！) ==========
    print("\n【5. 行情类】")
    
    # 5.1 quote_bars_latest - 最新K线 (日线，最近5条)
    # klt: 1/5/15/30/60/d/w/m/y  fqt: n(不复权)/f(前复权)/b(后复权)  lt: 条数
    results['quote_bars_latest'] = test_api('quote_bars_latest', 
        {'ts_code': '000001', 'klt': 'd', 'fqt': 'n', 'lt': '5'})
    time.sleep(INTERVAL)
    
    # 5.2 quote_bars_history - 历史K线 (有pc前收盘价! 日期格式YYYYMMDD)
    # 这是最重要的接口之一，可以替代通达信补数据！
    results['quote_bars_history'] = test_api('quote_bars_history',
        {'ts_code': '000001', 'klt': 'd', 'fqt': 'n', 'lt': '5'})
    time.sleep(INTERVAL)
    
    # 5.3 quote_stop_prices - 涨跌停价格
    results['quote_stop_prices'] = test_api('quote_stop_prices', {'ts_code': '000001'})
    time.sleep(INTERVAL)
    
    # 5.4 quote_realtime_broker - 单只实时(券商源)
    results['quote_realtime_broker'] = test_api('quote_realtime_broker', {'ts_code': '000001'})
    time.sleep(INTERVAL)
    
    # 5.5 quote_realtime_network - 单只实时(网络源)
    results['quote_realtime_network'] = test_api('quote_realtime_network', {'ts_code': '000001'})
    time.sleep(INTERVAL)
    
    # 5.6 stock_realtime - 单只实时(网络源，同5.5)
    results['stock_realtime'] = test_api('stock_realtime', {'ts_code': '000001'})
    time.sleep(INTERVAL)
    
    # 5.7 stock_realtime_multi - 批量实时(20只/次)
    # ⚠️ 参数名是stock_codes(不是ts_code!)，逗号分隔6位代码
    results['stock_realtime_multi'] = test_api('stock_realtime_multi',
        {'stock_codes': '000001,000002,600519,300750,000858'})
    time.sleep(INTERVAL)
    
    # 5.8 market_realtime_all_broker - 全市场实时(券商源)
    # ⚠️ 限1次/分钟!
    results['market_realtime_all_broker'] = test_api('market_realtime_all_broker',
        show_sample=False)  # 数据量大，不打印sample
    time.sleep(65)  # 等1分钟冷却(特殊接口限制)
    
    # 5.9 market_realtime_all_network - 全市场实时(网络源)
    # ⚠️ 限1次/分钟!
    results['market_realtime_all_network'] = test_api('market_realtime_all_network',
        show_sample=False)
    time.sleep(INTERVAL)
    
    # ========== 6. 资金类 ==========
    print("\n【6. 资金类】")
    
    # 6.1 capital_flow_history - 资金流向
    # 日期格式YYYYMMDD，可指定lt条数
    results['capital_flow_history'] = test_api('capital_flow_history',
        {'ts_code': '000001', 'start': '20260501', 'end': '20260506'})
    time.sleep(INTERVAL)
    
    # ========== 汇总 ==========
    print(f"\n{'='*60}")
    print(f"=== 测试汇总 ===")
    print(f"{'='*60}")
    success = sum(1 for v in results.values() if v)
    fail = sum(1 for v in results.values() if not v)
    print(f"成功: {success}  失败: {fail}  总计: {len(results)}")
    print()
    
    for k, v in sorted(results.items()):
        status = "✅" if v else "❌"
        print(f"  {status} {k}")
    
    return results


if __name__ == '__main__':
    test_all()
