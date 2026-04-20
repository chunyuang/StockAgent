#!/usr/bin/env python3
"""
简单直接的 AKShare 数据下载脚本
只获取数据，不进行复杂处理
"""

import akshare as ak
import pymongo
import time
from datetime import datetime, timedelta

def get_trade_dates(start_date, end_date):
    """获取交易日列表"""
    dates = []
    current = datetime.strptime(start_date, "%Y%m%d")
    end = datetime.strptime(end_date, "%Y%m%d")
    
    while current <= end:
        if current.weekday() < 5:  # 周一到周五
            dates.append(current.strftime("%Y%m%d"))
        current += timedelta(days=1)
    
    return dates

def main():
    print("🚀 开始下载 AKShare 数据 (简单版)")
    print("=" * 60)
    
    # 设置参数
    start_date = "20260105"
    end_date = "20260320"
    
    print(f"📅 时间范围: {start_date} - {end_date}")
    print()
    
    # 获取交易日列表
    trade_dates = get_trade_dates(start_date, end_date)
    print(f"📊 总共 {len(trade_dates)} 个交易日")
    print()
    
    # 连接数据库
    client = pymongo.MongoClient('localhost', 27017)
    db = client['stock_agent']
    collection = db['stock_daily_ak_full_ak']
    
    total_records = 0
    
    # 处理每个交易日
    for i, trade_date in enumerate(trade_dates, 1):
        print(f"[{i}/{len(trade_dates)}] 处理 {trade_date}...")
        
        try:
            # 使用 AKShare 获取实时行情数据
            df = ak.stock_zh_a_spot()
            
            if df is None or df.empty:
                print("  ⚠️  没有数据")
                continue
            
            # 处理数据
            records = []
            for _, row in df.iterrows():
                code = str(row['代码']).zfill(6)
                
                # 确定后缀
                if code.startswith('6') or code.startswith('5'):
                    ts_code = f"{code}.SH"
                else:
                    ts_code = f"{code}.SZ"
                
                # 创建记录
                record = {
                    '_id': f"{ts_code}_{trade_date}",
                    'ts_code': ts_code,
                    'trade_date': int(trade_date),
                    'open': float(row['今开']),
                    'high': float(row['最高']),
                    'low': float(row['最低']),
                    'close': float(row['最新价']),
                    'pre_close': float(row['昨收']),
                    'vol': float(row['成交量']),
                    'amount': float(row['成交额']),
                    'source': 'ak'
                }
                
                # 计算涨跌停价
                pre_close = record['pre_close']
                if ts_code.startswith(('688.', '300.')):  # 科创板/创业板
                    up_limit = round(pre_close * 1.2, 2)
                    down_limit = round(pre_close * 0.8, 2)
                else:  # 主板
                    up_limit = round(pre_close * 1.1, 2)
                    down_limit = round(pre_close * 0.9, 2)
                
                record['up_limit'] = up_limit
                record['down_limit'] = down_limit
                
                records.append(record)
            
            # 批量保存
            if records:
                from pymongo import ReplaceOne
                operations = [ReplaceOne({'_id': r['_id']}, r, upsert=True) for r in records]
                result = collection.bulk_write(operations)
                saved = result.upserted_count + result.modified_count
                total_records += saved
                print(f"  ✅ 保存 {saved} 条记录")
            else:
                print("  ⚠️  没有有效记录")
        
        except Exception as e:
            print(f"  ❌ 错误: {e}")
        
        # 频率控制
        if i < len(trade_dates):
            time.sleep(1)
    
    # 创建索引
    print()
    print("🔧 创建数据库索引...")
    try:
        collection.create_index([('ts_code', 1), ('trade_date', -1)])
        collection.create_index([('trade_date', -1)])
        print("✅ 索引创建完成")
    except Exception as e:
        print(f"❌ 创建索引失败: {e}")
    
    # 检查结果
    print()
    print("=" * 60)
    print("📊 下载完成!")
    print(f"总记录数: {total_records}")
    print(f"数据库总记录: {collection.count_documents({})}")
    
    # 验证数据
    print()
    print("🔍 验证数据质量...")
    sample = list(collection.find().limit(5))
    print(f"样本数据 ({len(sample)} 条):")
    for record in sample:
        print(f"  {record.get('ts_code')} - {record.get('trade_date')}: O:{record.get('open')} C:{record.get('close')}")
    
    client.close()

if __name__ == "__main__":
    main()