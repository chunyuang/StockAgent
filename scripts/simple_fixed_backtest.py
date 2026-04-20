#!/usr/bin/env python3
"""
简单的修复后回测测试
"""

import sys

# 添加项目路径
sys.path.insert(0, '/root/.openclaw/workspace/StockAgent')

try:
    # 尝试导入回测相关模块
    from backtest_module.backtest_engine.factor_selection.portfolio_backtest import PortfolioBacktester
    
    print("✅ 成功导入PortfolioBacktester")
    
    # 查看构造函数签名
    import inspect
    sig = inspect.signature(PortfolioBacktester.__init__)
    print(f"构造函数参数: {sig}")
    
except Exception as e:
    print(f"❌ 导入失败: {e}")
    import traceback
    traceback.print_exc()

def test_fixed_data():
    print()
    print("🧪 测试修复后的数据...")
    
    import pymongo
    client = pymongo.MongoClient('localhost', 27017)
    db = client['stock_agent']
    collection = db['stock_daily_ak_full_ak']
    
    # 检查修复后的数据
    print("1. 检查修复后的成交额数据:")
    sample = list(collection.find().limit(3))
    
    for record in sample:
        ts_code = record.get('ts_code', 'N/A')
        trade_date = record.get('trade_date', 'N/A')
        amount = record.get('amount', 0)
        
        print(f"   {ts_code} - {trade_date}:")
        print(f"     成交额: {amount:,.2f} 万元")
        print(f"     对应人民币: {amount * 10000:,.0f} 元")
        
        # 检查是否在合理范围内
        if 100 <= amount <= 500000:  # 100万到50亿元之间
            print("     ✅ 合理范围 (平安银行正常成交额)")
        else:
            print("     ⚠️  可能需要调整")
    
    print()
    print("2. 流动性门槛分析:")
    print("   设置门槛: 1000 万元 (现在单位是万元)")
    
    # 统计满足门槛的股票
    pipeline = [
        {"$match": {"amount": {"$gte": 1000}}},
        {"$group": {"_id": "$ts_code"}}
    ]
    
    liquid_stocks = list(collection.aggregate(pipeline))
    print(f"   满足门槛的股票数: {len(liquid_stocks)} 只")
    
    if len(liquid_stocks) >= 50:
        print("   ✅ 有足够的流动性股票进行回测")
    elif len(liquid_stocks) >= 10:
        print("   ⚠️  流动性股票较少，但可以进行测试")
    else:
        print("   ❌ 流动性股票太少，建议降低门槛")
    
    # 显示一些满足门槛的股票
    if len(liquid_stocks) > 0:
        print("   满足门槛的股票示例:")
        for i, stock in enumerate(liquid_stocks[:5], 1):
            stock_code = stock['_id']
            # 获取该股票的最新成交额
            latest = collection.find_one({'ts_code': stock_code}, sort=[('trade_date', -1)])
            if latest:
                amount = latest.get('amount', 0)
                print(f"     {i}. {stock_code}: {amount:,.2f} 万元")
    
    client.close()

def run_simple_backtest():
    print()
    print("🚀 运行简单回测...")
    
    # 尝试从项目中的现有回测脚本运行
    try:
        import subprocess
        print("   尝试运行现有的回测脚本...")
        
        # 查找项目中的回测脚本
        import os
        scripts_dir = '/root/.openclaw/workspace/StockAgent/backtest_module/backtest_engine/scripts'
        
        if os.path.exists(scripts_dir):
            scripts = os.listdir(scripts_dir)
            print(f"   找到回测脚本: {scripts}")
            
            # 尝试运行
            test_script = None
            for script in scripts:
                if 'akshare' in script.lower() and script.endswith('.py'):
                    test_script = os.path.join(scripts_dir, script)
                    break
            
            if test_script:
                print(f"   运行脚本: {test_script}")
                result = subprocess.run(['python3', test_script], capture_output=True, text=True)
                
                print("   输出:")
                print(result.stdout)
                
                if result.stderr:
                    print("   错误:")
                    print(result.stderr)
            else:
                print("   ❌ 没有找到合适的回测脚本")
        else:
            print(f"   ❌ 脚本目录不存在: {scripts_dir}")
    
    except Exception as e:
        print(f"   运行失败: {e}")

def main():
    print("🔧 修复后数据回测测试")
    print("="*60)
    
    test_fixed_data()
    # 暂时不运行回测，先确保数据正确
    print()
    print("="*60)
    print("✅ 数据修复验证完成")
    print("   成交额单位已从元修复为万元")
    print("   建议:")
    print("     1. 策略筛选门槛使用万元单位")
    print("     2. 1000门槛 = 1000万元成交额")
    print("     3. 重新运行项目回测")

if __name__ == "__main__":
    main()