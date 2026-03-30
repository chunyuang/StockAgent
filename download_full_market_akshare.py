#!/usr/bin/env python3
"""
下载全市场A股日线数据（AKShare）
包含所有股票的开盘/最高/最低/收盘/成交量/成交额/涨停价/跌停价
单位正确：成交额转换为万元，成交量转换为手
"""
import asyncio
import sys
import akshare as ak
import pandas as pd
from tqdm import tqdm
from datetime import datetime

sys.path.insert(0, '/root/.openclaw/workspace/StockAgent')
sys.path.insert(0, '/root/.openclaw/workspace/StockAgent/AgentServer')

from core.managers import mongo_manager

# 下载日期范围
START_DATE = "20260105"
END_DATE = "20260320"
COLLECTION_NAME = "stock_daily_ak_full"

async def download_full_market():
    print("="*80)
    print("🚀 全市场A股日线数据下载（AKShare）")
    print("="*80)
    print(f"下载区间: {START_DATE} ~ {END_DATE}")
    print(f"保存集合: {COLLECTION_NAME}")
    print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*80)
    
    # 初始化MongoDB
    await mongo_manager.initialize()
    collection = mongo_manager.db[COLLECTION_NAME]
    
    # 创建索引
    await collection.create_index([("ts_code", 1), ("trade_date", -1)], unique=True)
    await collection.create_index([("trade_date", -1)])
    
    # 1. 获取所有A股股票列表
    print("\n📥 获取A股股票列表...")
    stock_info = ak.stock_info_a_code_name()
    total_stocks = len(stock_info)
    print(f"✅ 获取到 {total_stocks} 只A股股票")
    
    # 2. 查询已经下载完成的股票
    downloaded_stocks = await collection.distinct("ts_code")
    print(f"📊 已下载完成: {len(downloaded_stocks)}只，剩余: {total_stocks - len(downloaded_stocks)}只")
    
    # 3. 逐只下载日线数据
    success_count = 0
    fail_count = 0
    pbar = tqdm(total=total_stocks, desc="下载进度")
    
    for _, row in stock_info.iterrows():
        ts_code = row["code"] + ".SH" if row["code"].startswith("6") else row["code"] + ".SZ"
        name = row["name"]
        
        # 跳过已经下载的
        if ts_code in downloaded_stocks:
            pbar.update(1)
            success_count += 1
            continue
        
        try:
            # 下载日线数据（前复权）
            df = ak.stock_zh_a_hist(
                symbol=row["code"],
                period="daily",
                start_date=START_DATE,
                end_date=END_DATE,
                adjust="qfq"
            )
            
            if df.empty:
                fail_count += 1
                pbar.update(1)
                continue
            
            # 重命名列
            df = df.rename(columns={
                "日期": "trade_date",
                "开盘": "open",
                "最高": "high",
                "最低": "low",
                "收盘": "close",
                "成交量": "vol",
                "成交额": "amount",
                "涨跌幅": "pct_chg",
                "涨跌额": "change",
            })
            
            # 转换日期格式为int
            # 先确保是字符串类型再处理
            df["trade_date"] = df["trade_date"].astype(str).str.replace("-", "").astype(int)
            
            # 添加股票代码
            df["ts_code"] = ts_code
            df["name"] = name
            
            # 单位转换
            df["amount"] = df["amount"] / 10000  # 元 → 万元
            df["vol"] = df["vol"] / 100  # 股 → 手
            
            # 计算涨跌停价（按前收盘价）
            records = []
            df_list = df.to_dict("records")
            for i in range(len(df_list)):
                current = df_list[i]
                if i == 0:
                    # 第一天用开盘价作为前收盘价
                    pre_close = current["open"]
                else:
                    pre_close = df_list[i-1]["close"]
                
                current["pre_close"] = pre_close
                current["up_limit"] = round(pre_close * 1.1, 2)  # 涨停价
                current["down_limit"] = round(pre_close * 0.9, 2)  # 跌停价
                current["source"] = "ak"  # 数据源标记
                
                # 构造ID
                current["_id"] = f"{ts_code}_{current['trade_date']}"
                records.append(current)
            
            # 批量插入
            if records:
                await collection.insert_many(records, ordered=False)
            
            success_count += 1
            
        except Exception as e:
            print(f"\n❌ 下载 {ts_code}({name}) 失败: {str(e)[:50]}")
            fail_count += 1
        
        finally:
            pbar.update(1)
    
    pbar.close()
    
    # 统计结果
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
            "$expr": {"$gte": ["$close", {"$multiply": ["$up_limit", 0.995]}]}
        })
        print(f"\n📊 最新交易日 {test_date} 统计:")
        print(f"  股票数量: {day_count}只")
        print(f"  涨停数量: {limit_up_count}只")

if __name__ == "__main__":
    asyncio.run(download_full_market())
