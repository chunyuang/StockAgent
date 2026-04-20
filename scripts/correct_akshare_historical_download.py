#!/usr/bin/env python3
"""
正确的 AKShare 历史数据下载脚本
使用 ak.stock_zh_a_hist() 接口获取历史数据
"""

import akshare as ak
import pymongo
import time
from tqdm import tqdm

def get_stock_list():
    """获取股票列表"""
    print("📋 获取股票列表...")
    try:
        stock_list = ak.stock_info_a_code_name()
        if stock_list is None or stock_list.empty:
            print("⚠️  股票列表为空，使用默认列表")
            # 使用常见股票代码
            return ['000001', '000002', '000858', '002415', '300750']
        
        stock_codes = stock_list['code'].tolist()
        print(f"✅ 获取到 {len(stock_codes)} 只股票")
        return stock_codes[:100]  # 先测试前100只股票
    
    except Exception as e:
        print(f"❌ 获取股票列表失败: {e}")
        # 使用测试股票列表
        return ['000001', '000002', '000858']

def download_stock_history(stock_code, start_date, end_date):
    """下载单只股票的历史数据"""
    try:
        # 使用正确的历史数据接口
        df = ak.stock_zh_a_hist(
            symbol=stock_code,
            period="daily",
            start_date=start_date,
            end_date=end_date,
            adjust=""
        )
        
        if df is None or df.empty:
            return None
        
        return df
    
    except Exception as e:
        print(f"  ❌ {stock_code} 下载失败: {e}")
        return None

def save_to_mongodb(stock_code, df, collection):
    """保存股票历史数据到MongoDB"""
    if df is None or df.empty:
        return 0
    
    records = []
    
    for _, row in df.iterrows():
        # 确定后缀
        if stock_code.startswith('6') or stock_code.startswith('5'):
            ts_code = f"{stock_code}.SH"
        else:
            ts_code = f"{stock_code}.SZ"
        
        # 转换日期格式
        trade_date_str = str(row['日期']).replace('-', '')
        try:
            trade_date = int(trade_date_str)
        except:
            continue
        
        # 创建记录
        record = {
            '_id': f"{ts_code}_{trade_date}",
            'ts_code': ts_code,
            'trade_date': trade_date,
            'open': float(row['开盘']),
            'high': float(row['最高']),
            'low': float(row['最低']),
            'close': float(row['收盘']),
            'vol': float(row['成交量']),
            'amount': float(row['成交额']),
            'source': 'ak_historical'
        }
        
        # 计算涨跌停价
        pre_close = float(row.get('昨收', row['收盘']))  # 如果没有昨收盘价，使用收盘价
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
        return result.upserted_count + result.modified_count
    
    return 0

def main():
    print("🚀 开始下载 AKShare 历史数据 (正确版本)")
    print("=" * 60)
    
    # 设置参数
    start_date = "20260105"
    end_date = "20260320"
    
    print(f"📅 时间范围: {start_date} - {end_date}")
    print()
    
    # 连接数据库
    client = pymongo.MongoClient('localhost', 27017)
    db = client['stock_agent']
    
    # 清空现有错误数据
    if 'stock_daily_ak_full_ak' in db.list_collection_names():
        print("🗑️  清空现有错误数据...")
        db['stock_daily_ak_full_ak'].delete_many({})
    
    collection = db['stock_daily_ak_full_ak']
    
    # 获取股票列表
    stock_codes = get_stock_list()
    print(f"📊 将下载 {len(stock_codes)} 只股票的历史数据")
    print()
    
    total_records = 0
    successful_stocks = 0
    failed_stocks = 0
    
    # 下载每只股票的历史数据
    for i, stock_code in enumerate(tqdm(stock_codes, desc="下载进度", unit="只"), 1):
        print(f"[{i}/{len(stock_codes)}] 下载 {stock_code}...")
        
        try:
            # 下载历史数据
            df = download_stock_history(stock_code, start_date, end_date)
            
            if df is None or df.empty:
                print("  ⚠️  没有数据")
                failed_stocks += 1
                continue
            
            # 保存到数据库
            saved_count = save_to_mongodb(stock_code, df, collection)
            
            if saved_count > 0:
                total_records += saved_count
                successful_stocks += 1
                print(f"  ✅ 保存 {saved_count} 条记录")
                
                # 显示数据示例
                if i <= 3:  # 前3只股票显示数据详情
                    print(f"    数据示例 ({len(df)} 个交易日):")
                    sample_dates = list(df['日期'].head(3))
                    for date in sample_dates:
                        row = df[df['日期'] == date].iloc[0]
                        print(f"      {date}: O:{row['开盘']} C:{row['收盘']} Vol:{row['成交量']}")
            
            else:
                failed_stocks += 1
                print("  ⚠️  保存失败")
        
        except Exception as e:
            print(f"  ❌ 错误: {e}")
            failed_stocks += 1
        
        # 频率控制 (避免触发API限制)
        if i < len(stock_codes):
            time.sleep(0.5)  # 每0.5秒下载一只股票
    
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
    print(f"成功股票数: {successful_stocks}/{len(stock_codes)}")
    print(f"失败股票数: {failed_stocks}/{len(stock_codes)}")
    print(f"总记录数: {total_records}")
    print(f"数据库总记录: {collection.count_documents({})}")
    
    # 验证数据质量
    print()
    print("🔍 验证数据质量...")
    if total_records > 0:
        # 随机检查一只股票
        sample_stocks = list(collection.distinct('ts_code', limit=1))
        if sample_stocks:
            stock = sample_stocks[0]
            records = list(collection.find({'ts_code': stock}).sort('trade_date', 1))
            
            if len(records) >= 2:
                print(f"测试股票: {stock}")
                print(f"记录数: {len(records)}")
                
                # 检查数据是否有变化
                first = records[0]
                second = records[1]
                
                if first['open'] != second['open'] or first['close'] != second['close']:
                    print("✅ 数据有正常变化")
                    print(f"  {first['trade_date']}: O:{first['open']} C:{first['close']}")
                    print(f"  {second['trade_date']}: O:{second['open']} C:{second['close']}")
                else:
                    print("❌ 数据没有变化")
    
    client.close()
    
    print()
    print("=" * 60)
    if successful_stocks > 0 and total_records > 0:
        print("✅ 历史数据下载成功，可以开始回测")
    else:
        print("❌ 下载失败，需要检查问题")

if __name__ == "__main__":
    main()