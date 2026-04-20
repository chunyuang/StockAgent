#!/usr/bin/env python3
"""
增量更新日线数据
自动检查最新交易日，增量更新，不需要全量重新下载
使用 fallback 链条: Tushare → AKShare → Baostock
"""

import argparse
import sys
import os
from datetime import datetime
from pymongo import MongoClient

# 项目路径加入 sys.path
sys.path.append('/root/.openclaw/workspace/StockAgent/AgentServer')

from data_sources import data_manager

def get_last_trade_date_from_mongo():
    """从 MongoDB 获取最新交易日"""
    client = MongoClient('mongodb://localhost:27017/')
    db = client['stock_agent']
    coll = db['stock_daily_ak_full']
    
    # 找到最大的 trade_date
    result = coll.find({}, {'trade_date': 1}).sort([('trade_date', -1)]).limit(1)
    last_date = None
    for doc in result:
        last_date = doc['trade_date']
        break
    client.close()
    return last_date

def count_total_records():
    """统计总记录数"""
    client = MongoClient('mongodb://localhost:27017/')
    db = client['stock_agent']
    coll = db['stock_daily_ak_full']
    count = coll.count_documents({})
    client.close()
    return count

def incremental_update(start_date=None, end_date=None):
    """增量更新数据"""
    dm = data_manager.DataManager()
    
    # 获取最后交易日
    last_date_db = get_last_trade_date_from_mongo()
    print(f"Last trade date in database: {last_date_db}")
    
    # 如果没有 start_date，从 last_date + 1 开始
    if start_date is None:
        if last_date_db is not None:
            start_date = last_date_db + 1
        else:
            # 默认从 2025-12-15 开始（本次回归测试起点）
            start_date = 20251215
    
    if end_date is None:
        # 默认到今天
        today = datetime.now().strftime('%Y%m%d')
        end_date = int(today)
    
    print(f"Incremental update from {start_date} to {end_date}")
    
    # 获取股票列表
    client = MongoClient('mongodb://localhost:27017/')
    db = client['stock_agent']
    coll = db['stock_basic']
    stocks = []
    for doc in coll.find({}, {'ts_code': 1}):
        stocks.append(doc['ts_code'])
    client.close()
    
    print(f"Total stocks: {len(stocks)}")
    
    # 增量获取
    inserted = 0
    for ts_code in stocks:
        # 获取日线
        df = dm.get_daily(ts_code, start_date, end_date)
        if df is None or df.empty:
            continue
        
        # 插入 MongoDB
        records = df.to_dict('records')
        for r in records:
            # 统一键名
            if '代码' in r:
                r['ts_code'] = r['代码']
            if '开盘' in r:
                r['open'] = r['开盘']
            if '最高' in r:
                r['high'] = r['最高']
            if '最低' in r:
                r['low'] = r['最低']
            if '最新价' in r:
                r['close'] = r['最新']
            if '成交量' in r:
                r['vol'] = r['成交量']
            if '成交额' in r:
                r['amount'] = r['成交额']
        
        client = MongoClient('mongodb://localhost:27017/')
        db = client['stock_agent']
        db['stock_daily_ak_full'].insert_many(records)
        client.close()
        inserted += len(records)
    
    print(f"\n✅ Incremental update complete! Inserted {inserted} new records")
    print(f"Total records now: {count_total_records()}")
    
    return inserted

