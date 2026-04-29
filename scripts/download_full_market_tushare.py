#!/usr/bin/env python3
"""
下载全市场A股日线数据（Tushare官方API）- 黄金方案
【数据源】Tushare Pro API，老板提供的token和代理地址
【优化】分批 + GC + 重试 + 断点续传
"""
import asyncio
import os
import sys
import gc
import time
import json
import random
from datetime import datetime
from pathlib import Path

import tushare as ts
from tqdm import tqdm

sys.path.insert(0, '/root/.openclaw/workspace/StockAgent')
sys.path.insert(0, '/root/.openclaw/workspace/StockAgent/AgentServer')

from core.managers import mongo_manager

# ==================== 配置区（严格按照老板要求）====================
TOKEN = os.getenv("TUSHARE_TOKEN", "")
if not TOKEN:
    raise ValueError("请设置环境变量 TUSHARE_TOKEN")
API_URL = os.getenv("TUSHARE_HTTP_URL", "https://api.tushare.pro")

START_DATE = "20260105"
END_DATE = "20260320"
COLLECTION_NAME = "stock_daily_ak_full"

# 反爬策略（老板要求）
REQUEST_INTERVAL_MIN = 0.5  # 最小请求间隔秒
REQUEST_INTERVAL_MAX = 1.0  # 最大请求间隔秒
BATCH_SIZE = 100            # 每N只释放一次内存
BATCH_SLEEP = 10            # 每N只休眠秒（避免限流）
RETRY_COUNT = 3             # 单只股票最大重试次数
FAILED_LIST_FILE = "/tmp/failed_stocks_tushare.json"

# ==================== Tushare初始化（严格按照老板要求）====================
ts.set_token(TOKEN)
pro = ts.pro_api(TOKEN)
pro._DataApi__token = TOKEN       # 必须有
pro._DataApi__http_url = API_URL  # 必须有


def get_stock_list():
    """获取全市场A股股票列表"""
    try:
        # 获取上市股票列表
        stock_basic = pro.stock_basic(exchange='', list_status='L', fields='ts_code,symbol,name,area,industry,list_date')
        codes = stock_basic['ts_code'].tolist()
        print(f"✅ 获取到 {len(codes)} 只上市A股")
        return codes
    except Exception as e:
        print(f"❌ 获取股票列表失败: {e}")
        # 降级方案：生成主要指数成分股
        codes = []
        # 上证50 + 沪深300 + 中证500 大致范围
        for i in range(600000, 604000):  # 上证
            codes.append(f"{i:06d}.SH")
        for i in range(1, 3000):       # 深证
            codes.append(f"{i:06d}.SZ")
        for i in range(300001, 301500): # 创业板
            codes.append(f"{i:06d}.SZ")
        return codes[:5510]


async def download_one_stock(ts_code, collection, retry_count=0):
    """
    下载单只股票数据（Tushare API）
    返回: (是否成功, 插入记录数, 错误信息)
    """
    try:
        # 调用Tushare日线API
        df = pro.daily(ts_code=ts_code, start_date=START_DATE, end_date=END_DATE)
        
        if df is None or df.empty:
            return (False, 0, "空数据")
        
        # 转换为MongoDB格式
        records = []
        for _, row in df.iterrows():
            record = {
                "ts_code": row['ts_code'],
                "trade_date": int(row['trade_date']),
                "open": float(row['open']),
                "high": float(row['high']),
                "low": float(row['low']),
                "close": float(row['close']),
                "vol": float(row['vol']),      # 成交量（手）
                "amount": float(row['amount']), # 成交额（千元）
                "pct_chg": float(row['pct_chg']), # 涨跌幅
            }
            records.append(record)
        
        if not records:
            return (False, 0, "目标区间无数据")
        
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
            wait_time = (2 ** retry_count) + random.uniform(0, 1)
            time.sleep(wait_time)
            return await download_one_stock(ts_code, collection, retry_count + 1)
        
        return (False, 0, err_msg)


async def download_full_market():
    print("="*80)
    print("🚀 全市场A股日线数据下载（Tushare官方API - 老板黄金方案）")
    print("="*80)
    print(f"Token: {TOKEN[:10]}...{TOKEN[-4:]}")
    print(f"API代理: {API_URL}")
    print(f"下载区间: {START_DATE} ~ {END_DATE}")
    print(f"保存集合: {COLLECTION_NAME}")
    print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"反爬策略: 间隔 {REQUEST_INTERVAL_MIN}-{REQUEST_INTERVAL_MAX}秒 / 每{BATCH_SIZE}只休眠{BATCH_SLEEP}秒")
    print("="*80)
    
    # 1. 初始化MongoDB
    print("\n1️⃣  初始化MongoDB连接...")
    await mongo_manager.initialize()
    collection = mongo_manager.db[COLLECTION_NAME]
    
    # 创建索引（如果不存在）
    await collection.create_index([("ts_code", 1), ("trade_date", -1)], unique=True)
    await collection.create_index([("trade_date", -1)])
    print("   ✅ MongoDB初始化完成")
    
    # 2. 获取股票列表
    print("\n2️⃣  获取股票列表...")
    stock_codes = get_stock_list()
    total_stocks = len(stock_codes)
    print(f"   ✅ 共 {total_stocks} 只A股股票")
    
    # 3. 查询已经下载完成的股票（断点续传）
    downloaded = await collection.distinct("ts_code")
    downloaded_set = set(downloaded)
    remaining = [code for code in stock_codes if code not in downloaded_set]
    print(f"\n📊 已下载完成: {len(downloaded)}只，剩余: {len(remaining)}只")
    
    # 4. 加载之前失败的股票列表
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
    print(f"\n3️⃣  开始下载，每{BATCH_SIZE}只释放一次内存并休眠{BATCH_SLEEP}秒...")
    success_count = 0
    fail_count = 0
    total_inserted = 0
    pbar = tqdm(total=len(remaining), desc="下载进度")
    
    current_failed = []
    
    for i, code in enumerate(remaining):
        success, inserted, err_msg = await download_one_stock(code, collection)
        
        if success:
            success_count += 1
            total_inserted += inserted
        else:
            fail_count += 1
            current_failed.append({
                "ts_code": code,
                "error": err_msg,
                "time": datetime.now().isoformat()
            })
            pbar.set_postfix(failed=fail_count)
        
        # 进度条更新
        pbar.update(1)
        
        # 随机间隔，避免限流
        time.sleep(random.uniform(REQUEST_INTERVAL_MIN, REQUEST_INTERVAL_MAX))
        
        # 每BATCH_SIZE只：释放内存 + 休眠
        if (i + 1) % BATCH_SIZE == 0:
            gc.collect()
            pbar.set_description(f"下载进度 (GC已执行，休眠{BATCH_SLEEP}秒)")
            time.sleep(BATCH_SLEEP)
            pbar.set_description("下载进度")
        
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
    print(f"本轮下载: 成功{success_count}只，失败{fail_count}只")
    print(f"总股票数: {stocks_count} 只")
    print(f"总记录数: {total_records:,} 条")
    print(f"覆盖交易日: {len(dates)} 天")
    if dates:
        print(f"日期范围: {dates[0]} ~ {dates[-1]}")
    print(f"完成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*80)


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
        code = stock.get("ts_code")
        if not code:
            continue
        success, inserted, err_msg = await download_one_stock(code, collection)
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
