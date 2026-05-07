#!/usr/bin/env python3
"""
数据统一化脚本 — 将stock_daily_ak_full的所有数据统一为标准格式

标准格式:
  close/open/high/low/pre_close: 真实价(不复权)
  vol: 股(整数)
  amount: 元(浮点数)
  circ_mv: 万元(浮点数)
  turnover_rate: 百分比(如0.48, 不是48)
  volume_ratio: 倍数(如1.5)
  pct_chg: 百分比(如-2.15)

问题数据段:
  段1 (20251008~20260320): Tushare前复权, close=前复权价, vol=手, amount=千元
  段2 (20260323~20260506): AKShare, close=真实价, vol=股, amount=元, 但每日只2400只
  段3 (20260507+): 东方财富, close=真实价, vol=股, amount=元, circ_mv=万元

统一化策略:
  段1: 用AKShare stock_zh_a_daily重新拉(真实价+股+元), 覆盖旧数据
  段2: 保留, 但补全缺失的股票(用AKShare补)
  段3: 保留, 修正circ_mv单位(东方财富写入的万元→保持万元)

注意: 
  - 段1的前复权数据严重干扰回测, 必须替换
  - AKShare stock_zh_a_daily一次拉全市场需要逐只, 约17分钟
  - 但只需要拉段1的日期范围(20251008~20260320)

用法:
  python3 scripts/unify_data.py [--dry-run] [--start 20251008] [--end 20260320]
"""
import sys
import os
import time
import logging
import argparse
from pymongo import MongoClient, UpdateOne

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "stock_agent"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("unify")

# ============ 数据标准 ============
# 所有数据最终必须满足:
STANDARD = {
    "close": "真实价(不复权), float",
    "open": "真实价(不复权), float",
    "high": "真实价(不复权), float",
    "low": "真实价(不复权), float",
    "pre_close": "真实价(不复权), float",
    "pct_chg": "百分比, float (如-2.15, 不是-0.0215)",
    "vol": "股, int",
    "amount": "元, float",
    "circ_mv": "万元, float",
    "turnover_rate": "百分比, float (如0.48, 不是48)",
    "volume_ratio": "倍数, float (如1.5)",
}


def detect_qfq_dates(db):
    """检测哪些日期的数据是前复权格式"""
    # 用平安银行(000001.SZ)作为检测标的
    # 真实价应在5-15区间, 前复权价约50-70
    pipeline = [
        {"$match": {"ts_code": "000001.SZ"}},
        {"$project": {
            "trade_date": 1,
            "close": 1,
            "is_qfq": {"$cond": [{"$gt": ["$close", 30]}, True, False]}
        }},
        {"$sort": {"trade_date": 1}}
    ]
    
    qfq_dates = []
    real_dates = []
    for doc in db.stock_daily_ak_full.aggregate(pipeline):
        if doc.get("is_qfq"):
            qfq_dates.append(doc["trade_date"])
        else:
            real_dates.append(doc["trade_date"])
    
    return qfq_dates, real_dates


