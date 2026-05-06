#!/usr/bin/env python3
"""
实盘绩效报告生成器
生成模拟账户的详细绩效报告
"""
import sys
import logging

logger = logging.getLogger(__name__)
import os
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'AgentServer'))  # FIXME: 使用sys.path.insert做模块查找是反模式，应改用setup.py/pyproject.toml将项目安装到venv中
sys.path.insert(0, os.path.dirname(__file__))

from paper_trading import PaperTradingEngine
from performance_analyzer import PerformanceAnalyzer

def generate_report(account_id: str = None, output_format: str = "text"):
    """生成模拟账户绩效报告
    
    从PaperTradingEngine和PerformanceAnalyzer获取数据，
    生成包含账户概览、当前持仓、绩效指标的Markdown报告。
    
    Args:
        account_id: 账户ID，None则列出所有活跃账户供选择
        output_format: 输出格式 'text'-纯文本 / 'markdown'-Markdown格式
    
    Returns:
        str: 报告内容文本，账户不存在或未指定时返回None
    """
    engine = PaperTradingEngine()
    
    if not account_id:
        # 列出所有活跃账户
        logger.info("📋 可用模拟账户：")
        for acc_id, acc in engine.accounts.items():
            if acc.status == "active":
                logger.info(f"  - {acc.name} ({acc_id})：余额{acc.current_balance:.2f}元，收益{acc.total_profit_pct:.2f}%")
        return
    
    if account_id not in engine.accounts:
        logger.error(f"❌ 账户{account_id}不存在")
        return
    
    account = engine.accounts[account_id]
    pos_manager = engine.position_managers[account_id]
    positions = pos_manager.get_positions()
    
    # 生成报告内容
    report = [
        f"# 📊 {account.name} 绩效报告",
        f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## 🏦 账户概览",
        f"- 账户ID：{account.account_id}",
        f"- 创建时间：{account.created_at}",
        f"- 初始资金：{account.initial_balance:.2f}元",
        f"- 当前余额：{account.current_balance:.2f}元",
        f"- 总收益：{account.total_profit:.2f}元（{account.total_profit_pct:.2f}%）",
        f"- 最大回撤：{account.max_drawdown:.2f}%",
        f"- 状态：{'活跃' if account.status == 'active' else '已关闭'}",
        "",
        "## 📈 当前持仓",
    ]
    
    if positions:
        report.append(f"共持有 {len(positions)} 只股票：")
        report.append("| 股票代码 | 持仓数量 | 成本价 | 当前市值 | 收益 | 收益率 |")
        report.append("|----------|----------|--------|----------|------|--------|")
        total_market_value = 0
        for pos in positions:
            # 从MongoDB获取当前价格（字典访问，get_positions返回dict）
            cost = pos.get("buy_price", pos.get("cost_price", 0))
            try:
                import pymongo
                from core.settings import settings as _s
                _client = pymongo.MongoClient(_s.mongo.url)
                _db = _client[_s.mongo.database]
                doc = _db.stock_daily_ak_full.find_one({"ts_code": pos["ts_code"]}, sort=[("trade_date", -1)])
                _client.close()
                current_price = doc["close"] if doc and doc.get("close", 0) > 0 else cost
            except Exception:
                current_price = cost
            market_value = pos["shares"] * current_price
            total_market_value += market_value
            profit = market_value - (pos["shares"] * cost)
            profit_pct = profit / (pos["shares"] * cost) * 100 if (pos["shares"] * cost) > 0 else 0
            
            report.append(f"| {pos['ts_code']} | {pos['shares']} | {cost:.2f} | {market_value:.2f} | {profit:.2f} | {profit_pct:.2f}% |")
        
        report.append(f"\n总持仓市值：{total_market_value:.2f}元，仓位：{total_market_value/account.current_balance*100:.1f}%" if account.current_balance > 0 else f"\n总持仓市值：{total_market_value:.2f}元")
    else:
        report.append("当前空仓，无持仓股票")
    
    # 绩效分析
    analyzer = PerformanceAnalyzer()
    performance = analyzer.get_basic_stats()
    report.extend([
        "",
        "## 📊 绩效指标",
        f"- 胜率：{performance.get('win_rate', 0):.2f}%",
        f"- 盈亏比：{performance.get('profit_loss_ratio', 0):.2f}",
        f"- 夏普比率：{performance.get('sharpe_ratio', 0):.2f}",
        f"- 最大回撤：{performance.get('max_drawdown', account.max_drawdown):.2f}%",
        f"- 总交易次数：{performance.get('total_trades', 0)}次",
        f"- 盈利次数：{performance.get('win_trades', 0)}次",
        f"- 亏损次数：{performance.get('loss_trades', 0)}次",
    ])
    
    report_content = "\n".join(report)
    
    if output_format == "markdown":
        logger.info(report_content)
    else:
        # 纯文本格式，去掉markdown标记
        text = report_content.replace("#", "").replace("##", "").replace("|", " ").replace("---", "")
        logger.info(text)
    
    return report_content

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="实盘绩效报告生成器")
    parser.add_argument("--account", help="指定账户ID")
    parser.add_argument("--format", choices=["text", "markdown"], default="text", help="输出格式")
    args = parser.parse_args()
    
    generate_report(args.account, args.format)
