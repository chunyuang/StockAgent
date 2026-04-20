#!/usr/bin/env python3
"""
下载更多股票数据，扩大股票池
使用AKShare原生接口获取日线数据
"""

import akshare as ak
import pymongo
from tqdm import tqdm
import time
import pandas as pd

# 配置
START_DATE = "20260105"
END_DATE = "20260320"
TARGET_STOCK_COUNT = 500  # 目标下载500只股票

def get_akshare_stock_daily_ak_full(symbol, start_date, end_date):
    """
    使用AKShare原生接口获取股票日线数据
    """
    try:
        # 格式化日期
        start = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}"
        
        # 调用AKShare接口
        df = ak.stock_zh_a_daily(symbol=symbol, start_date=start, end_date=end_date, adjust="qfq")
        
        if df.empty:
            return None
        
        # 计算涨跌停价
        # 主板涨跌幅10%，科创板/创业板20%
        if symbol.startswith(('sh688', 'sz300')):
            limit_ratio = 0.2
        else:
            limit_ratio = 0.1
        
        df['pre_close'] = df['close'].shift(1)
        df['up_limit'] = df['pre_close'] * (1 + limit_ratio)
        df['down_limit'] = df['pre_close'] * (1 - limit_ratio)
        
        # 四舍五入到两位小数
        df[['up_limit', 'down_limit']] = df[['up_limit', 'down_limit']].round(2)
        
        # 添加trade_date字段
        df['trade_date'] = df.index.strftime('%Y%m%d').astype(int)
        
        # 重命名字段
        df = df.rename(columns={'volume': 'vol'})
        
        # 转换成交额为万元
        df['amount'] = df['amount'] / 10000.0
        
        return df
    
    except Exception as e:
        print(f"下载 {symbol} 失败: {e}")
        return None

