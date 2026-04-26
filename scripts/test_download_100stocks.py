#!/usr/bin/env python3
"""
小规模测试：下载100只股票，验证脚本正确性
"""
import asyncio
import sys
import time
from datetime import datetime

sys.path.insert(0, '/root/.openclaw/workspace/StockAgent')
sys.path.insert(0, '/root/.openclaw/workspace/StockAgent/AgentServer')

import akshare as ak
from core.managers import mongo_manager

COLLECTION_NAME = "stock_daily_ak_full_test"
START_DATE = "20260301"
END_DATE = "20260320"
TEST_COUNT = 100

async def test_download():
    print("="*80)
    print("🧪 小规模测试：前100只股票下载验证")
    print("="*80)
    start_time = time.time()
    
    # 1. 测试MongoDB连接
    print("\n1️⃣  测试MongoDB连接...")
    try:
        await mongo_manager.initialize()
        collection = mongo_manager.db[COLLECTION_NAME]
        await collection.create_index([("ts_code", 1), ("trade_date", -1)], unique=True)
        print("   ✅ MongoDB连接成功")
    except Exception as e:
        print(f"   ❌ MongoDB连接失败: {e}")
        return False
    
    # 2. 测试获取股票列表
    print("\n2️⃣  测试获取股票列表...")
    try:
        stock_info = ak.stock_info_a_code_name()
        stock_codes = stock_info['code'].tolist()[:TEST_COUNT]
        stock_names = stock_info['name'].tolist()[:TEST_COUNT]
        print(f"   ✅ 获取到前{TEST_COUNT}只股票列表")
    except Exception as e:
        print(f"   ❌ 获取股票列表失败: {e}")
        return False
    
    # 3. 测试下载
    print(f"\n3️⃣  开始下载 {TEST_COUNT} 只股票...")
    success_count = 0
    fail_count = 0
    total_records = 0
    
    for i in range(TEST_COUNT):
        code = stock_codes[i]
        name = stock_names[i]
        ts_code = code + ".SH" if code.startswith('6') else code + ".SZ"
        
        try:
            df = ak.stock_zh_a_hist(
                symbol=code,
                period="daily",
                start_date=START_DATE,
                end_date=END_DATE,
                adjust=""
            )
            
            if df is None or df.empty:
                fail_count += 1
                continue
            
            records = []
            for _, row in df.iterrows():
                record = {
                    "ts_code": ts_code,
                    "trade_date": int(str(row['日期']).replace('-', '')),
                    "open": float(row['开盘']),
                    "high": float(row['最高']),
                    "low": float(row['最低']),
                    "close": float(row['收盘']),
                    "vol": float(row['成交量']),
                    "amount": float(row['成交额']),
                    "pct_chg": float(row['涨跌幅']),
                }
                records.append(record)
            
            if records:
                await collection.delete_many({"ts_code": ts_code})
                await collection.insert_many(records)
                total_records += len(records)
            
            success_count += 1
            
            # 进度反馈
            if (i + 1) % 20 == 0:
                print(f"   进度: {i+1}/{TEST_COUNT} 成功={success_count} 失败={fail_count}")
            
        except Exception as e:
            fail_count += 1
            continue
        
        # 控制请求频率
        time.sleep(0.05)
    
    # 4. 验证结果
    print("\n4️⃣  验证结果...")
    db_total = await collection.count_documents({})
    db_stocks = len(await collection.distinct("ts_code"))
    db_dates = len(await collection.distinct("trade_date"))
    
    elapsed = time.time() - start_time
    
    print("\n" + "="*80)
    print("📊 测试结果汇总")
    print("="*80)
    print(f"  总耗时: {elapsed:.1f}秒")
    print(f"  测试股票: {TEST_COUNT}只")
    print(f"  下载成功: {success_count}只")
    print(f"  下载失败: {fail_count}只")
    print(f"  数据库总记录: {db_total}条")
    print(f"  数据库股票数: {db_stocks}只")
    print(f"  数据库交易日: {db_dates}天")
    print(f"  平均每只: {total_records / TEST_COUNT:.1f}条/只")
    print("="*80)
    
    # 清理测试数据
    await collection.drop()
    
    if fail_count == 0 and success_count == TEST_COUNT:
        print("✅ 测试全部通过！")
        return True
    else:
        print("⚠️  部分失败，请检查AKShare连接")
        return success_count > 80  # 80%以上成功即认为可接受

if __name__ == "__main__":
    result = asyncio.run(test_download())
    sys.exit(0 if result else 1)
