#!/usr/bin/env python3
"""
详细验证数据质量
"""

import pymongo
import random

def verify_data_quality():
    print('=== 详细验证数据质量 ===')
    print()
    
    client = pymongo.MongoClient('localhost', 27017)
    db = client['stock_agent']
    collection = db['stock_daily_ak_full_ak']
    
    print('1. 数据总体情况:')
    total = collection.count_documents({})
    distinct_stocks = len(collection.distinct('ts_code'))
    distinct_dates = len(collection.distinct('trade_date'))
    
    print(f'   总记录数: {total}')
    print(f'   唯一股票数: {distinct_stocks}')
    print(f'   交易日数量: {distinct_dates}')
    print(f'   平均每只股票记录数: {total/distinct_stocks:.1f}')
    
    print()
    print('2. 时间范围检查:')
    all_dates = sorted(collection.distinct('trade_date'))
    if len(all_dates) > 0:
        print(f'   最早交易日: {all_dates[0]}')
        print(f'   最晚交易日: {all_dates[-1]}')
        print(f'   日期数量: {len(all_dates)}')
        
        # 检查日期连续性
        date_gaps = []
        for i in range(1, len(all_dates)):
            gap = (int(str(all_dates[i])[:8]) - int(str(all_dates[i-1])[:8]))
            if gap > 1:
                date_gaps.append((all_dates[i-1], all_dates[i], gap))
        
        if date_gaps:
            print(f'   ⚠️  发现日期间隔: {len(date_gaps)} 处')
            for gap in date_gaps[:3]:
                print(f'     {gap[0]} -> {gap[1]}: 间隔 {gap[2]} 天')
    
    print()
    print('3. 关键数据字段检查:')
    sample_doc = collection.find_one({})
    if sample_doc:
        print('   示例文档字段:')
        for key, value in sample_doc.items():
            if key != '_id':
                print(f'     {key}: {value}')
    
    print()
    print('4. 数据变化性检查:')
    print('   a) 检查同一只股票在不同交易日的数据是否有变化:')
    
    # 随机选择5只股票进行详细检查
    sample_stocks = list(collection.distinct('ts_code'))
    random.shuffle(sample_stocks)
    test_stocks = sample_stocks[:5]
    
    has_change = False
    has_identical = False
    
    for stock in test_stocks:
        print(f'   股票 {stock}:')
        records = list(collection.find({'ts_code': stock}).sort('trade_date', 1))
        
        if len(records) >= 2:
            # 检查前3个交易日
            first = records[0]
            second = records[1]
            
            print(f'     第1天 ({records[0]["trade_date"]}): O:{first["open"]} H:{first["high"]} L:{first["low"]} C:{first["close"]}')
            print(f'     第2天 ({records[1]["trade_date"]}): O:{second["open"]} H:{second["high"]} L:{second["low"]} C:{second["close"]}')
            
            # 检查是否有变化
            changed = False
            for key in ['open', 'high', 'low', 'close', 'vol', 'amount']:
                if first.get(key) != second.get(key):
                    changed = True
                    break
            
            if changed:
                print('     ✅ 数据有变化')
                has_change = True
                # 显示具体变化
                for key in ['open', 'high', 'low', 'close']:
                    if first.get(key) != second.get(key):
                        change_pct = (second[key] - first[key]) / first[key] * 100
                        print(f'       {key}: {first[key]} → {second[key]} ({change_pct:+.1f}%)')
                
                # 检查涨跌停价
                print(f'       up_limit: {first.get("up_limit")} → {second.get("up_limit")}')
                print(f'       down_limit: {first.get("down_limit")} → {second.get("down_limit")}')
            else:
                print('     ❌ 所有交易日数据完全相同！')
                has_identical = True
        
        print()
    
    print()
    print('5. 数据质量评估:')
    print(f'   成功下载股票数: {distinct_stocks} 只')
    print(f'   交易日数量: {distinct_dates} 天')
    print(f'   总记录数: {total} 条')
    
    if has_change:
        print('   ✅ 数据有正常变化 - 这是真实的历史数据')
    else:
        print('   ❌ 所有股票数据相同 - 可能是错误的数据源')
    
    if has_identical:
        print('   ⚠️  发现数据重复问题 - 需要检查数据下载过程')
    
    print()
    print('6. 回测可行性分析:')
    if total > 1000 and distinct_stocks >= 50 and distinct_dates >= 10:
        print('   ✅ 数据量足够进行回测测试')
        print(f'     股票数量: {distinct_stocks} 只 (建议至少50只)')
        print(f'     交易日数量: {distinct_dates} 天 (建议至少10天)')
        print(f'     总记录数: {total} 条')
    else:
        print('   ⚠️  数据量可能不足')
        print('     建议再下载更多数据')
    
    client.close()
    
    print()
    print('=' * 60)
    
    # 最终建议
    if has_change and total > 1000:
        print('✅ 数据质量良好，可以开始回测测试')
        return True
    elif has_change and total <= 1000:
        print('⚠️  数据质量良好但数量较少，建议下载更多数据后再回测')
        return False
    else:
        print('❌ 数据存在质量问题，需要重新下载')
        return False

if __name__ == "__main__":
    verify_data_quality()