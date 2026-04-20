#!/usr/bin/env python3
"""
更新A股交易日历，使用Baostock，不依赖Tushare
"""
import baostock as bs
import pymongo
from pymongo import UpdateOne

client = pymongo.MongoClient('mongodb://localhost:27017/')
db = client['stock_agent']
coll = db['trade_cal']

print("🚀 从Baostock获取交易日历...")
# 登录baostock
lg = bs.login()
if lg.error_code != '0':
    print(f"❌ Baostock登录失败: {lg.error_msg}")
    exit()

# 获取2026年全年交易日历
rs = bs.query_trade_dates(start_date='2025-01-01', end_date='2026-12-31')
data_list = []
while rs.error_code == '0' and rs.next():
    row = rs.get_row_data()
    cal_date = row[0].replace('-', '')  # 转换成YYYYMMDD格式
    is_open = 1 if row[1] == '1' else 0
    data_list.append({
        'cal_date': int(cal_date),
        'is_open': is_open,
        'year': int(cal_date[:4]),
        'month': int(cal_date[4:6]),
        'day': int(cal_date[6:8])
    })

bs.logout()
print(f"✅ 获取到{len(data_list)}条交易日历记录")

# 批量写入
operations = [
    UpdateOne(
        {'cal_date': item['cal_date']},
        {'$set': item},
        upsert=True
    ) for item in data_list
]

print("⏳ 写入数据库...")
result = coll.bulk_write(operations)
print(f"✅ 更新完成: 新增{result.upserted_count}条，更新{result.modified_count}条")
print("✅ 交易日历覆盖区间: 20250101 ~ 20261231")