def get_stock_list():
    """获取A股股票列表"""
    try:
        stock_info = ak.stock_info_a_code_name()
        print(f"获取到 {len(stock_info)} 只A股股票")
        return stock_info
    except Exception as e:
        print(f"获取股票列表失败: {e}")
        # 使用备选列表
        return pd.DataFrame({
            'code': [
                '000001', '000002', '000004', '000005', '000006', '000007', '000008', '000009', '000010',
                '000011', '000012', '000014', '000016', '000017', '000019', '000020', '000021', '000023',
                '000025', '000026', '000027', '000028', '000029', '000030', '000031', '000032', '000034',
                '000035', '000036', '000037', '000038', '000039', '000040', '000042', '000043', '000045',
                '000046', '000048', '000049', '000050', '000055', '000056', '000059', '000060', '000061',
                '000062', '000063', '000065', '000066', '000068', '000069', '000070', '000078', '000088',
                '000089', '000090', '000096', '000099', '000100', '000150', '000151', '000153', '000155',
                '000156', '000157', '000158', '000159', '000166', '000301', '000333', '000338', '000400',
                '000401', '000402', '000403', '000404', '000407', '000408', '000409', '000410', '000411',
                '000413', '000415', '000416', '000417', '000418', '000419', '000420', '000421', '000422',
                '000423', '000425', '000426', '000428', '000429', '000430', '000488', '000498', '000501',
                '000502', '000503', '000504', '000505', '000506', '000507', '000509', '000510', '000513',
                '000514', '000516', '000517', '000518', '000519', '000520', '000521', '000523', '000525',
                '000526', '000528', '000529', '000530', '000531', '000532', '000533', '000534', '000536',
                '000537', '000538', '000539', '000540', '000541', '000543', '000544', '000545', '000546',
                '000547', '000548', '000550', '000551', '000552', '000553', '000554', '000555', '000557',
                '000558', '000559', '000560', '000561', '000562', '000563', '000564', '000565', '000566',
                '000567', '000568', '000569', '000570', '000571', '000572', '000573', '000576', '000581',
                '000582', '000584', '000585', '000586', '000587', '000589', '000590', '000591', '000592',
                '000593', '000595', '000596', '000597', '000598', '000599', '000600', '000601', '000603',
                '000605', '000606', '000607', '000608', '000609', '000610', '000611', '000612', '000613',
                '000615', '000616', '000617', '000619', '000620', '000622', '000623', '000625', '000626',
                '000627', '000628', '000629', '000630', '000631', '000632', '000633', '000635', '000636',
                '000637', '000638', '000639', '000650', '000651', '000652', '000655', '000656', '000657',
                '000659', '000661', '000662', '000663', '000665', '000666', '000667', '000668', '000669',
                '000670', '000671', '000672', '000673', '000676', '000677', '000678', '000679', '000680',
                '000681', '000682', '000683', '000685', '000686', '000687', '000688', '000690', '000691',
                '000692', '000693', '000695', '000697', '000698', '000700', '000701', '000702', '000703',
                '000705', '000707', '000708', '000709', '000710', '000711', '000712', '000713', '000715',
                '000716', '000717', '000718', '000719', '000720', '000721', '000722', '000723', '000725',
                '000726', '000727', '000728', '000729', '000730', '000731', '000732', '000733', '000735',
                '000736', '000737', '000738', '000739', '000748', '000750', '000751', '000752', '000753',
                '000755', '000756', '000757', '000758', '000759', '000760', '000761', '000762', '000763',
                '000766', '000767', '000768', '000769', '000776', '000777', '000778', '000779', '000780',
                '000782', '000783', '000785', '000786', '000788', '000789', '000790', '000791', '000792',
                '000793', '000795', '000796', '000797', '000798', '000799', '000800', '000801', '000802',
                '000803', '000806', '000807', '000809', '000810', '000811', '000812', '000813', '000815',
                '000816', '000818', '000819', '000820', '000821', '000822', '000823', '000825', '000826',
                '000828', '000829', '000830', '000831', '000833', '000835', '000836', '000837', '000838',
                '000839', '000848', '000850', '000851', '000852', '000856', '000858', '000859', '000860',
                '000861', '000862', '000863', '000868', '000869', '000875', '000876', '000877', '000878',
                '000880', '000881', '000882', '000883', '000885', '000886', '000887', '000888', '000889',
                '000890', '000892', '000893', '000895', '000897', '000898', '000899', '000900', '000901',
                '000902', '000903', '000905', '000906', '000908', '000909', '000910', '000911', '000912',
                '000913', '000915', '000916', '000917', '000918', '000919', '000920', '000921', '000922',
                '000923', '000925', '000926', '000927', '000928', '000929', '000930', '000931', '000932',
                '000933', '000935', '000936', '000937', '000938', '000939', '000948', '000949', '000950',
                '000951', '000952', '000953', '000955', '000957', '000958', '000959', '000960', '000961',
                '000962', '000963', '000965', '000966', '000967', '000968', '000969', '000970', '000971',
                '000972', '000973', '000975', '000976', '000977', '000978', '000979', '000980', '000981',
                '000982', '000983', '000985', '000987', '000988', '000989', '000990', '000993', '000995',
                '000996', '000997', '000998', '000999'
            ]
        })