def fix_qfq_segment(db, start_date, end_date, dry_run=False):
    """修复前复权数据段 — 用AKShare重新拉真实价数据
    
    AKShare stock_zh_a_daily返回:
      open/high/low/close: 真实价(不复权, adjust='')
      volume: 股
      amount: 元
      turnover: 换手率(小数, 需×100=百分比)
    """
    import akshare as ak
    
    log.info(f"修复前复权数据段: {start_date}~{end_date}")
    
    # 获取需要修复的交易日
    qfq_dates = sorted(db.stock_daily_ak_full.distinct(
        "trade_date", 
        {"trade_date": {"$gte": start_date, "$lte": end_date}}
    ))
    log.info(f"需要修复的交易日: {len(qfq_dates)}天")
    
    # 获取股票列表(只拉还在列表中的)
    codes = db.stock_basic.distinct("ts_code", {"list_status": "L"})
    log.info(f"活跃股票: {len(codes)}只")
    
    # 转换ts_code → AKShare symbol
    def ts_code_to_symbol(ts_code):
        code, suffix = ts_code.split(".")
        if suffix == "SH":
            return f"sh{code}"
        elif suffix == "SZ":
            return f"sz{code}"
        else:
            return None  # 北交所不支持stock_zh_a_daily
    
    total_updated = 0
    total_failed = 0
    
    for i, ts_code in enumerate(codes):
        symbol = ts_code_to_symbol(ts_code)
        if symbol is None:
            continue  # 跳过北交所
        
        try:
            # 拉取该股票在整个日期范围内的日线
            start_str = str(start_date)
            end_str = str(end_date)
            df = ak.stock_zh_a_daily(
                symbol=symbol, 
                start_date=start_str, 
                end_date=end_str, 
                adjust=""  # 不复权!
            )
            
            if df.empty:
                continue
            
            updates = []
            for _, row in df.iterrows():
                td = int(row["date"].replace("-", ""))
                
                record = {
                    "open": round(float(row["open"]), 2),
                    "high": round(float(row["high"]), 2),
                    "low": round(float(row["low"]), 2),
                    "close": round(float(row["close"]), 2),
                    "pre_close": round(float(row["close"]) - float(row.get("change", 0)), 2),
                    "pct_chg": round(float(row.get("pct_change", 0)) * 100, 2),
                    "vol": int(float(row["volume"])),  # 股
                    "amount": float(row["amount"]),     # 元
                    "turnover_rate": round(float(row.get("turnover", 0)) * 100, 4),  # 小数→百分比
                }
                
                updates.append(
                    UpdateOne(
                        {"ts_code": ts_code, "trade_date": td},
                        {"$set": record}
                    )
                )
            
            if updates and not dry_run:
                try:
                    result = db.stock_daily_ak_full.bulk_write(updates, ordered=False)
                    total_updated += result.modified_count
                except Exception as e:
                    log.error(f"  {ts_code} bulk_write error: {e}")
                    total_failed += len(updates)
            
        except Exception as e:
            if "date" not in str(e):  # 北交所date错误不记录
                log.warning(f"  {ts_code} 获取失败: {e}")
            total_failed += 1
            continue
        
        if (i + 1) % 500 == 0:
            log.info(f"  进度: {i+1}/{len(codes)}, 更新={total_updated}, 失败={total_failed}")
        
        time.sleep(0.15)  # AKShare限流
    
    log.info(f"前复权修复完成: 更新={total_updated}, 失败={total_failed}")


def fix_segment2_missing(db, start_date, end_date, dry_run=False):
    """修复段2缺失的股票(AKShare段每天只有2400只, 缺SZ/BJ)"""
    import akshare as ak
    
    log.info(f"修复段2缺失: {start_date}~{end_date}")
    
    # 找出缺失的股票-日期对
    dates = sorted(db.stock_daily_ak_full.distinct(
        "trade_date",
        {"trade_date": {"$gte": start_date, "$lte": end_date}}
    ))
    
    for td in dates:
        existing_codes = set(db.stock_daily_ak_full.distinct("ts_code", {"trade_date": td}))
        all_codes = set(db.stock_basic.distinct("ts_code", {"list_status": "L"}))
        missing = all_codes - existing_codes
        
        if not missing:
            continue
        
        log.info(f"  {td}: 缺{len(missing)}只")
        
        # 只拉SZ的(BJ不支持stock_zh_a_daily)
        sz_missing = [c for c in missing if c.endswith(".SZ")]
        
        for ts_code in sz_missing[:50]:  # 每天最多补50只
            code = ts_code.replace(".SZ", "")
            try:
                df = ak.stock_zh_a_daily(
                    symbol=f"sz{code}",
                    start_date=str(td),
                    end_date=str(td),
                    adjust=""
                )
                if df.empty:
                    continue
                
                row = df.iloc[0]
                record = {
                    "ts_code": ts_code,
                    "trade_date": td,
                    "open": round(float(row["open"]), 2),
                    "high": round(float(row["high"]), 2),
                    "low": round(float(row["low"]), 2),
                    "close": round(float(row["close"]), 2),
                    "pre_close": round(float(row["close"]) - float(row.get("change", 0)), 2),
                    "pct_chg": round(float(row.get("pct_change", 0)) * 100, 2),
                    "vol": int(float(row["volume"])),
                    "amount": float(row["amount"]),
                    "turnover_rate": round(float(row.get("turnover", 0)) * 100, 4),
                }
                
                if not dry_run:
                    db.stock_daily_ak_full.update_one(
                        {"ts_code": ts_code, "trade_date": td},
                        {"$set": record},
                        upsert=True
                    )
            except Exception:
                pass
            
            time.sleep(0.15)


