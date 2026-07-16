"""
从stock_daily_ak_full的is_limit_up/is_limit_down反向生成limit_list历史数据
补全2024-05-06~2025-12-31缺失的涨停池记录

用法: python3 fill_limit_list_from_daily.py [--start 20240506] [--end 20251231]
"""
import argparse
from pymongo import MongoClient


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--start', default='20240506')
    parser.add_argument('--end', default='20251231')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    client = MongoClient('localhost', 27017)
    db = client.stock_agent

    # 获取stock_daily有但limit_list缺失的日期
    bar_dates = set(d['_id'] for d in db.stock_daily_ak_full.aggregate([
        {"$group": {"_id": "$trade_date"}}
    ]))
    ll_dates = set(d['_id'] for d in db.limit_list.aggregate([
        {"$group": {"_id": "$trade_date"}}
    ]))
    missing = sorted(d for d in (bar_dates - ll_dates) if int(args.start) <= d <= int(args.end))
    print(f"缺失涨停池数据: {len(missing)}天 ({missing[0] if missing else '?'}~{missing[-1] if missing else '?'})")

    if args.dry_run:
        for d in missing[:10]:
            print(f"  {d}")
        if len(missing) > 10:
            print(f"  ... 共{len(missing)}天")
        return

    total_up = 0
    total_down = 0

    for td in missing:
        # 涨停
        up_docs = []
        for doc in db.stock_daily_ak_full.find({
            'trade_date': td, 'is_limit_up': 1
        }, {'ts_code': 1, 'close': 1, 'pct_chg': 1, 'limit_up_count': 1, 'first_limit_up': 1}):
            up_docs.append({
                'trade_date': td,
                'ts_code': doc['ts_code'],
                'name': '',  # 名字不关键,回测不用
                'limit': 'U',
                'close': doc.get('close', 0),
                'amp': doc.get('pct_chg', 0),
                'fc_ratio': 0,
                'first_time': '09:30:00' if doc.get('first_limit_up') else '',
                'last_time': '',
                'open_times': 0,
                'limit_times': doc.get('limit_up_count', 1),
            })

        # 跌停
        down_docs = []
        for doc in db.stock_daily_ak_full.find({
            'trade_date': td, 'is_limit_down': 1
        }, {'ts_code': 1, 'close': 1, 'pct_chg': 1}):
            down_docs.append({
                'trade_date': td,
                'ts_code': doc['ts_code'],
                'name': '',
                'limit': 'D',
                'close': doc.get('close', 0),
                'amp': doc.get('pct_chg', 0),
                'fc_ratio': 0,
                'first_time': '',
                'last_time': '',
                'open_times': 0,
                'limit_times': 1,
            })

        all_docs = up_docs + down_docs
        if all_docs:
            try:
                db.limit_list.insert_many(all_docs, ordered=False)
            except Exception as e:
                print(f"  {td}: 插入失败 {e}")
                continue

        total_up += len(up_docs)
        total_down += len(down_docs)
        if len(missing) <= 20 or td == missing[-1] or td % 100 == 1:
            print(f"  {td}: 涨停={len(up_docs)} 跌停={len(down_docs)}")

    print(f"\n✅ 完成! 涨停{total_up}条 跌停{total_down}条 共{total_up+total_down}条")


if __name__ == '__main__':
    main()
