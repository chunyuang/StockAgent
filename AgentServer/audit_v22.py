#!/usr/bin/env python3
"""V22 backtest audit: Deep code analysis"""
import re

with open('nodes/backtest_engine/factor_selection/portfolio_backtest.py') as f:
    code = f.read()

lines = code.split('\n')

print('=== V22 BACKTEST AUDIT: CODE ANALYSIS ===')
print()

# 1. T+1 enforcement consistency
print('1. T+1 Enforcement (cost_basis_date check):')
for i, line in enumerate(lines, 1):
    if 'cost_basis_date' in line and 'trade_date' in line and '==' in line:
        print(f'  L{i}: {line.strip()[:100]}')

print()
# 2. _check_early_sell_signals strategy coverage
print('2. _check_early_sell_signals strategy coverage:')
in_method = False
for i, line in enumerate(lines, 1):
    if 'def _check_early_sell_signals' in line:
        in_method = True
    elif in_method and 'def ' in line and '_check_early_sell' not in line:
        in_method = False
    if in_method and 'sname ==' in line:
        print(f'  L{i}: {line.strip()[:80]}')

print()
# 3. Inconsistent stop_loss/take_profit logic between _rebalance and _process_non_rebalance_day
print('3. Stop-loss/take-profit: _rebalance vs _process_non_rebalance_day:')
for i, line in enumerate(lines, 1):
    if 'stop_price = cost' in line or 'tp_price = cost' in line:
        print(f'  L{i}: {line.strip()[:80]}')

print()
# 4. _prev_day_close: Check when it gets populated vs used
print('4. _prev_day_close usage:')
for i, line in enumerate(lines, 1):
    if '_prev_day_close' in line and 'self.' in line:
        print(f'  L{i}: {line.strip()[:100]}')

print()
# 5. MongoDB queries in daily loop (performance concern)
print('5. MongoDB queries in _process_rebalance_day (daily loop):')
for i, line in enumerate(lines, 1):
    if 'await mongo_manager' in line:
        print(f'  L{i}: {line.strip()[:100]}')

print()
# 6. Missing strategy-level max_hold_days in _rebalance
print('6. max_hold_days calculation in _rebalance:')
for i, line in enumerate(lines, 1):
    if 'max_hold' in line.lower() and ('days' in line.lower() or 'day' in line.lower()):
        if 'strategy' in line.lower() or 'strategies' in line.lower():
            print(f'  L{i}: {line.strip()[:100]}')

print()
# 7. Inconsistent slippage for force_empty
print('7. Force empty sell - slippage check:')
for i, line in enumerate(lines, 1):
    if 'force_empty' in line.lower() and 'slippage' in line.lower():
        print(f'  L{i}: {line.strip()[:100]}')

print()
# 8. Strategy-level stop_loss parameters check
print('8. Strategy risk params propagation:')
for i, line in enumerate(lines, 1):
    if '_strategy_risk_params' in line and '=' in line and 'self.' in line:
        print(f'  L{i}: {line.strip()[:100]}')