def fix_eastmoney_circ_mv(db, trade_date, dry_run=False):
    """修正东方财富数据的circ_mv单位
    
    东方财富API返回的流通市值单位=元, 脚本里÷10000转万元
    但需要确认是否真的存的是万元
    """
    # 检查: 茅台流通市值≈1.72万亿=17169亿元=171692507万元
    s = db.stock_daily_ak_full.find_one({"trade_date": trade_date, "ts_code": "600519.SH"})
    if s:
        circ = s.get("circ_mv", 0)
        if circ > 1e10:  # >100亿万元=1万亿? 不对, 应该是171692507万元
            log.info(f"  {trade_date} circ_mv单位检查: 600519.SH={circ} → {circ/10000:.2f}亿")
            if circ / 10000 > 10000:  # 亿元>1万亿? 
                log.warning(f"  ⚠️ circ_mv可能存的是元而非万元!")


def validate_data_quality(db):
    """验证数据质量"""
    log.info("=== 数据质量验证 ===")
    
    # 1. 检测前复权数据
    qfq, real = detect_qfq_dates(db)
    if qfq:
        log.warning(f"⚠️ 仍有{len(qfq)}天前复权数据 ({qfq[0]}~{qfq[-1]})")
    else:
        log.info("✅ 无前复权数据")
    
    # 2. 检测vol单位异常
    # 真实价下, 日成交量<1亿股是正常的; 如果vol<1000, 可能是手
    for td in [20260320, 20260323, 20260507]:
        cnt = db.stock_daily_ak_full.count_documents({"trade_date": td, "vol": {"$lt": 1000}})
        total = db.stock_daily_ak_full.count_documents({"trade_date": td})
        log.info(f"  {td}: vol<1000={cnt}/{total} (可能是'手'而非'股')")
    
    # 3. 检测amount单位异常
    for td in [20260320, 20260323, 20260507]:
        cnt = db.stock_daily_ak_full.count_documents({"trade_date": td, "amount": {"$lt": 100000}})
        total = db.stock_daily_ak_full.count_documents({"trade_date": td})
        log.info(f"  {td}: amount<100000={cnt}/{total} (可能是'千元'而非'元')")
    
    # 4. 每日股票数量
    for td in sorted(db.stock_daily_ak_full.distinct("trade_date"))[-5:]:
        cnt = db.stock_daily_ak_full.count_documents({"trade_date": td})
        status = "⚠️偏少" if cnt < 4000 else "✅"
        log.info(f"  {td}: {cnt}只 {status}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="数据统一化")
    parser.add_argument("--dry-run", action="store_true", help="只检测不修改")
    parser.add_argument("--validate", action="store_true", help="只做数据质量验证")
    parser.add_argument("--fix-qfq", action="store_true", help="修复前复权数据段")
    parser.add_argument("--fix-missing", action="store_true", help="修复段2缺失股票")
    parser.add_argument("--start", type=int, default=20251008, help="起始日期")
    parser.add_argument("--end", type=int, default=20260320, help="结束日期")
    args = parser.parse_args()
    
    db = MongoClient(MONGO_URI)[DB_NAME]
    
    if args.validate or (not args.fix_qfq and not args.fix_missing):
        validate_data_quality(db)
    
    if args.fix_qfq:
        fix_qfq_segment(db, args.start, args.end, dry_run=args.dry_run)
    
    if args.fix_missing:
        fix_segment2_missing(db, 20260323, 20260506, dry_run=args.dry_run)
