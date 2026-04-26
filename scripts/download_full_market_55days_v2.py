#!/usr/bin/env python3
"""
下载全市场A股日线数据（AKShare）- V2优化版
【优化点】
1. 使用项目统一的 mongo_manager，移除localhost硬编码
2. 分批处理 + gc.collect() 内存释放，防止OOM
3. AKShare请求间隔 + 指数退避重试机制
4. 断点续传支持（记录失败股票，支持重试失败列表）
5. 异步化IO，提高下载效率
"""
import asyncio
import sys
import gc
import time
import json
from datetime import datetime
from pathlib import Path

import akshare as ak
from tqdm import tqdm

sys.path.insert(0, '/root/.openclaw/workspace/StockAgent')
sys.path.insert(0, '/root/.openclaw/workspace/StockAgent/AgentServer')

from core.managers import mongo_manager

# ==================== 配置区 ====================
START_DATE = "20260105"
END_DATE = "20260320"
COLLECTION_NAME = "stock_daily_ak_full"
BATCH_SIZE = 100              # 每处理N只释放一次内存
RETRY_COUNT = 3               # 单只股票最大重试次数
REQUEST_INTERVAL = 0.1        # 正常请求间隔（秒）
RETRY_BACKOFF_BASE = 1        # 重试退避基数（秒）
FAILED_LIST_FILE = "/tmp/failed_stocks.json"  # 失败股票列表

async def download_one_stock(code, name, collection, retry_count=0):
    """
    下载单只股票数据
    返回: (是否成功, 插入记录数, 错误信息)
    """
    ts_code = code + ".SH" if code.startswith('6') else code + ".SZ"
    
    try:
        # 下载日线数据（不复权，避免调整导致数据不一致）
        df = ak.stock_zh_a_hist(
            symbol=code,
            period="daily",
            start_date=START_DATE,
            end_date=END_DATE,
            adjust=""
        )
        
        if df is None or df.empty:
            return (False, 0, "empty data")
        
        # 转换数据格式
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
                "_id": f"{ts_code}_{int(str(row['日期']).replace('-', ''))}"
            }
            records.append(record)
        
        if not records:
            return (False, 0, "no valid records")
        
        # 批量插入（先删后插，防止重复）
        await collection.delete_many({
            "ts_code": ts_code,
            "trade_date": {"$gte": int(START_DATE), "$lte": int(END_DATE)}
        })
        await collection.insert_many(records)
        
        return (True, len(records), None)
        
    except Exception as e:
        err_msg = str(e)[:100]
        
        # 重试逻辑：指数退避
        if retry_count < RETRY_COUNT:
            wait_time = RETRY_BACKOFF_BASE * (2 ** retry_count)
            time.sleep(wait_time)
            return await download_one_stock(code, name, collection, retry_count + 1)
        
        return (False, 0, err_msg)


