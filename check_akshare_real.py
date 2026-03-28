#!/usr/bin/env python3
"""
从 AKShare 获取真实数据，对比数据库中的数据
"""
import akshare as ak
import pandas as pd
import numpy as np
import pymongo
from datetime import datetime

# 连接 MongoDB
client = pymongo.MongoClient('mongodb://localhost:27017/')
db = client['stock_agent']

def get_real_akshare_data():
    """从 AKShare 获取真实数据"""
    
    # 股票代码 sh600110.SZ
    stock_code = "sh600110"
    
    print(f"📊 从 AKShare 获取 {stock_code} 的真实数据")
    print("="*60)
    
    try:
        # 获取历史数据
        df = ak.stock_zh_a_hist(
            symbol=stock_code, 
            period="daily", 
            start_date="20260101", 
            end_date="20260320",
            adjust=""
        )
        
        if df.empty:
            print("❌ AKShare 返回空数据")
            return
        
        print(f"✅ 获取到 {len(df)} 条数据")
        
        # 显示前几行
        print("\n📈 AKShare 数据前10行:")
        print(df.head(10).to_string())
        
        # 检查涨停价计算
        print("\n🔍 检查涨停价计算:")
        # AKShare 数据列：日期、开盘、收盘、最高、最低、成交量、成交额、振幅、涨跌幅、涨跌额、换手率
        # 涨停价 = 前收盘价 * 1.1（创业板/科创板不同）
        
        # 手动计算涨停价
        df["涨停价_计算"] = df["收盘"].shift(1) * 1.1
        
        # 显示对比
        for idx, row in df.head(10).iterrows():
            print(f"  日期: {row['日期']}, 收盘: {row['收盘']}, 前收盘: {row['收盘'].shift(1) if idx>0 else 'N/A'}, 涨停价_计算: {row['涨停价_计算'] if not pd.isna(row['涨停价_计算']) else 'N/A'}")
        
        # 对比数据库中的数据
        print(f"\n🔍 对比数据库数据:")
        
        # 获取数据库中的数据
        db_docs = list(db.stock_daily_ak.find(
            {"ts_code": f"{stock_code}.SZ"},
            {"trade_date": 1, "close": 1, "up_limit": 1, "open": 1}
        ).sort("trade_date", 1).limit(10))
        
        print(f"   数据库中的 {stock_code}.SZ 数据:")
        for doc in db_docs:
            print(f"     日期: {doc['trade_date']}, close: {doc.get('close')}, up_limit: {doc.get('up_limit')}, open: {doc.get('open')}")
        
        # 对比 20260105-20260106
        print(f"\n🔍 详细对比 20260105-20260106:")
        
        # 从 AKShare 数据中找
        akshare_20260105 = df[df["日期"] == "2026-01-05"]
        akshare_20260106 = df[df["日期"] == "2026-01-06"]
        
        if not akshare_20260105.empty:
            row = akshare_20260105.iloc[0]
            print(f"   AKShare 2026-01-05:")
            print(f"     收盘: {row['收盘']}")
            print(f"     前收盘: {df[df['日期'] == '2026-01-04']['收盘'].iloc[0] if not df[df['日期'] == '2026-01-04'].empty else 'N/A'}")
            print(f"     涨停价_计算: {row['收盘'].shift(1) * 1.1 if idx>0 else 'N/A'}")
        
        if not akshare_20260106.empty:
            row = akshare_20260106.iloc[0]
            print(f"   AKShare 2026-01-06:")
            print(f"     开盘: {row['开盘']}")
            print(f"     前收盘: {df[df['日期'] == '2026-01-05']['收盘'].iloc[0] if not df[df['日期'] == '2026-01-05'].empty else 'N/A'}")
            print(f"     涨停价_计算: {row['收盘'].shift(1) * 1.1 if idx>0 else 'N/A'}")
        
        # 检查其他股票
        print(f"\n🔍 检查其他股票数据:")
        
        # 获取一个随机股票
        random_docs = list(db.stock_daily_ak.find(
            {"trade_date": 20260105},
            {"ts_code": 1, "close": 1, "up_limit": 1}
        ).limit(5))
        
        for doc in random_docs:
            ts_code = doc["ts_code"]
            close = doc.get("close")
            up_limit = doc.get("up_limit")
            
            # 检查涨停价是否合理
            if close and up_limit:
                ratio = up_limit / close if close != 0 else 0
                print(f"   {ts_code}: close={close}, up_limit={up_limit}, 比例={ratio:.4f}")
                
                # 涨停价应该是收盘价的 1.1 倍左右
                if abs(ratio - 1.1) > 0.01:
                    print(f"      ⚠️  涨停价比例异常！应该是 ~1.1，实际是 {ratio:.4f}")
                else:
                    print(f"      ✅  涨停价比例正常")
        
    except Exception as e:
        print(f"❌ 获取 AKShare 数据失败: {e}")
        import traceback
        traceback.print_exc()

def test_akshare_api():
    """测试 AKShare API 能否正常工作"""
    print(f"\n🧪 测试 AKShare API")
    print("="*60)
    
    try:
        # 测试获取股票列表
        stock_info = ak.stock_info_a_code_name()
        print(f"✅ 获取股票列表成功: {len(stock_info)} 只股票")
        
        # 测试获取单只股票数据
        test_df = ak.stock_zh_a_hist(
            symbol="sh600000", 
            period="daily", 
            start_date="20260101", 
            end_date="20260105",
            adjust=""
        )
        print(f"✅ 获取单只股票数据成功: {len(test_df)} 条记录")
        print(f"   列名: {list(test_df.columns)}")
        
        # 显示列名和数据类型
        print(f"   数据列: {test_df.dtypes.to_dict()}")
        
    except Exception as e:
        print(f"❌ AKShare API 测试失败: {e}")

if __name__ == "__main__":
    print("🔍 验证数据库数据 vs AKShare 真实数据")
    print("="*60)
    
    test_akshare_api()
    get_real_akshare_data()