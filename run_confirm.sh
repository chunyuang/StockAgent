#!/usr/bin/expect

set timeout 3600

spawn python3 run_backtest_wizard.py --config backtest_five_short_20251215_20260318_20260327.json

expect "确认配置正确，开始回测? \[Y/n\] "

send "y\r"

expect eof
