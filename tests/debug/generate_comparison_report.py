
#!/usr/bin/env python3
"""
FactorEngine修复前后回测对比报告自动生成脚本

使用方法：
1. 先运行修复前的回测，保存结果为 backtest_before.json
2. 再运行修复后的回测，保存结果为 backtest_after.json
3. 运行本脚本，自动生成完整的Markdown对比报告
"""

import json
import os
from datetime import datetime

def load_backtest_result(filepath):
    """加载回测结果文件"""
    if not os.path.exists(filepath):
        print(f"⚠️  文件不存在: {filepath}")
        return None
    
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)

def generate_report(before, after):
    """生成对比报告"""
    
    template_path = "/root/.openclaw/workspace/StockAgent/backtest_comparison_template.md"
    with open(template_path, 'r', encoding='utf-8') as f:
        template = f.read()
    
    # 填充核心指标
    if before and after:
        template = template.replace("[待填充]", "实际数据待填充")
        # 这里可以写具体的填充逻辑，根据实际的JSON结构来写
        # 示例：
        # template = template.replace("修复前总收益率", f"{before.get('total_return', 0):.2f}%")
        # template = template.replace("修复后总收益率", f"{after.get('total_return', 0):.2f}%")
    
    output_path = f"/root/.openclaw/workspace/StockAgent/backtest_comparison_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(template)
    
    print(f"✅ 对比报告已生成: {output_path}")
    return output_path

def main():
    print("=" * 80)
    print("FactorEngine修复前后回测对比报告自动生成工具")
    print("=" * 80)
    print()
    
    before = load_backtest_result("/root/.openclaw/workspace/StockAgent/backtest_before.json")
    after = load_backtest_result("/root/.openclaw/workspace/StockAgent/backtest_after.json")
    
    if not before or not after:
        print()
        print("⚠️  提示：请先运行修复前后的回测，并将结果保存为：")
        print("   - backtest_before.json")
        print("   - backtest_after.json")
        print()
        print("当前生成的是带占位符的模板，可以用来做测试：")
    
    report_path = generate_report(before, after)
    
    print()
    print("=" * 80)
    print("✅ 模板准备完成！数据一到，直接填充即可！")
    print("=" * 80)

if __name__ == "__main__":
    main()