async def download_full_market():
    print("="*80)
    print("🚀 全市场A股日线数据下载（AKShare V2优化版）")
    print("="*80)
    print(f"下载区间: {START_DATE} ~ {END_DATE}")
    print(f"保存集合: {COLLECTION_NAME}")
    print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*80)
    
    # 1. 初始化MongoDB（项目统一配置，无localhost硬编码）
    print("\n📦 初始化MongoDB连接...")
    await mongo_manager.initialize()
    collection = mongo_manager.db[COLLECTION_NAME]
    
    # 创建索引（如果不存在）
    await collection.create_index([("ts_code", 1), ("trade_date", -1)], unique=True)
    await collection.create_index([("trade_date", -1)])
    print("✅ MongoDB初始化完成")
    
    # 2. 获取所有A股股票列表
    print("\n📥 获取A股股票列表...")
    try:
        stock_info = ak.stock_info_a_code_name()
        stock_codes = stock_info['code'].tolist()
        stock_names = stock_info['name'].tolist()
        total_stocks = len(stock_codes)
        print(f"✅ 获取到 {total_stocks} 只A股股票")
    except Exception as e:
        print(f"❌ 获取股票列表失败: {e}")
        # 降级方案：使用备用股票列表
        stock_codes = ['000001', '000002', '600519', '300750', '601318']
        stock_names = ['平安银行', '万科A', '贵州茅台', '宁德时代', '中国平安']
        total_stocks = len(stock_codes)
        print(f"⚠️  使用降级方案: {total_stocks}只股票")
    
    # 3. 查询已经下载完成的股票（断点续传）
    downloaded_stocks = await collection.distinct("ts_code")
    print(f"📊 已下载完成: {len(downloaded_stocks)}只，剩余: {total_stocks - len(downloaded_stocks)}只")
    
    # 4. 加载之前失败的股票列表（如果存在）
    failed_stocks = []
    if Path(FAILED_LIST_FILE).exists():
        try:
            with open(FAILED_LIST_FILE, 'r') as f:
                failed_data = json.load(f)
                failed_stocks = failed_data.get("failed_stocks", [])
                print(f"📋 加载上次失败的股票列表: {len(failed_stocks)}只")
        except Exception:
            pass
    
    # 5. 逐只下载日线数据
    success_count = 0
    fail_count = 0
    total_inserted = 0
    pbar = tqdm(total=total_stocks, desc="下载进度")
    
    current_failed = []
    
    for i in range(total_stocks):
        code = stock_codes[i]
        name = stock_names[i]
        ts_code = code + ".SH" if code.startswith('6') else code + ".SZ"
        
        # 跳过已经下载的
        if ts_code in downloaded_stocks:
            pbar.update(1)
            success_count += 1
            continue
        
        success, inserted, err_msg = await download_one_stock(code, name, collection)
        
        if success:
            success_count += 1
            total_inserted += inserted
        else:
            fail_count += 1
            current_failed.append({
                "code": code,
                "name": name,
                "ts_code": ts_code,
                "error": err_msg,
                "time": datetime.now().isoformat()
            })
            pbar.set_postfix(failed=fail_count)
        
        # 进度条更新
        pbar.update(1)
        
        # 请求间隔，避免AKShare限流
        time.sleep(REQUEST_INTERVAL)
        
        # 分批释放内存（防止OOM）
        if (i + 1) % BATCH_SIZE == 0:
            gc.collect()
            pbar.set_description(f"下载进度 (已释放内存)")
        
        # 定期保存失败列表
        if (i + 1) % 500 == 0 and current_failed:
            with open(FAILED_LIST_FILE, 'w') as f:
                json.dump({"failed_stocks": current_failed}, f, ensure_ascii=False, indent=2)
    
    pbar.close()
    
    # 保存最终失败列表
    if current_failed:
        with open(FAILED_LIST_FILE, 'w') as f:
            json.dump({"failed_stocks": current_failed}, f, ensure_ascii=False, indent=2)
        print(f"\n💾 失败股票列表已保存到: {FAILED_LIST_FILE}")
        print(f"   可单独重试: python {sys.argv[0]} --retry-failed")
    
    # 6. 统计结果
    total_records = await collection.count_documents({})
    dates = sorted(await collection.distinct("trade_date"))
    stocks_count = len(await collection.distinct("ts_code"))
    
    print("\n" + "="*80)
    print("✅ 下载完成！")
    print("="*80)
    print(f"总股票数: {total_stocks}")
    print(f"下载成功: {success_count}只")
    print(f"下载失败: {fail_count}只")
    print(f"总记录数: {total_records}条")
    print(f"覆盖交易日: {len(dates)}天")
    print(f"覆盖股票: {stocks_count}只")
    print(f"完成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 测试数据
    if dates:
        test_date = dates[-1]
        day_count = await collection.count_documents({"trade_date": test_date})
        limit_up_count = await collection.count_documents({
            "trade_date": test_date,
            "$expr": {"$gte": ["$close", {"$multiply": ["$pre_close", 0.995]}]}
        })
        print(f"\n📊 最新交易日 {test_date} 统计:")
        print(f"  股票数量: {day_count}只")
        print(f"  涨停数量: {limit_up_count}只")


async def retry_failed():
    """重试之前失败的股票"""
    if not Path(FAILED_LIST_FILE).exists():
        print(f"❌ 失败列表文件不存在: {FAILED_LIST_FILE}")
        return
    
    print(f"\n🔄 重试失败的股票...")
    
    await mongo_manager.initialize()
    collection = mongo_manager.db[COLLECTION_NAME]
    
    with open(FAILED_LIST_FILE, 'r') as f:
        failed_data = json.load(f)
    
    failed_stocks = failed_data.get("failed_stocks", [])
    print(f"📋 共 {len(failed_stocks)} 只股票需要重试")
    
    success_count = 0
    for stock in tqdm(failed_stocks, desc="重试进度"):
        code = stock["code"]
        name = stock["name"]
        
        success, inserted, err_msg = await download_one_stock(code, name, collection)
        if success:
            success_count += 1
    
    print(f"\n✅ 重试完成: 成功 {success_count}/{len(failed_stocks)}")
    
    # 如果全部成功，删除失败文件
    if success_count == len(failed_stocks):
        Path(FAILED_LIST_FILE).unlink()
        print("🗑️  失败列表已删除")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--retry-failed":
        asyncio.run(retry_failed())
    else:
        asyncio.run(download_full_market())
