#!/usr/bin/env python3
import sys
import run_backtest_wizard

# 预设置所有配置
sys.argv = ['run_backtest_wizard.py', '--config', '/root/.openclaw/workspace/akshare-five-short-backtest-20260105-20260320.json']

# 猴子补丁input，自动确认
original_input = __builtins__.input
def patched_input(prompt):
    print(prompt)
    return ""  # 空回车就是确认

__builtins__.input = patched_input

# 运行
wizard = run_backtest_wizard.BacktestWizard()
wizard.run()
