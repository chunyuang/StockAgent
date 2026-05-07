#!/usr/bin/env python3
"""
量脉API完整测试脚本 - 使用requests库(官方推荐方式)
覆盖文档所有27个接口

使用方式: python3 test_liangmai_all_apis_v2.py

官方调用示例:
    import requests
    r = requests.get(
        "http://124.220.44.71/api/gateway",
        params={"token": "YOUR_TOKEN", "api": "stock_realtime", "ts_code": "600519"},
        timeout=30,
    )
    print(r.json())
"""

import requests
import json
import time
import pymongo
from pymongo import UpdateOne

# ============ 配置 ============
TOKEN = 'ebacbad6d64444cd037ac5504b63f25d'
GATEWAY = 'http://124.220.44.71/api/gateway'
INTERVAL = 0.7  # 120次/分 → 0.5s + 0.2s余量
TODAY = time.strftime('%Y-%m-%d')  # yyyy-MM-dd
TODAY_INT = int(time.strftime('%Y%m%d'))  # yyyyMMdd


# ============ 核心调用函数 ============
def call_api(api_name, extra_params=None, timeout=30):
    """
    调用量脉API - 使用requests库(官方推荐方式)
    
    参数:
        api_name: 接口别名，如 'hs_list_main', 'stock_realtime'
        extra_params: 额外参数字典，如 {'ts_code': '000001', 'date': '2026-05-06'}
        timeout: 超时秒数(默认30)
    
    返回:
        (success: bool, data: list/dict/str)
    
    调用示例:
        # 无参数接口
        call_api('hs_list_main')
        
        # 带日期参数(yyyy-MM-dd格式)
        call_api('pool_limit_up', {'date': '2026-05-06'})
        
        # 带股票代码
        call_api('stock_realtime', {'ts_code': '600519'})
        
        # 批量查询(参数名是stock_codes不是ts_code!)
        call_api('stock_realtime_multi', {'stock_codes': '000001,000002,600519'})
        
        # 历史K线(klt=级别, fqt=复权, lt=条数)
        call_api('quote_bars_history', {'ts_code': '000001', 'klt': 'd', 'fqt': 'n', 'lt': '5'})
        
        # 资金流向(日期YYYYMMDD格式)
        call_api('capital_flow_history', {'ts_code': '000001', 'start': '20260501', 'end': '20260506'})
    """
    params = {'token': TOKEN, 'api': api_name}
    if extra_params:
        params.update(extra_params)
    
    try:
        r = requests.get(GATEWAY, params=params, timeout=timeout)
        
        # 处理HTTP错误
        if r.status_code == 429:
            # 429可能是频率限制或IP限制
            try:
                body = r.json()
                return False, f"429 code={body.get('code')} msg={body.get('msg','')[:100]}"
            except:
                return False, f"429 (非JSON响应)"
        
        r.raise_for_status()
        data = r.json()
        
        # 新文档: 成功时code=20000, msg=success
        # 也有些接口直接返回数组(无顶层code)
        if isinstance(data, list):
            # 直接返回数组
            return True, data
        
        if isinstance(data, dict):
            code = data.get('code')
            msg = data.get('msg', '')
            
            # 业务错误(如422参数错误, 4291 IP超限)
            if code is not None and code not in (0, 20000):
                return False, f"code={code} msg={msg[:200]}"
            
            # 成功: 取data字段
            if 'data' in data:
                return True, data['data']
            
            # 有些接口直接返回对象(无data包装)
            return True, data
        
        return True, data
    
    except requests.exceptions.Timeout:
        return False, "Timeout"
    except requests.exceptions.ConnectionError:
        return False, "ConnectionError"
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
                    # 只打印前6个字段，避免刷屏
                    sample = {k: v for k, v in list(r.items())[:6]}
                    print(f"     {sample}")
    elif isinstance(data, dict):
        print(f"  ✅ {name}: dict, keys={list(data.keys())[:10]}")
    else:
        print(f"  ✅ {name}: {type(data)}")
    
    return True


