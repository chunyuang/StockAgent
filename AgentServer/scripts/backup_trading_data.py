#!/usr/bin/env python3
"""
交易数据每日备份 — broker_orders/positions/accounts/equity_curve
这些集合不可从外部重建, 必须备份
"""
import pymongo
import json
import os
from datetime import datetime
from pathlib import Path

BACKUP_DIR = Path("/root/.openclaw/workspace/StockAgent/backups")
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

def main():
    db = pymongo.MongoClient().stock_agent
    today = datetime.now().strftime('%Y%m%d')
    backup_path = BACKUP_DIR / today
    backup_path.mkdir(exist_ok=True)
    
    # 只备份不可恢复的集合
    critical_collections = [
        'broker_orders', 'broker_positions', 'broker_accounts', 'equity_curve',
        'risk_decisions', 'scanner_timeline', 'scanner_signals',
    ]
    
    total_docs = 0
    for col_name in critical_collections:
        docs = list(db[col_name].find())
        if docs:
            # 转换ObjectId为字符串
            for doc in docs:
                doc['_id'] = str(doc['_id'])
            
            output_file = backup_path / f"{col_name}.json"
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(docs, f, ensure_ascii=False, default=str, indent=1)
            
            total_docs += len(docs)
            print(f"  {col_name}: {len(docs)}条 → {output_file}")
        else:
            print(f"  {col_name}: 0条(跳过)")
    
    # 清理30天前的备份
    import shutil
    for d in sorted(BACKUP_DIR.iterdir()):
        if d.is_dir() and d.name < (datetime.now().replace(day=1) if datetime.now().day > 30 else datetime.now()).strftime('%Y%m%d'):
            age = (datetime.now() - datetime.strptime(d.name, '%Y%m%d')).days
            if age > 30:
                shutil.rmtree(d)
                print(f"  清理: {d.name} ({age}天前)")
    
    print(f"\n备份完成: {total_docs}条 → {backup_path}")

if __name__ == '__main__':
    main()
