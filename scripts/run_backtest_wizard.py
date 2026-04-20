#!/usr/bin/env python3
"""
StockAgent 交互式回测启动向导

分步引导用户确认所有配置，检查数据完整性，确保不缺数据再启动回测。
"""

import sys
from datetime import datetime
import pymongo
from typing import List, Tuple

sys.path.insert(0, '/root/.openclaw/workspace/StockAgent/AgentServer')

from core.settings import settings

class BacktestWizard:
    def __init__(self):
        self.data_source = None  # 1: tushare, 2: akshare, 3: local-mongo
        self.start_date = None
        self.end_date = None
        self.strategy_type = None  # A: 五大超短, B: 因子选股, C: 情绪周期
        self.liquidity_threshold = 1000  # 流动性门槛 (单位: 万元) 默认 1000万
        self.initial_capital = 10000000  # 初始本金 (单位: 元) 默认 1000万 = 10,000,000
        self.max_workers = 5  # 最大并发数，默认 5
        self.enable_checkpoint = True  # 断点续传，默认开启
        self.verbose = False  # 详细日志，默认关闭
        self.save_config = True  # 保存配置方便复用，默认开启
        self.upload_to_feishu = None  # 是否上传报告到飞书
        self.mongo_client = None
        self.db = None
    
    def print_banner(self):
        print("="*60)
        print("🚀 StockAgent 交互式回测启动向导")
        print("="*60)
        print()
    
    def select_data_source(self, default: int = 3) -> int:
        print("📌 第一步: 选择数据源")
        print()
        print("  [1] Tushare - 按股票获取完整历史，需要 Token")
        print("  [2] AKShare - 按日期批量获取，免费无需 Token")
        print("  [3] 本地 MongoDB 直接使用 (数据已经下载好了) → 推荐")
        print()
        print(f"  默认: {default} → 直接回车")
        
        while True:
            choice = input("请选择 [1/2/3] (默认 {default}): ").strip()
            if not choice:
                return default
            if choice in ["1","2","3"]:
                return int(choice)
            print("❌ 请输入 1, 2 或 3")
    
    def confirm_date_range(self, default_start: str = "20251215", default_end: str = "20260318") -> Tuple[str, str]:
        print()
        print("📌 第二步: 确认回测区间")
        print()
        print(f"  默认: {default_start} ~ {default_end} (近三个月)")
        print("  格式: YYYYMMDD YYYYMMDD，例如: 20251215 20260318")
        print()
        print(f"  默认: {default_start} {default_end} → 直接回车")
        
        while True:
            choice = input("请输入回测区间 (回车使用默认): ").strip()
            if not choice:
                return default_start, default_end
            
            parts = choice.split()
            if len(parts) == 2:
                start, end = parts
                if len(start) == 8 and len(end) == 8:
                    return start, end
            
            print("❌ 格式错误，请重新输入")
    
    def select_strategy(self, default: str = "A") -> str:
        print()
        print("📌 第三步: 选择策略组合")
        print()
        print("  [A] 五大超短策略 (半路追涨/涨停开板/龙头战法/首板打板)")
        print("  [B] StockAgent-v0.2 因子选股 (月度调仓，top 50 选股)")
        print("  [C] 情绪周期策略 (需要涨跌停/基本面/龙虎榜数据)")
        print()
        print(f"  默认: {default} → 直接回车")
        
        while True:
            choice = input("请选择 [A/B/C] (默认 {default}): ").strip().upper()
            if not choice:
                return default
            if choice in ["A", "B", "C"]:
                return choice
            print("❌ 请输入 A, B 或 C")

    def confirm_liquidity_threshold(self, default: int = 1000) -> int:
        print()
        print("📌 第五步: 流动性门槛")
        print()
        print("  排除成交额低于门槛的股票，确保流动性")
        print("  单位: 万元")
        print("  推荐:")
        print("    1000  →  1000万 (推荐，适合大资金)")
        print("     500  →   500万")
        print("     200  →   200万")
        print("       0  →  不限制")
        print()
        print(f"  默认: {default} → 直接回车")
        
        while True:
            choice = input(f"请输入流动性门槛 (万元) (默认 {default}): ").strip()
            if not choice:
                return default
            try:
                val = int(choice)
                if val >= 0:
                    return val
                print("❌ 请输入大于等于 0 的数字")
            except:
                print("❌ 请输入有效的数字")
    
    def confirm_initial_capital(self, default: int = 1000) -> int:
        print()
        print("📌 第六步: 初始本金")
        print()
        print("  回测初始本金")
        print("  单位: 万元")
        print("  默认: 1000 → 1000万元")
        print()
        print(f"  默认: {default} → 直接回车")
        
        while True:
            choice = input(f"请输入初始本金 (万元) (默认 {default}): ").strip()
            if not choice:
                return default * 10000  # 转换为元
            try:
                val = int(choice)
                if val > 0:
                    return val * 10000  # 转换为元
                print("❌ 请输入大于 0 的数字")
            except:
                print("❌ 请输入有效的数字")

    def confirm_concurrency(self, default: int = 5) -> int:
        print()
        print("📌 第七步: 最大并发数")
        print()
        print("  每日选股因子计算并发数")
        print("  推荐:")
        print("    1 → 串行，最慢，稳定")
        print("    5 → 默认，平衡速度")
        print("   10 → 较快")
        print("   20 → 最快 (看 CPU 核心)")
        print()
        print(f"  默认: {default} → 直接回车")
        
        while True:
            choice = input(f"请输入并发数 (默认 {default}): ").strip()
            if not choice:
                return default
            try:
                val = int(choice)
                if val >= 1:
                    return val
                print("❌ 请输入大于等于 1 的整数")
            except:
                print("❌ 请输入有效的整数")

    def confirm_verbose_log(self, default: bool = False) -> bool:
        print()
        print("📌 第八步: 详细日志输出")
        print()
        print("  [N] 默认关闭 - 只输出进度，减少日志")
        print("  [Y] 开启 - 输出详细调试信息")
        print()
        default_str = "N" if not default else "Y"
        print(f"  默认: {default_str} → 直接回车")
        
        while True:
            choice = input(f"请选择 [Y/n] (默认 {default_str}): ").strip().lower()
            if not choice:
                return default
            if choice in ["y", "yes", "n", "no"]:
                return choice in ["y", "yes"]
            print("❌ 请输入 y 或 n")

    def confirm_checkpoint(self, default: bool = True) -> bool:
        print()
        print("📌 第九步: 断点续传")
        print()
        print("  [Y] 默认开启 - 回测中断后可以从断点继续")
        print("  [N] 关闭 - 从头开始")
        print()
        default_str = "Y" if default else "N"
        print(f"  默认: {default_str} → 直接回车")
        
        while True:
            choice = input(f"请选择 [Y/n] (默认 {default_str}): ").strip().lower()
            if not choice:
                return default
            if choice in ["y", "yes", "n", "no"]:
                return choice in ["y", "yes"]
            print("❌ 请输入 y 或 n")

    def confirm_save_config(self, default: bool = True) -> bool:
        print()
        print("📌 第十步: 保存配置")
        print()
        print("  [Y] 默认开启 - 保存配置到 JSON 文件，方便下次复用")
        print("  [N] 关闭 - 不保存配置")
        print()
        default_str = "Y" if default else "N"
        print(f"  默认: {default_str} → 直接回车")
        
        while True:
            choice = input(f"请选择 [Y/n] (默认 {default_str}): ").strip().lower()
            if not choice:
                return default
            if choice in ["y", "yes", "n", "no"]:
                return choice in ["y", "yes"]
            print("❌ 请输入 y 或 n")

    def confirm_upload_feishu(self, default: bool = True) -> bool:
        print()
        print("📌 第十一步: 回测报告上传飞书")
        print()
        print("  回测完成后，是否自动将报告上传到飞书云文档？")
        print("  [Y] 是 - 自动上传，命名遵循规范")
        print("  [N] 否 - 只在本地生成，不上传")
        print()
        default_str = "Y" if default else "N"
        print(f"  默认: {default_str} → 直接回车")
        
        while True:
            choice = input("请选择 [Y/n] (默认 {default_str}): ").strip().lower()
            if not choice:
                return default
            if choice in ["y", "yes", "n", "no"]:
                return choice in ["y", "yes"]
            print("❌ 请输入 y 或 n")
    
    def connect_mongo(self):
        """连接 MongoDB"""
        self.mongo_client = pymongo.MongoClient(settings.mongo.url)
        self.db = self.mongo_client[settings.mongo.database]
        print()
        print("✅ MongoDB 连接成功")
    
    def check_data_integrity(self) -> Tuple[bool, List[str]]:
        print()
        print("📌 第四步: 数据完整性检查")
        print()
        
        required = []
        missing = []
        
        # 根据策略类型确定需要检查什么
        if self.strategy_type == "A":
            # 五大超短只需要 stock_daily_ak_full
            required = [
                ("stock_daily_ak_full", ["trade_date", "ts_code", "open", "high", "low", "close", 
                             "pre_close", "vol", "amount", "up_limit", "down_limit"],
             "stock_daily_ak_full - 日线行情（含涨跌停价）")
            ]
        elif self.strategy_type == "B":
            # 因子选股需要 stock_daily_ak_full + daily_basic + fina_indicator
            required = [
                ("stock_daily_ak_full", ["trade_date", "ts_code", "open", "high", "low", "close", 
                             "pre_close", "vol", "amount", "up_limit", "down_limit"],
             "stock_daily_ak_full - 日线行情"),
                ("daily_basic", ["trade_date", "ts_code", "pe", "pe_ttm", "pb", "total_mv", "turnover_rate"],
             "daily_basic - 每日基本面"),
                ("fina_indicator", ["ts_code", "end_date", "roe", "revenue_yoy", "netprofit_yoy"],
             "fina_indicator - 财务指标"),
            ]
        elif self.strategy_type == "C":
            # 情绪周期需要更多数据
            required = [
                ("stock_daily_ak_full", ["trade_date", "ts_code", "open", "high", "low", "close", 
                             "pre_close", "vol", "amount", "up_limit", "down_limit"],
             "stock_daily_ak_full - 日线行情"),
                ("limit_list", ["trade_date", "ts_code", "limit"],
             "limit_list - 涨跌停列表（情绪周期核心）"),
                ("daily_basic", ["trade_date", "ts_code", "pe", "pe_ttm", "pb", "total_mv", "turnover_rate"],
             "daily_basic - 每日基本面"),
                ("lhb", ["trade_date", "ts_code", "net_buy"],
             "lhb - 龙虎榜（情绪周期辅助）"),
            ]
        
        # 执行检查
        all_ok = True
        
        for collection_name, required_fields, description in required:
            print(f"  检查 {description} ... ", end="", flush=True)
            
            # 检查集合是否存在且有数据
            if collection_name not in self.db.list_collection_names():
                print(f"\n  ❌ 集合 [{collection_name}] 不存在")
                missing.append(f"集合 {collection_name} 不存在")
                all_ok = False
                continue
            
            # 统一转换为int查询，因为我们存储的是int
            start_int = int(self.start_date)
            end_int = int(self.end_date)
            count = self.db[collection_name].count_documents({
                "trade_date": {"$gte": start_int, "$lte": end_int}
            })
            
            if count == 0:
                print(f"\n  ❌ 集合 [{collection_name}] 在区间 {self.start_date} ~ {self.end_date} 内 0 条记录")
                missing.append(f"{collection_name}: 区间内 0 条记录")
                all_ok = False
                continue
            
            # 检查抽样一条看字段是否存在
            sample = self.db[collection_name].find_one({
                "trade_date": {"$gte": start_int, "$lte": end_int}
            })
            
            missing_fields = []
            for f in required_fields:
                if sample is None or f not in sample:
                    missing_fields.append(f)
            
            if missing_fields:
                print(f"\n  ❌ 缺少字段: {', '.join(missing_fields)}")
                missing.append(f"{collection_name}: 缺少字段 {', '.join(missing_fields)}")
                all_ok = False
                continue
            
            print(f"✓ OK ({count} 条记录)")
        
        # 检查涨跌停价补全 (只对 stock_daily_ak_full 需要)
        if "stock_daily_ak_full" in [x[0] for x in required]:
            print("  检查涨跌停价完整性 ... ", end="", flush=True)
            # 统一转换为int查询，因为我们存储的是int
            start_int = int(self.start_date)
            end_int = int(self.end_date)
            count_missing = self.db['stock_daily_ak_full'].count_documents({
                "trade_date": {"$gte": start_int, "$lte": end_int},
                "$or": [
                    {"up_limit": {"$exists": False}},
                    {"down_limit": {"$exists": False}},
                    {"up_limit": None},
                    {"down_limit": None},
                ]
            })
            if count_missing > 0:
                print(f"⚠️  {count_missing} 条记录缺少 up_limit/down_limit (数量极少，继续回测)")
                print("    需要运行: python StockAgent/download_scripts/add_up_down_limit.py")
                # 缺失条数极少不阻止回测
                if count_missing > 10:
                    missing.append(f"stock_daily_ak_full: {count_missing} 条记录缺少涨跌停价")
                    all_ok = False
            else:
                print("✓ 全部完整")
        
        print()
        if all_ok:
            print("✅ 数据完整性检查通过，可以开始回测!")
        else:
            print("⚠️  发现缺失数据，请先补充下载:")
            print()
            for msg in missing:
                print(f"  - {msg}")
            print()
            print("下载命令参考:")
            if "limit_list" in [m.split(":")[0] for m in missing]:
                print(f"  python StockAgent/download_scripts/download_limit_list_tushare.py {self.start_date} {self.end_date}")
            if "daily_basic" in [m.split(":")[0] for m in missing]:
                print(f"  python StockAgent/download_scripts/download_daily_basic_tushare.py {self.start_date} {self.end_date}")
            if "lhb" in [m.split(":")[0] for m in missing]:
                print(f"  python StockAgent/download_scripts/download_lhb_tushare.py {self.start_date} {self.end_date}")
            if "stock_daily_ak_full" in [m.split(":")[0] for m in missing] and "涨跌停" in "".join(missing):
                print("  python StockAgent/download_scripts/add_up_down_limit.py")
            print()
            print("补充完成后重新运行这个向导即可")
        
        return all_ok, missing
    
    def summary_config(self):
        print()
        print("="*60)
        print("📋 回测配置汇总")
        print("="*60)
        print()
        
        ds_map = {1: "Tushare", 2: "AKShare", 3: "本地 MongoDB"}
        st_map = {"A": "五大超短策略", "B": "StockAgent-v0.2 因子选股", "C": "情绪周期策略"}
        up_map = {True: "是 - 自动上传飞书", False: "否 - 保留本地"}
        
        print(f"  数据源: {ds_map[self.data_source]}")
        print(f"  回测区间: {self.start_date} ~ {self.end_date}")
        print(f"  策略组合: {st_map[self.strategy_type]}")
        print(f"  上传飞书报告: {up_map[self.upload_to_feishu]}")
        print()
        print("📝 报告命名规范:")
        print(f"  文件名: backtest_{st_map[self.strategy_type]}_{self.start_date}_{self.end_date}_YYYYMMDD.md")
        print(f"  日期: {self.start_date}_{self.end_date}")
        print("  时间戳: 回测完成日期 YYYYMMDD (便于区分不同回测)")
        print()
        print("="*60)
        print()
    
    def generate_report_name(self) -> str:
        """生成报告文件名，遵循命名规范:
        backtest_{strategy}_{start}_{end}_{today}.md
        """
        from datetime import datetime
        today = datetime.now().strftime("%Y%m%d")
        st_code = {
            "A": "five_short",
            "B": "factor_v02",
            "C": "emotion_cycle",
        }
        strategy_code = st_code.get(self.strategy_type, "unknown")
        return f"backtest_{strategy_code}_{self.start_date}_{self.end_date}_{today}.md"
    
    def run_backtest(self):
        """启动回测"""
        print("🚀 启动回测...")
        print()
        
        report_name = self.generate_report_name()
        print(f"📝 报告文件名: {report_name}")
        print()
        
        # 导入并运行回测脚本
        if self.strategy_type == "A":
            script = "backtest_module/backtest_engine/scripts/run_strategies_backtest_3months.py"
        elif self.strategy_type == "B":
            script = "backtest_module/backtest_engine/scripts/run_factor_backtest_monthly.py"
        else:  # C
            script = "backtest_module/backtest_engine/scripts/run_emotion_cycle_backtest.py"
        
        # 这里我们直接exec，传递参数
        print(f"执行: {script}")
        print("-"*60)
        print()
        
        # 读取并执行
        with open(script, 'r') as f:
            code = f.read()
        
        # 把参数传到全局
        g = globals()
        g['START_DATE'] = self.start_date
        g['END_DATE'] = self.end_date
        g['REPORT_NAME'] = report_name
        g['UPLOAD_TO_FEISHU'] = self.upload_to_feishu
        exec(code, g)
    
    def load_config_from_file(self, path: str) -> bool:
        """从 JSON 文件加载配置"""
        import json
        try:
            with open(path, 'r') as f:
                config = json.load(f)
            self.data_source = config.get('data_source', self.data_source)
            self.start_date = config.get('start_date', self.start_date)
            self.end_date = config.get('end_date', self.end_date)
            self.strategy_type = config.get('strategy_type', self.strategy_type)
            self.liquidity_threshold = config.get('liquidity_threshold', self.liquidity_threshold)
            self.initial_capital = config.get('initial_capital', self.initial_capital)
            self.max_workers = config.get('max_workers', self.max_workers)
            self.enable_checkpoint = config.get('enable_checkpoint', self.enable_checkpoint)
            self.verbose = config.get('verbose', self.verbose)
            self.save_config = config.get('save_config', self.save_config)
            self.upload_to_feishu = config.get('upload_to_feishu', self.upload_to_feishu)
            print(f"✅ 已从 {path} 加载配置")
            return True
        except Exception as e:
            print(f"❌ 加载配置失败: {e}")
            return False

    def save_current_config(self):
        """保存当前配置到 JSON 文件，方便下次复用"""
        import json
        config = {
            'data_source': self.data_source,
            'start_date': self.start_date,
            'end_date': self.end_date,
            'strategy_type': self.strategy_type,
            'liquidity_threshold': self.liquidity_threshold,
            'initial_capital': self.initial_capital,
            'max_workers': self.max_workers,
            'enable_checkpoint': self.enable_checkpoint,
            'verbose': self.verbose,
            'save_config': self.save_config,
            'upload_to_feishu': self.upload_to_feishu,
            'created_at': datetime.now().isoformat(),
        }
        report_name = self.generate_report_name()
        config_name = report_name.replace('.md', '.json')
        with open(config_name, 'w') as f:
            json.dump(config, f, indent=2)
        print(f"✅ 配置已保存到: {config_name}")
        print(f"  下次启动: python run_backtest_wizard.py --config {config_name}")

    def run(self):
        """运行向导，支持命令行参数默认配置快速启动:
           python run_backtest_wizard.py [data_source] [start_date] [end_date] [strategy] [upload]
           python run_backtest_wizard.py --config config.json
        """
        # 检查是否从配置文件加载
        if len(sys.argv) >= 2 and sys.argv[1] == '--config':
            if len(sys.argv) >= 3:
                self.print_banner()
                loaded = self.load_config_from_file(sys.argv[2])
                if not loaded:
                    return
            else:
                self.print_banner()
                print("❌ 请指定配置文件路径")
                return
        else:
            # 正常交互式/命令行流程
            if len(sys.argv) >= 2:
                # 快速模式：参数都从命令行读取，不用交互式选择
                try:
                    data_source = int(sys.argv[1])
                    if data_source not in [1, 2, 3]:
                        raise ValueError()
                    self.data_source = data_source
                except:
                    self.print_banner()
                    self.data_source = self.select_data_source()
            else:
                self.print_banner()
                self.data_source = self.select_data_source()
            
            if len(sys.argv) >= 4:
                self.start_date = sys.argv[2]
                self.end_date = sys.argv[3]
            else:
                self.start_date, self.end_date = self.confirm_date_range()
            
            if len(sys.argv) >= 5:
                self.strategy_type = sys.argv[4].upper()
            else:
                self.strategy_type = self.select_strategy()
            
            # 新增选项
            if len(sys.argv) >= 6:
                try:
                    self.liquidity_threshold = int(sys.argv[5])
                except:
                    self.liquidity_threshold = self.confirm_liquidity_threshold()
            else:
                self.liquidity_threshold = self.confirm_liquidity_threshold()
            
            if len(sys.argv) >= 7:
                try:
                    initial_capital_wan = int(sys.argv[6])
                    self.initial_capital = initial_capital_wan * 10000
                except:
                    self.initial_capital = self.confirm_initial_capital()
            else:
                self.initial_capital = self.confirm_initial_capital()
            
            if len(sys.argv) >= 8:
                try:
                    self.max_workers = int(sys.argv[7])
                except:
                    self.max_workers = self.confirm_concurrency()
            else:
                self.max_workers = self.confirm_concurrency()
            
            if len(sys.argv) >= 9:
                self.verbose = sys.argv[8].lower() in ['y', 'yes', 'true']
            else:
                self.verbose = self.confirm_verbose_log()
            
            if len(sys.argv) >= 10:
                self.enable_checkpoint = sys.argv[9].lower() in ['y', 'yes', 'true']
            else:
                self.enable_checkpoint = self.confirm_checkpoint()
            
            if len(sys.argv) >= 11:
                self.save_config = sys.argv[10].lower() in ['y', 'yes', 'true']
            else:
                self.save_config = self.confirm_save_config()
            
            if len(sys.argv) >= 12:
                self.upload_to_feishu = sys.argv[11].lower() in ['y', 'yes', 'true']
            else:
                self.upload_to_feishu = self.confirm_upload_feishu()
        
        # 保存配置（如果开启）
        if self.save_config:
            self.save_current_config()
        
        self.connect_mongo()
        
        all_ok, _ = self.check_data_integrity()
        if not all_ok:
            print()
            print("👋 请先补充缺失数据，完成后重新运行向导")
            self.mongo_client.close()
            return
        
        self.summary_config()
        
        confirm = input("确认配置正确，开始回测? [Y/n] ").strip().lower()
        if confirm == "" or confirm == "y" or confirm == "yes":
            self.run_backtest()
        else:
            print("👋 已取消，可以重新运行向导修改配置")
        
        self.mongo_client.close()


if __name__ == "__main__":
    wizard = BacktestWizard()
    wizard.run()