# ============ 测试所有27个接口 ============
def test_all():
    print(f"=== 量脉API完整测试 (requests库) {time.strftime('%Y-%m-%d %H:%M')} ===")
    print(f"网关: {GATEWAY}")
    print(f"Token: ...{TOKEN[-8:]}")
    print(f"日期: {TODAY}")
    print(f"间隔: {INTERVAL}s\n")
    
    results = {}
    
    # ========== 1. 股票列表类 ==========
    print("【1. 股票列表类")
    # stock_list: 沪深京合并(推荐, 含BJ!)
    results['stock_list'] = test_api('stock_list')
    time.sleep(INTERVAL)
    results['hs_list_main'] = test_api('hs_list_main')
    time.sleep(INTERVAL)
    results['index_list_main'] = test_api('index_list_main')
    time.sleep(INTERVAL)
    results['bj_list_stocks'] = test_api('bj_list_stocks')
    time.sleep(INTERVAL)
    results['ipo_calendar'] = test_api('ipo_calendar')
    time.sleep(INTERVAL)
    results['base_st'] = test_api('base_st')  # ST股票列表
    time.sleep(INTERVAL)
    
    # ========== 2. 行业概念类 ==========
    print("\n【2. 行业概念类")
    results['base_gn'] = test_api('base_gn')  # 概念代码
    time.sleep(INTERVAL)
    results['base_bk'] = test_api('base_bk')  # 板块代码
    time.sleep(INTERVAL)
    results['sector_tree'] = test_api('sector_tree', sample_count=2)
    time.sleep(INTERVAL)
    # sector_constituents: 参数名是sector_code(不是code!)
    results['sector_constituents'] = test_api('sector_constituents', {'sector_code': 'sh000016'})
    time.sleep(INTERVAL)
    results['stock_sectors'] = test_api('stock_sectors', {'ts_code': '000001'})
    time.sleep(INTERVAL)
    results['base_bk_flow_history'] = test_api('base_bk_flow_history', {'bkCode': 'BK1036'})
    time.sleep(INTERVAL)
    results['base_bk_list'] = test_api('base_bk_list', {'bkCode': 'BK1036', 'pageNo': '1', 'pageSize': '5'})
    time.sleep(INTERVAL)
    
    # ========== 3. 涨跌股池类 ==========
    print("\n【3. 涨跌股池类】")
    # 日期格式: yyyy-MM-dd
    results['pool_limit_up'] = test_api('pool_limit_up', {'date': TODAY})
    time.sleep(INTERVAL)
    results['pool_limit_down'] = test_api('pool_limit_down', {'date': TODAY})
    time.sleep(INTERVAL)
    results['pool_strong'] = test_api('pool_strong', {'date': TODAY})
    time.sleep(INTERVAL)
    results['pool_subnew'] = test_api('pool_subnew', {'date': TODAY})
    time.sleep(INTERVAL)
    results['pool_broken_board'] = test_api('pool_broken_board', {'date': TODAY})
    time.sleep(INTERVAL)
    
    # ========== 4. 公司详情类 ==========
    print("\n【4. 公司详情类】")
    results['company_profile'] = test_api('company_profile', {'ts_code': '000001'}, sample_count=1)
    time.sleep(INTERVAL)
    results['company_index_membership'] = test_api('company_index_membership', {'ts_code': '000001'})
    time.sleep(INTERVAL)
    results['company_dividend'] = test_api('company_dividend', {'ts_code': '000001'})
    time.sleep(INTERVAL)
    results['company_finance_metrics'] = test_api('company_finance_metrics', {'ts_code': '000001'}, sample_count=1)
    time.sleep(INTERVAL)
    results['company_quarter_profit'] = test_api('company_quarter_profit', {'ts_code': '000001'})
    time.sleep(INTERVAL)
    results['company_quarter_cashflow'] = test_api('company_quarter_cashflow', {'ts_code': '000001'})
    time.sleep(INTERVAL)
    results['company_forecast'] = test_api('company_forecast', {'ts_code': '000001'})
    time.sleep(INTERVAL)
    results['company_holders_top10'] = test_api('company_holders_top10', {'ts_code': '000001'}, sample_count=1)
    time.sleep(INTERVAL)
    results['company_float_holders_top10'] = test_api('company_float_holders_top10', {'ts_code': '000001'}, sample_count=1)
    time.sleep(INTERVAL)
    results['company_holder_trend'] = test_api('company_holder_trend', {'ts_code': '000001'})
    time.sleep(INTERVAL)
    results['company_fund_holdings'] = test_api('company_fund_holdings', {'ts_code': '000001'})
    time.sleep(INTERVAL)
    
    # ========== 5. 行情类 ==========
    print("\n【5. 行情类 - 最重要】")
    
    # 5.1 quote_bars_latest - 最新K线
    # klt: 1/5/15/30/60/d/w/m/y  fqt: n/f/b/fr/br  lt: 条数
    results['quote_bars_latest'] = test_api('quote_bars_latest',
        {'ts_code': '000001', 'klt': 'd', 'fqt': 'n', 'lt': '5'})
    time.sleep(INTERVAL)
    
    # 5.2 quote_bars_history - 历史K线(有pc前收盘价!)
    # 可指定start/end(YYYYMMDD格式)
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
    
    # 5.6 stock_realtime - 单只实时(同5.5)
    results['stock_realtime'] = test_api('stock_realtime', {'ts_code': '000001'})
    time.sleep(INTERVAL)
    
    # 5.7 stock_realtime_multi - 批量实时(20只/次)
    # ⚠️ 参数名是stock_codes(不是ts_code!)，逗号分隔6位代码
    # ⚠️ 新文档提示: 若返回权限类错误，多为套餐不含「多股实时」能力
    results['stock_realtime_multi'] = test_api('stock_realtime_multi',
        {'stock_codes': '000001,000002,600519,300750,000858'})
    time.sleep(INTERVAL)
    
    # 5.7b stock_ticks_today - 当日逐笔成交(方向: 0中性 1买 2卖)
    results['stock_ticks_today'] = test_api('stock_ticks_today', {'ts_code': '000001'})
    time.sleep(INTERVAL)
    
    # 5.8 market_realtime_all_broker - 全市场(券商源)
    # ⚠️ 限1次/分钟!
    print("  (等待60秒 - 特殊接口限1次/分)")
    time.sleep(60)
    results['market_realtime_all_broker'] = test_api('market_realtime_all_broker', show_sample=False)
    time.sleep(INTERVAL)
    
    # 5.9 market_realtime_all_network - 全市场(网络源)
    # ⚠️ 限1次/分钟!
    print("  (等待60秒 - 特殊接口限1次/分)")
    time.sleep(60)
    results['market_realtime_all_network'] = test_api('market_realtime_all_network', show_sample=False)
    time.sleep(INTERVAL)
    
    # ========== 6. 资金类 ==========
    print("\n【6. 资金类】")
    # 日期格式: YYYYMMDD
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


