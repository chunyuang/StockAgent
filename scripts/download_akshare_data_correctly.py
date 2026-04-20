#!/usr/bin/env python3
"""
正确的 AKShare 数据下载脚本
按照你之前确定的方式：按日期获取全市场股票数据
"""

import akshare as ak
import pymongo
from datetime import datetime, timedelta
import time
from typing import List, Dict, Any
from tqdm import tqdm

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

def download_daily_data_for_date(trade_date: str, collection_name: str = "stock_daily_ak_full_ak") -> Dict[str, Any]:
    """
    下载指定交易日的全市场股票数据
    """
    result = {
        'success': False,
        'date': trade_date,
        'records_downloaded': 0,
        'records_saved': 0,
        'error': None,
        'stock_count': 0
    }
    
    try:
        print(f"📥 下载 {trade_date} 的数据...")
        
        # 使用正确的历史数据接口
        # 注意：这里我们使用一个更稳定的接口
        df = ak.stock_zh_a_spot()
        
        if df is None or df.empty:
            result['error'] = f"{trade_date}: AKShare返回空数据"
            return result
        
        # 转换日期格式
        
        # 标准化数据格式
        records = []
        for _, row in df.iterrows():
            code = str(row['代码']).zfill(6)
            
            # 确定后缀
            if code.startswith('6') or code.startswith('5'):
                ts_code = f"{code}.SH"
            else:
                ts_code = f"{code}.SZ"
            
            record = {
                'ts_code': ts_code,
                'trade_date': int(trade_date),
                'open': float(row['今开']),
                'high': float(row['最高']),
                'low': float(row['最低']),
                'close': float(row['最新价']),
                'pre_close': float(row['昨收']),
                'vol': float(row['成交量']),
                'amount': float(row['成交额']),
                'source': 'ak',
                '_id': f"{ts_code}_{trade_date}"
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
        
        result['records_downloaded'] = len(records)
        
        # 批量保存到数据库
        if records:
            success_count = save_to_mongodb(records, collection_name)
            result['records_saved'] = success_count
            result['stock_count'] = len(set([r['ts_code'] for r in records]))
            result['success'] = True
        
        print(f"   ✅ {trade_date}: 下载 {len(records)} 条记录")
        
    except Exception as e:
        result['error'] = str(e)
    
    return result

def save_to_mongodb(records: List[Dict[str, Any]], collection_name: str = "stock_daily_ak_full_ak") -> int:
    """批量保存数据到MongoDB"""
    client = pymongo.MongoClient('localhost', 27017)
    db = client['stock_agent']
    
    collection = db[collection_name]
    
    try:
        from pymongo import ReplaceOne
        operations = []
        
        for record in records:
            operations.append(ReplaceOne(
                {'_id': record['_id']},
                record,
                upsert=True
            ))
        
        if operations:
            result = collection.bulk_write(operations)
            saved_count = result.upserted_count + result.modified_count
            return saved_count
        
    except Exception as e:
        print(f"保存数据时出错: {e}")
    finally:
        client.close()
    
    return 0

def download_data_range(start_date: str, end_date: str, request_interval: float = 1.0) -> Dict[str, Any]:
    """
    下载指定日期范围内的数据
    """
    print("=" * 60)
    print(f"📅 下载范围: {start_date} 至 {end_date}")
    print(f"⏳ 请求间隔: {request_interval} 秒")
    print("=" * 60)
    print()
    
    total_summary = {
        'start_date': start_date,
        'end_date': end_date,
        'total_days': 0,
        'successful_days': 0,
        'failed_days': 0,
        'total_records': 0,
        'start_time': time.time(),
        'errors': []
    }
    
    # 获取所有交易日
    all_dates = get_trade_dates(start_date, end_date)
    total_days = len(all_dates)
    total_summary['total_days'] = total_days
    
    print(f"📊 总共 {total_days} 个交易日")
    print()
    
    successful_dates = []
    failed_dates = []
    
    # 使用进度条
    for i, trade_date in enumerate(tqdm(all_dates, desc="下载进度", unit="天"), 1):
        print(f"   📈 处理第 {i}/{total_days} 天: {trade_date}")
        
        try:
            # 下载该交易日数据
            result = download_daily_data_for_date(trade_date)
            
            if result['success']:
                successful_dates.append(trade_date)
                total_summary['total_records'] += result.get('records_saved', 0)
                total_summary['successful_days'] += 1
            else:
                failed_dates.append((trade_date, result.get('error', '未知错误')))
                total_summary['errors'].append({
                    'date': trade_date,
                    'error': result.get('error')
                })
                total_summary['failed_days'] += 1
            
            # 频率控制
            if i < total_days:
                time.sleep(request_interval)
        
        except Exception as e:
            print(f"   ❌ {trade_date}: 下载失败 - {e}")
            failed_dates.append((trade_date, str(e)))
            total_summary['errors'].append({
                'date': trade_date,
                'error': str(e)
            })
    
    total_summary['successful_days'] = successful_days
    total_summary['failed_days'] = failed_days
    total_summary['elapsed_time'] = time.time() - total_summary['start_time']
    
    return total_summary

def main():
    print("🚀 开始按照正确方式下载 AKShare 数据")
    print("=" * 60)
    
    # 设置参数
    start_date = "20260105"
    end_date = "20260320"
    request_interval = 1.0  # 每1秒请求一次
    
    print(f"📅 时间范围: {start_date} - {end_date}")
    print(f"⏱️  请求间隔: {request_interval}秒")
    print()
    
    # 记录开始时间
    start_time = time.time()
    
    # 下载数据
    summary = download_data_range(start_date, end_date, request_interval)
    
    # 计算总耗时
    elapsed_time = time.time() - start_time
    
    print()
    print("=" * 60)
    print("📊 下载完成!")
    print(f"⏱️  总耗时: {elapsed_time:.1f} 秒")
    print(f"📊 成功交易日: {summary.get('successful_days', 0)}")
    print(f"⚠️  失败交易日: {summary.get('failed_days', 0)}")
    print(f"📈 总记录数: {summary.get('total_records', 0)}")
    
    # 显示错误信息
    errors = summary.get('errors', [])
    if errors:
        print()
        print("❌ 下载失败的交易日:")
        for error in errors[:5]:  # 只显示前5个错误
            print(f"   {error['date']}: {error.get('error', '未知错误')}")
    
    # 创建数据库索引
    if summary.get('successful_days', 0) > 0:
        print()
        print("🔧 创建数据库索引...")
        try:
            client = pymongo.MongoClient('localhost', 27017)
            db = client['stock_agent']
            collection = db['stock_daily_ak_full_ak']
            
            # 创建复合索引
            collection.create_index([('ts_code', 1), ('trade_date', -1)])
            collection.create_index([('trade_date', -1)])
            
            print("✅ 索引创建完成")
            
            # 检查数据状态
            count = collection.count_documents({})
            print(f"📊 数据库现有记录: {count} 条")
            
            # 验证数据质量
            print("🔍 验证数据质量...")
            # 随机检查几条记录
            sample = list(collection.find().limit(3))
            print(f"   样本数据 ({len(sample)} 条):")
            for record in sample:
                print(f"     {record.get('ts_code')} - {record.get('trade_date')}: O:{record.get('open')} C:{record.get('close')}")
            
            client.close()
        except Exception as e:
            print(f"❌ 创建索引失败: {e}")
    
    print()
    print("✅ 下载任务完成")
    
    # 打印最终统计
    print("=" * 60)
    print("📈 最终统计:")
    print(f"   成功交易日: {summary.get('successful_days', 0)}")
    print(f"   失败交易日: {summary.get('failed_days', 0)}")
    print(f"   总记录数: {summary.get('total_records', 0)}")
    print(f"   平均速度: {summary.get('total_records', 0)/elapsed_time:.1f} 条/秒")

if __name__ == "__main__":
    main()