def main():
    print("📈 扩大股票池 - 下载更多股票数据（包含pre_close字段）")
    print("="*60)
    
    # 连接数据库
    client = pymongo.MongoClient('localhost', 27017)
    db = client['stock_agent']
    collection = db['stock_daily_ak_full']
    
    # 获取股票列表
    stock_info = get_stock_list()
    target_codes = stock_info['code'].head(TARGET_STOCK_COUNT).tolist()
    print(f"将下载 {len(target_codes)} 只股票数据")
    print(f"时间范围: {START_DATE} ~ {END_DATE}")
    
    # 统计
    total_downloaded = 0
    total_stocks = 0
    failed_stocks = []
    
    # 下载数据
    for code in tqdm(target_codes, desc="下载进度"):
        try:
            # 转换为AKShare格式
            if code.startswith('6'):
                symbol = f"sh{code}"
                ts_code = f"{code}.SH"
            else:
                symbol = f"sz{code}"
                ts_code = f"{code}.SZ"
            
            # 检查是否已存在
            existing_count = collection.count_documents({'ts_code': ts_code})
            if existing_count >= 40:  # 已有足够数据，跳过
                continue
            
            # 下载数据
            df = get_akshare_stock_daily_ak_full(symbol, START_DATE, END_DATE)
            
            if df is not None and len(df) > 0:
                # 转换为记录
                records = []
                for idx, row in df.iterrows():
                    # 跳过第一个交易日（没有pre_close）
                    if pd.isna(row['pre_close']):
                        continue
                    
                    record = {
                        '_id': f"{ts_code}_{row['trade_date']}",
                        'ts_code': ts_code,
                        'trade_date': int(row['trade_date']),
                        'open': float(row['open']),
                        'high': float(row['high']),
                        'low': float(row['low']),
                        'close': float(row['close']),
                        'vol': float(row['vol']),
                        'amount': float(row['amount']),  # 已经是万元
                        'up_limit': float(row['up_limit']),
                        'down_limit': float(row['down_limit']),
                        'pre_close': float(row['pre_close']),  # 新增字段
                    }
                    records.append(record)
                
                if records:
                    # 批量插入
                    collection.insert_many(records, ordered=False)
                    total_downloaded += len(records)
                    total_stocks += 1
            
            # 限流
            time.sleep(0.2)
        
        except Exception as e:
            failed_stocks.append((code, str(e)))
            time.sleep(0.5)
    
    # 统计结果
    print("\n📊 下载结果统计:")
    print(f"成功下载股票数: {total_stocks} 只")
    print(f"新增记录数: {total_downloaded} 条")
    
    if failed_stocks:
        print(f"\n失败股票数: {len(failed_stocks)} 只")
        for code, error in failed_stocks[:5]:
            print(f"  {code}: {error[:50]}...")
    
    # 验证数据
    print("\n🔍 验证数据:")
    
    # 检查总记录数
    total_records = collection.count_documents({})
    unique_stocks = len(collection.distinct('ts_code'))
    unique_dates = len(collection.distinct('trade_date'))
    
    print(f"总记录数: {total_records}")
    print(f"唯一股票数: {unique_stocks}")
    print(f"唯一交易日数: {unique_dates}")
    
    # 检查字段完整性
    sample = collection.find_one()
    if sample:
        print("\n字段完整性检查:")
        fields = list(sample.keys())
        required_fields = ['ts_code', 'trade_date', 'open', 'high', 'low', 'close', 'vol', 'amount', 'up_limit', 'down_limit', 'pre_close']
        
        for field in required_fields:
            if field in fields:
                print(f"  ✅ {field}: 存在")
            else:
                print(f"  ❌ {field}: 缺失")
    
    # 检查涨停股票
    print("\n📈 涨停股票检查:")
    dates_to_check = sorted(collection.distinct('trade_date'))[:5]  # 前5个交易日
    
    total_limit_up = 0
    for date in dates_to_check:
        count = 0
        cursor = collection.find({'trade_date': date})
        for record in cursor:
            close = record.get('close', 0)
            up_limit = record.get('up_limit', 0)
            if abs(close - up_limit) < 0.001 and up_limit > 0:
                count += 1
        
        print(f"  交易日 {date}: {count} 只涨停")
        total_limit_up += count
    
    print(f"  前5个交易日总计涨停: {total_limit_up} 只")
    
    if total_limit_up > 0:
        print("\n🎉 成功找到涨停股票! 现在可以重新运行回测了!")
    else:
        print("\n⚠️  前5个交易日没有涨停股票，可能需要检查更多日期")
    
    client.close()
    
    print("\n✅ 下载完成!")
    print("="*60)
    
    if total_limit_up > 0:
        print("🎯 下一步: 运行回测验证策略信号")
    else:
        print("🎯 下一步: 扩大股票池或调整时间范围")

if __name__ == "__main__":
    main()