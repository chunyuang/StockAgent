#!/usr/bin/env python3
"""
修复版 AKShare 数据下载脚本
正确使用历史数据接口，避免重复数据问题
"""

import akshare as ak
import pymongo
from datetime import datetime, timedelta
import time
from typing import List, Dict, Any

def get_trade_dates(start_date: str, end_date: str) -> List[str]:
    """获取交易日列表"""
    dates = []
    current = datetime.strptime(start_date, "%Y%m%d")
    end = datetime.strptime(end_date, "%Y%m%d")
    
    while current <= end:
        if current.weekday() < 5:  # 周一到周五
            dates.append(current.strftime("%Y%m%d"))
        current += timedelta(days=1)
    
    return dates

def get_stock_list() -> List[str]:
    """获取股票列表"""
    print("获取股票列表...")
    
    # 获取A股列表
    try:
        # 使用AKShare获取股票列表
        stock_info = ak.stock_info_a_code_name()
        if stock_info is None or stock_info.empty:
            print("⚠️ 无法获取股票列表，使用默认列表")
            return []
        
        # 转换为标准格式
        stocks = []
        for _, row in stock_info.iterrows():
            code = str(row['code'])
            if len(code) < 6:
                code = code.zfill(6)
            
            if code.startswith('6'):
                ts_code = f"{code}.SH"
            elif code.startswith('3') or code.startswith('0'):
                ts_code = f"{code}.SZ"
            else:
                continue
            
            stocks.append(ts_code)
        
        print(f"✅ 获取到 {len(stocks)} 只股票")
        return stocks[:100]  # 测试用，先取100只
        
    except Exception as e:
        print(f"❌ 获取股票列表失败: {e}")
        # 返回一些测试股票
        return ['000001.SZ', '000002.SZ', '600000.SH', '600036.SH', '300750.SZ']