# ============ SZ数据补充 ============
def supplement_sz_with_multi():
    """
    用stock_realtime_multi批量补充SZ流通市值/换手率/量比
    每次20只，2510只SZ需126次请求，约2分钟
    """
    client = pymongo.MongoClient('localhost', 27017)
    db = client['stock_agent']
    daily_basic = db['daily_basic']
    stock_daily = db['stock_daily_ak_full']
    today = int(time.strftime('%Y%m%d'))
    
    sz_codes = stock_daily.distinct('ts_code', {'ts_code': {'$regex': '\\.SZ$'}, 'trade_date': today})
    codes_list = [c.replace('.SZ', '') for c in sz_codes]
    print(f"\n=== SZ数据补充: {len(codes_list)}只 (每次20只, {len(codes_list)//20+1}次) ===")
    
    updated = 0
    batch = []
    start = time.time()
    
    for i in range(0, len(codes_list), 20):
        chunk = codes_list[i:i+20]
        ok, data = call_api('stock_realtime_multi', {'stock_codes': ','.join(chunk)})
        
        if ok and isinstance(data, list):
            for r in data:
                dm = str(r.get('dm', '')).zfill(6)
                if len(dm) != 6 or not dm.isdigit():
                    continue
                ts_code = f'{dm}.SZ'
                
                doc = {}
                if r.get('lt') and r['lt'] > 0:
                    doc['circ_mv'] = r['lt'] / 10000  # 元→万元
                if r.get('sz') and r['sz'] > 0:
                    doc['total_mv'] = r['sz'] / 10000
                if r.get('hs') and r['hs'] > 0:
                    doc['turnover_rate'] = r['hs']
                if r.get('lb') and r['lb'] > 0:
                    doc['volume_ratio'] = r['lb']
                if r.get('pe') and r['pe'] > 0:
                    doc['pe'] = r['pe']
                if r.get('sjl') and r['sjl'] > 0:
                    doc['pb'] = r['sjl']
                
                if doc:
                    batch.append(UpdateOne(
                        {'ts_code': ts_code, 'trade_date': today},
                        {'$set': doc},
                        upsert=True
                    ))
                    updated += 1
            
            if len(batch) >= 500:
                daily_basic.bulk_write(batch, ordered=False)
                batch = []
                elapsed = time.time() - start
                print(f"  {i+20}/{len(codes_list)} ({updated}更新) {elapsed/60:.1f}分")
        else:
            print(f"  ❌ 第{i//20+1}批失败: {data}")
            if '429' in str(data):
                print("  ⏳ IP被占，等30秒...")
                time.sleep(30)
        
        time.sleep(INTERVAL)
    
    if batch:
        daily_basic.bulk_write(batch, ordered=False)
    
    elapsed = time.time() - start
    print(f"\n完成: {updated}只, 耗时{elapsed/60:.1f}分")
    
    sz_cm = daily_basic.count_documents({'trade_date': today, 'circ_mv': {'$ne': None}, 'ts_code': {'$regex': '\\.SZ$'}})
    sz_tr = daily_basic.count_documents({'trade_date': today, 'turnover_rate': {'$ne': None}, 'ts_code': {'$regex': '\\.SZ$'}})
    print(f"SZ: circ_mv={sz_cm} turnover_rate={sz_tr}")


if __name__ == '__main__':
    results = test_all()
    
    # 如果行情接口可用，补充SZ数据
    if results.get('stock_realtime_multi'):
        print("\n\n行情接口可用，开始补充SZ数据...")
        supplement_sz_with_multi()