def update_metadata(raw_name):
    """更新 metadata 文件（总记录数）"""
    metadata_path = f'/root/.openclaw/workspace/local-databases/raw/metadata/{raw_name}.md'
    if not os.path.exists(metadata_path):
        print(f"⚠️ Metadata not found: {metadata_path}")
        return
    
    # 读取现有内容
    with open(metadata_path, 'r') as f:
        content = f.read()
    
    # 更新总记录数
    total = count_total_records()
    content = content.replace(f'total_records: {count_total_records}', f'total_records: {total}')
    
    # 更新最后交易日
    last_date = get_last_trade_date_from_mongo()
    if 'last_trade_date:' in content:
        # 替换
        lines = content.split('\n')
        new_lines = []
        for line in lines:
            if 'last_trade_date:' in line:
                new_lines.append(f'| **最后交易日** | {last_date} |')
            else:
                new_lines.append(line)
        content = '\n'.join(new_lines)
    else:
        # 添加
        content += f'\n| **最后交易日** | {last_date} |\n'
    
    with open(metadata_path, 'w') as f:
        f.write(content)
    
    print(f"✅ Metadata updated: {metadata_path}")

def regenerate_index():
    """重新生成总体索引 README"""
    # 扫描 raw metadata 收集所有原始数据库
    metadata_dir = '/root/.openclaw/workspace/local-databases/raw/metadata'
    raw_list = []
    for f in os.listdir(metadata_dir):
        if f.endswith('.md'):
            name = f.replace('.md', '')
            # 读取 metadata 提取基本信息
            with open(os.path.join(metadata_dir, f), 'r') as mf:
                content = mf.read()
                n_stocks = 0
                n_days = 0
                total = 0
                start = None
                end = None
                for line in content.split('\n'):
                    if '股票数量' in line:
                        for part in line.split('|'):
                            digits = ''.join([c for c in part if c.isdigit()])
                            if digits:
                                n_stocks = int(digits)
                    if '交易日数量' in line:
                        for part in line.split('|'):
                            digits = ''.join([c for c in part if c.isdigit()])
                            if digits:
                                n_days = int(digits)
                    if '总日线记录数' in line:
                        for part in line.split('|'):
                            digits = ''.join([c for c in part if c.isdigit()])
                            if digits:
                                total = int(digits)
                    if '起止日期' in line:
                        # 找 ~
                        for part in line.split('|'):
                            if '~' in part:
                                parts = part.split('~')
                                if len(parts) >= 2:
                                    start = parts[0].strip()
                                    end = parts[1].strip()
            raw_list.append({
                'name': name,
                'n_stocks': n_stocks,
                'n_days': n_days,
                'total_records': total,
                'start_date': start,
                'end_date': end,
            })
    
    # 生成 README
    readme_path = '/root/.openclaw/workspace/local-databases/README.md'
    with open(readme_path, 'r') as f:
        original = f.read()
    
    # 找到 原始数据源列表 位置替换
    if '## 原始数据源列表' in original:
        # 分割
        before, after = original.split('## 原始数据源列表')
        new_table = """
## 原始数据源列表

| 原始数据名称 | 起止日期 | 股票数量 | 交易日 | 总记录数 | 创建时间 | 更新时间 |
|--------------|----------|----------|------------|------------|----------|------------|
"""
        for raw in raw_list:
            update_time = datetime.now().strftime('%Y-%m-%d')
            new_table += f"| `{raw['name']}` | {raw['start_date']} ~ {raw['end_date']} | {raw['n_stocks']} | {raw['n_days']} | {raw['total_records']} | {raw.get('created', '-')} | {update_time} |\n"
        
        new_after = new_table + '\n' + after
        final = before + '## 原始数据源列表' + new_after
    else:
        final = original
    
    with open(readme_path, 'w') as f:
        f.write(final)
    
    print(f"✅ Index regenerated: {readme_path}")

def main():
    parser = argparse.ArgumentParser(description='Incremental update daily data')
    parser.add_argument('--start', type=int, help='Start date YYYYMMDD, default: after last date in DB')
    parser.add_argument('--end', type=int, help='End date YYYYMMDD, default: today')
    parser.add_argument('--raw', type=str, help='Raw database name', required=True)
    args = parser.parse_args()
    
    incremental_update(args.start, args.end)
    update_metadata(args.raw)
    regenerate_index()
    print("\n✅ All done!")

if __name__ == '__main__':
    main()