def download_stock_history(ts_code: str, start_date: str, end_date: str) -> List[Dict[str, Any]]:
    """下载单只股票的历史数据"""
    try:
        # 提取股票代码（去掉后缀）
        code = ts_code.split('.')[0]
        
        print(f"  下载 {ts_code} 的历史数据...")
        
        # 使用正确的历史数据接口
        df = ak.stock_zh_a_hist(
            symbol=code,
            period="daily",
            start_date=start_date,
            end_date=end_date,
            adjust=""  # 不复权
        )
        
        if df is None or df.empty:
            print(f"  ⚠️  {ts_code} 没有数据")
            return []
        
        # 转换为标准格式
        records = []
        for _, row in df.iterrows():
            # 转换日期格式
            trade_date = row['日期'].replace('-', '')
            
            record = {
                'ts_code': ts_code,
                'trade_date': int(trade_date),  # 统一为int类型
                'open': float(row['开盘']),
                'high': float(row['最高']),
                'low': float(row['最低']),
                'close': float(row['收盘']),
                'pre_close': float(row['收盘'].shift(1) if _ > 0 else row['开盘']),  # 前收盘价
                'vol': float(row['成交量']),  # 成交量（手）
                'amount': float(row['成交额']),  # 成交额（元）
                'pct_chg': float(row['涨跌幅']),  # 涨跌幅（%）
                'change': float(row['涨跌额']),  # 涨跌额
                'amplitude': float(row['振幅']),  # 振幅（%）
                'turnover_rate': float(row['换手率']),  # 换手率（%）
                'source': 'ak',  # 明确标识数据源
                '_id': f"{ts_code}_{trade_date}"  # 唯一ID
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
        
        print(f"  ✅ {ts_code}: 下载到 {len(records)} 条记录")
        return records
        
    except Exception as e:
        print(f"  ❌ {ts_code} 下载失败: {e}")
        return []

def save_to_mongodb(records: List[Dict[str, Any]], collection_name: str = "stock_daily_ak_full_ak"):
    """保存数据到MongoDB"""
    if not records:
        return
    
    client = pymongo.MongoClient('localhost', 27017)
    db = client['stock_agent']
    
    # 使用指定集合
    collection = db[collection_name]
    
    # 批量插入
    try:
        from pymongo import ReplaceOne
        bulk_operations = []
        
        for record in records:
            bulk_operations.append(ReplaceOne(
                {'_id': record['_id']},
                record,
                upsert=True
            ))
        
        if bulk_operations:
            result = collection.bulk_write(bulk_operations)
            print(f"  📊 保存结果: 新增 {result.upserted_count}, 修改 {result.modified_count}")
    
    except Exception as e:
        print(f"  ❌ 保存失败: {e}")
    
    finally:
        client.close()

def validate_data(ts_code: str, collection_name: str = "stock_daily_ak_full_ak"):
    """验证数据是否正确"""
    client = pymongo.MongoClient('localhost', 27017)
    db = client['stock_agent']
    collection = db[collection_name]
    
    # 获取该股票的所有记录
    records = list(collection.find({'ts_code': ts_code}).sort('trade_date', 1))
    
    if not records:
        print(f"  ❌ {ts_code}: 没有找到数据")
        return False
    
    print(f"  🔍 {ts_code}: 验证 {len(records)} 条记录")
    
    # 检查数据是否正确（不应该所有记录都相同）
    first_record = records[0]
    all_same = True
    
    for i in range(1, min(5, len(records))):  # 检查前5条
        for key in ['open', 'high', 'low', 'close', 'vol', 'amount']:
            if first_record.get(key) != records[i].get(key):
                all_same = False
                break
    
    if all_same:
        print(f"  ❌ {ts_code}: 所有记录完全相同！数据有问题")
        return False
    else:
        print(f"  ✅ {ts_code}: 数据有正常变化")
        
        # 显示一些数据示例
        print("     示例数据:")
        for i in range(min(3, len(records))):
            r = records[i]
            print(f"       {r['trade_date']}: O:{r['open']} H:{r['high']} L:{r['low']} C:{r['close']}")
        
        return True

def main():
    """主函数"""
    print("=" * 60)
    print("修复版 AKShare 数据下载工具")
    print("=" * 60)
    
    # 参数设置
    start_date = "20260105"
    end_date = "20260320"
    collection_name = "stock_daily_ak_full_ak"  # 专门存储AKShare数据的集合
    
    print(f"时间范围: {start_date} - {end_date}")
    print(f"目标集合: {collection_name}")
    print()
    
    # 1. 获取股票列表
    stocks = get_stock_list()
    if not stocks:
        print("❌ 没有找到股票，退出")
        return
    
    # 限制测试数量
    test_stocks = stocks[:10]  # 先测试10只股票
    print(f"测试股票: {len(test_stocks)} 只")
    print()
    
    total_records = 0
    successful_stocks = 0
    
    # 2. 下载每只股票的历史数据
    for i, ts_code in enumerate(test_stocks, 1):
        print(f"[{i}/{len(test_stocks)}] 处理 {ts_code}")
        
        # 下载数据
        records = download_stock_history(ts_code, start_date, end_date)
        
        if records:
            # 保存到数据库
            save_to_mongodb(records, collection_name)
            
            # 验证数据
            if validate_data(ts_code, collection_name):
                successful_stocks += 1
            
            total_records += len(records)
        
        # 频率控制
        time.sleep(1)  # 避免请求过快
    
    print()
    print("=" * 60)
    print("下载完成!")
    print(f"成功股票: {successful_stocks}/{len(test_stocks)}")
    print(f"总记录数: {total_records}")
    
    # 3. 创建索引
    if successful_stocks > 0:
        print()
        print("创建索引...")
        client = pymongo.MongoClient('localhost', 27017)
        db = client['stock_agent']
        collection = db[collection_name]
        
        # 创建复合索引
        collection.create_index([('ts_code', 1), ('trade_date', -1)])
        collection.create_index([('trade_date', -1)])
        
        print("✅ 索引创建完成")
        client.close()

if __name__ == "__main__":
    main()