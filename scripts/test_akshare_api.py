#!/usr/bin/env python3
"""
测试 AKShare API 连接性和数据获取
"""

import akshare as ak

def test_akshare_api():
    print('=== 测试 AKShare API 连接性 ===')
    print()
    
    # 测试一只股票的历史数据获取
    test_stock = '000001'  # 平安银行，去掉.SZ后缀
    
    print(f'1. 测试获取股票 {test_stock} 的历史数据')
    print()
    
    try:
        print(f'   正在从 AKShare 获取 {test_stock} 历史数据...')
        
        df = ak.stock_zh_a_hist(
            symbol=test_stock,
            period='daily',
            start_date='20260105',
            end_date='20260110',
            adjust=''
        )
        
        if df is None or df.empty:
            print('   ❌ AKShare 返回空数据')
            return False
        else:
            print(f'   ✅ 成功获取 {len(df)} 条记录')
            print()
            
            # 显示数据
            print('   前5条数据:')
            print(df.head().to_string())
            print()
            
            # 检查数据格式
            print('   数据列名:')
            for col in df.columns:
                sample = df[col].iloc[0] if len(df) > 0 else 'N/A'
                print(f'     {col}: 类型 {df[col].dtype}, 示例 {sample}')
            
            # 检查是否有正常的价格变化
            if len(df) >= 2:
                close_values = df['收盘'].head(2).tolist()
                if close_values[0] != close_values[1]:
                    print(f'   ✅ 价格有正常变化: {close_values[0]} -> {close_values[1]}')
                else:
                    print(f'   ⚠️  价格没有变化: {close_values[0]} = {close_values[1]}')
                    
            # 检查数据列名
            print()
            print(f'   列名列表: {list(df.columns)}')
            
            # 检查是否有我们需要的关键列
            needed_columns = ['日期', '开盘', '收盘', '最高', '最低', '成交量', '成交额', '涨跌幅', '涨跌额']
            missing = [col for col in needed_columns if col not in df.columns]
            
            if missing:
                print(f'   ⚠️  缺少关键列: {missing}')
                return False
            else:
                print('   ✅ 所有关键列都存在')
                return True
            
    except Exception as e:
        print(f'   ❌ 获取数据失败: {e}')
        import traceback
        traceback.print_exc()
        return False

def test_stock_list():
    print()
    print('=== 测试股票列表获取 ===')
    
    try:
        stock_list = ak.stock_info_a_code_name()
        if stock_list is not None and not stock_list.empty:
            print(f'✅ 成功获取股票列表，共 {len(stock_list)} 只股票')
            print('   前5只股票:')
            print(stock_list.head().to_string())
            return True
        else:
            print('⚠️  股票列表为空')
            return False
            
    except Exception as e:
        print(f'❌ 获取股票列表失败: {e}')
        import traceback
        traceback.print_exc()
        return False

def test_spot_data():
    print()
    print('=== 测试实时行情数据 ===')
    
    try:
        # 测试实时行情
        spot_df = ak.stock_zh_a_spot()
        
        if spot_df is None or spot_df.empty:
            print('❌ 实时行情数据为空')
            return False
        else:
            print(f'✅ 获取实时行情数据，共 {len(spot_df)} 只股票')
            print('   列名:')
            for col in spot_df.columns:
                print(f'     {col}')
            return True
            
    except Exception as e:
        print(f'❌ 获取实时行情失败: {e}')
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    # 运行所有测试
    hist_success = test_akshare_api()
    list_success = test_stock_list()
    spot_success = test_spot_data()
    
    print()
    print('=' * 60)
    print('测试结果汇总:')
    print(f'  历史数据: {"✅ 通过" if hist_success else "❌ 失败"}')
    print(f'  股票列表: {"✅ 通过" if list_success else "❌ 失败"}')
    print(f'  实时行情: {"✅ 通过" if spot_success else "❌ 失败"}')
    
    if hist_success and list_success:
        print('✅ AKShare API 工作正常，可以开始下载数据')
    else:
        print('❌ AKShare API 存在问题，需要检查')