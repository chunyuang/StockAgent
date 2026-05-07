#!/usr/bin/env python3
"""
量脉新接口批量测试 + SZ数据补充
明早9:30后运行，盘中数据更全
"""
import urllib.request, json, pymongo, time
from pymongo import UpdateOne

TOKEN = 'ebacbad6d64444cd037ac5504b63f25d'
BASE = 'http://124.220.44.71/api/gateway'
INTERVAL = 0.7  # 120次/分 → 0.5s + 余量

client = pymongo.MongoClient('localhost', 27017)
db = client['stock_agent']
daily_basic = db['daily_basic']
stock_daily = db['stock_daily_ak_full']

def api_call(url, timeout=15):
    """调用量脉API，处理429"""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = json.loads(resp.read())
        if isinstance(data, dict) and 'data' in data:
            return data['data']
        return data
    except urllib.error.HTTPError as e:
        return None

def test_all_apis():
    """测试所有新发现的接口"""
    results = {}
    
    # 1. quote_bars_history (历史K线+pc前收盘价)
    data = api_call(f'{BASE}?token={TOKEN}&api=quote_bars_history&ts_code=000001&klt=d&fqt=n&lt=5')
    if data and isinstance(data, list):
        results['quote_bars_history'] = len(data)
        print(f"✅ quote_bars_history: {len(data)}条")
        for r in data:
            print(f"  t={r.get('t')} o={r.get('o')} c={r.get('c')} pc={r.get('pc')} v={r.get('v')} a={r.get('a')}")
    else:
        results['quote_bars_history'] = 'FAIL'
        print("❌ quote_bars_history")
    time.sleep(2)
    
    # 2. pool_strong (强势股池)
    today_str = time.strftime('%Y-%m-%d')
    data = api_call(f'{BASE}?token={TOKEN}&api=pool_strong&date={today_str}')
    if data and isinstance(data, list):
        results['pool_strong'] = len(data)
        print(f"✅ pool_strong: {len(data)}只")
        if data:
            r = data[0]
            print(f"  {r.get('dm')}: p={r.get('p')} lt={r.get('lt')} hs={r.get('hs')} lb={r.get('lb')}")
    else:
        results['pool_strong'] = 'FAIL'
        print("❌ pool_strong")
    time.sleep(2)
    
    # 3. pool_limit_up
    data = api_call(f'{BASE}?token={TOKEN}&api=pool_limit_up&date={today_str}')
    if data and isinstance(data, list):
        results['pool_limit_up'] = len(data)
        print(f"✅ pool_limit_up: {len(data)}只")
    else:
        results['pool_limit_up'] = 'FAIL'
        print("❌ pool_limit_up")
    time.sleep(2)
    
    # 4. capital_flow_history
    data = api_call(f'{BASE}?token={TOKEN}&api=capital_flow_history&ts_code=000001&lt=3')
    if data and isinstance(data, list):
        results['capital_flow_history'] = len(data)
        print(f"✅ capital_flow_history: {len(data)}条")
    else:
        results['capital_flow_history'] = 'FAIL'
        print("❌ capital_flow_history")
    time.sleep(2)
    
    # 5. hs_list_main (股票列表)
    data = api_call(f'{BASE}?token={TOKEN}&api=hs_list_main')
    if data and isinstance(data, list):
        sz = sum(1 for r in data if r.get('jys') == 'sz')
        sh = sum(1 for r in data if r.get('jys') == 'sh')
        results['hs_list_main'] = f'{len(data)}(SH:{sh} SZ:{sz})'
        print(f"✅ hs_list_main: {len(data)}只 (SH:{sh} SZ:{sz})")
    else:
        results['hs_list_main'] = 'FAIL'
        print("❌ hs_list_main")
    time.sleep(2)
    
    # 6. quote_stop_prices
    data = api_call(f'{BASE}?token={TOKEN}&api=quote_stop_prices&ts_code=000001')
    if data and isinstance(data, list):
        results['quote_stop_prices'] = len(data)
        print(f"✅ quote_stop_prices: {len(data)}条")
    else:
        results['quote_stop_prices'] = 'FAIL'
        print("❌ quote_stop_prices")
    time.sleep(2)
    
    # 7. stock_realtime_multi (20只/次)
    codes = '000001,000002,000006,000007,000008,000009,000010,000011,000012,000014,000016,000017,000018,000019,000020,000021,000022,000023,000025,000026'
    data = api_call(f'{BASE}?token={TOKEN}&api=stock_realtime_multi&stock_codes={codes}')
    if data and isinstance(data, list):
        results['stock_realtime_multi'] = len(data)
        print(f"✅ stock_realtime_multi: {len(data)}只")
        if data:
            r = data[0]
            print(f"  {r.get('dm')}: lt={r.get('lt')} hs={r.get('hs')} lb={r.get('lb')} pe={r.get('pe')} sjl={r.get('sjl')}")
    else:
        results['stock_realtime_multi'] = 'FAIL'
        print("❌ stock_realtime_multi")
    
    return results

def supplement_sz_data():
    """用stock_realtime_multi批量补充SZ数据"""
    today = int(time.strftime('%Y%m%d'))
    
    # 获取SZ股票代码
    sz_codes = stock_daily.distinct('ts_code', {'ts_code': {'$regex': '\\.SZ$'}, 'trade_date': today})
    print(f"\n=== 补充SZ数据: {len(sz_codes)}只 ===")
    
    # 去掉后缀，只留6位代码
    codes_list = [c.replace('.SZ', '') for c in sz_codes]
    
    updated = 0
    batch = []
    start = time.time()
    
    # 每次20只
    for i in range(0, len(codes_list), 20):
        chunk = codes_list[i:i+20]
        codes_str = ','.join(chunk)
        url = f'{BASE}?token={TOKEN}&api=stock_realtime_multi&stock_codes={codes_str}'
        
        data = api_call(url)
        if data and isinstance(data, list):
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
                rate = (i+20) / elapsed * 60
                print(f"  {i+20}/{len(codes_list)} ({updated}更新) {rate:.0f}只/分")
        
        time.sleep(INTERVAL)
    
    if batch:
        daily_basic.bulk_write(batch, ordered=False)
    
    elapsed = time.time() - start
    print(f"\n完成: {updated}只, 耗时{elapsed/60:.1f}分")
    
    # 统计
    sz_cm = daily_basic.count_documents({'trade_date': today, 'circ_mv': {'$ne': None}, 'ts_code': {'$regex': '\\.SZ$'}})
    sz_tr = daily_basic.count_documents({'trade_date': today, 'turnover_rate': {'$ne': None}, 'ts_code': {'$regex': '\\.SZ$'}})
    sz_pe = daily_basic.count_documents({'trade_date': today, 'pe': {'$ne': None}, 'ts_code': {'$regex': '\\.SZ$'}})
    print(f"SZ: PE={sz_pe} circ_mv={sz_cm} turnover_rate={sz_tr}")

if __name__ == '__main__':
    print(f"=== 量脉接口测试+数据补充 {time.strftime('%Y-%m-%d %H:%M')} ===\n")
    
    # Phase 1: 测试所有接口
    results = test_all_apis()
    
    print(f"\n=== 测试汇总 ===")
    for k, v in results.items():
        print(f"  {k}: {v}")
    
    # Phase 2: 补充SZ数据
    supplement_sz_data()
