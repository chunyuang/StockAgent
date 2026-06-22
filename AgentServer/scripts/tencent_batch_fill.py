#!/usr/bin/env python3
"""
用腾讯行情接口批量补全stock_daily_ak_full + daily_basic数据
- 一次请求最多50只股票
- 包含close/pre_close/pct_chg/pe/pb/turnover_rate/volume等
"""
import requests
import time
from pymongo import MongoClient, UpdateOne
from datetime import datetime

db = MongoClient('localhost', 27017)['stock_agent']

def ts_code_to_tencent(ts_code):
    """000001.SZ -> sz000001, 600036.SH -> sh600036"""
    code, market = ts_code.split('.')
    prefix = 'sz' if market == 'SZ' else 'sh'
    return f'{prefix}{code}'

def get_batch_quotes(tencent_codes, batch_size=50):
    """批量获取行情数据"""
    results = {}
    for i in range(0, len(tencent_codes), batch_size):
        batch = tencent_codes[i:i+batch_size]
        url = 'https://qt.gtimg.cn/q=' + ','.join(batch)
        try:
            r = requests.get(url, timeout=15)
            lines = r.text.strip().split(';')
            for line in lines:
                if '~' not in line or len(line) < 10:
                    continue
                parts = line.split('~')
                if len(parts) < 47:
                    continue
                try:
                    code = parts[2]  # 600036
                    tencent_code = parts[0].split('=')[0].split('_')[-1] if '=' in parts[0] else ''
                    # 从parts[0]提取前缀
                    var_part = line.split('=')[0] if '=' in line else ''
                    prefix = ''
                    for tc in batch:
                        if tc.endswith(code):
                            prefix = tc[:2]
                            break
                    
                    ts_code = f"{code}.SZ" if prefix == 'sz' else f"{code}.SH"
                    
                    data = {
                        'ts_code': ts_code,
                        'close': float(parts[3]) if parts[3] else None,
                        'pre_close': float(parts[4]) if parts[4] else None,
                        'open': float(parts[5]) if parts[5] else None,
                        'volume': float(parts[6]) if parts[6] else None,
                        'high': float(parts[33]) if len(parts) > 33 and parts[33] else None,
                        'low': float(parts[34]) if len(parts) > 34 and parts[34] else None,
                        'pct_chg': float(parts[32]) if parts[32] else None,
                        'turnover_rate': float(parts[38]) if parts[38] else None,
                        'pe_ttm': float(parts[39]) if parts[39] else None,
                        'pb': float(parts[46]) if len(parts) > 46 and parts[46] else None,
                        'total_mv': float(parts[45]) if len(parts) > 45 and parts[45] else None,
                        'trade_date': int(parts[30][:8]) if len(parts) > 30 and len(parts[30]) >= 8 else None,
                        'amount': float(parts[37]) if len(parts) > 37 and parts[37] else None,
                    }
                    
                    if data['close'] and data['trade_date']:
                        results[ts_code] = data
                except (ValueError, IndexError):
                    continue
        except Exception as e:
            print(f'  批次请求错误: {e}')
        time.sleep(0.2)
    return results


def fill_missing_dates():
    """补全缺失的交易日数据"""
    # 获取需要补的日期
    existing_dates = sorted(db.stock_daily_ak_full.distinct('trade_date', {'trade_date': {'$gte': 20260601}}))
    print(f'6月已有数据日期: {existing_dates[-5:]}')
    
    # 从腾讯获取招商银行确认最近交易日
    sample = get_batch_quotes(['sh600036'])
    if '600036.SH' in sample:
        latest_td = sample['600036.SH']['trade_date']
        print(f'腾讯显示最新交易日: {latest_td}')
    else:
        print('无法获取最新交易日')
        return
    
    # 需要补的日期范围
    missing_dates = []
    for d in range(20260616, latest_td + 1):
        d_int = int(d)
        # 跳过周末
        from datetime import datetime as dt
        try:
            wd = dt.strptime(str(d_int), '%Y%m%d').weekday()
            if wd >= 5:
                continue
        except:
            continue
        count = db.stock_daily_ak_full.count_documents({'trade_date': d_int})
        if count < 1000:  # 不完整
            missing_dates.append(d_int)
    
    print(f'需要补全的日期: {missing_dates}')
    
    # 获取全市场股票代码
    all_codes = db.stock_daily_ak_full.distinct('ts_code')
    # 加上stock_basic中的代码
    basic_codes = db.stock_basic.distinct('ts_code')
    all_codes = list(set(all_codes + basic_codes))
    print(f'总股票数: {len(all_codes)}')
    
    tencent_codes = [ts_code_to_tencent(c) for c in all_codes]
    
    # 批量获取行情
    print(f'\n获取全市场行情...')
    quotes = get_batch_quotes(tencent_codes, batch_size=50)
    print(f'获取到 {len(quotes)} 只股票行情')
    
    if not quotes:
        print('未获取到任何数据!')
        return
    
    # 按日期分组写入
    daily_ops = []
    basic_ops = []
    
    for ts_code, data in quotes.items():
        td = data.get('trade_date')
        if not td or td not in missing_dates:
            continue
        
        close = data.get('close')
        pre_close = data.get('pre_close')
        pct_chg = data.get('pct_chg')
        vol = data.get('volume')
        amt = data.get('amount')
        high = data.get('high')
        low = data.get('low')
        open_p = data.get('open')
        
        # stock_daily_ak_full
        daily_update = {
            'close': close,
            'open': open_p,
            'high': high,
            'low': low,
            'vol': vol,
            'amount': amt,
            'pct_chg': pct_chg,
            'pre_close': pre_close,
            'change': round(close - pre_close, 2) if close and pre_close else None,
            'updated_at': datetime.now(),
        }
        daily_ops.append(UpdateOne(
            {'ts_code': ts_code, 'trade_date': td},
            {'$set': daily_update},
            upsert=True
        ))
        
        # daily_basic
        basic_update = {
            'close': close,
            'pct_chg': pct_chg,
            'updated_at': datetime.now(),
        }
        if data.get('pe_ttm'): basic_update['pe_ttm'] = data['pe_ttm']
        if data.get('pb'): basic_update['pb'] = data['pb']
        if data.get('turnover_rate'): basic_update['turnover_rate'] = data['turnover_rate']
        if data.get('total_mv'): basic_update['total_mv'] = data['total_mv']
        
        basic_ops.append(UpdateOne(
            {'ts_code': ts_code, 'trade_date': td},
            {'$set': basic_update},
            upsert=True
        ))
    
    # 批量写入
    print(f'\n写入stock_daily_ak_full: {len(daily_ops)}条')
    if daily_ops:
        result = db.stock_daily_ak_full.bulk_write(daily_ops, ordered=False)
        print(f'  插入: {result.upserted_count}, 更新: {result.modified_count}')
    
    print(f'写入daily_basic: {len(basic_ops)}条')
    if basic_ops:
        result = db.daily_basic.bulk_write(basic_ops, ordered=False)
        print(f'  插入: {result.upserted_count}, 更新: {result.modified_count}')
    
    # 验证
    for td in missing_dates:
        c = db.stock_daily_ak_full.count_documents({'trade_date': td})
        c2 = db.daily_basic.count_documents({'trade_date': td})
        print(f'\n验证 {td}: stock_daily={c}, daily_basic={c2}')


if __name__ == '__main__':
    fill_missing_dates()
