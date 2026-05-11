import subprocess, time, os, signal, sys

# 启动回测进程
proc = subprocess.Popen(
    [sys.executable, '-u', 'scripts/run_2year_backtest.py'],
    stdout=open('/tmp/backtest_2y.log', 'w'),
    stderr=subprocess.STDOUT,
    cwd='/root/.openclaw/workspace/StockAgent/AgentServer'
)

print(f"回测PID: {proc.pid}", flush=True)

# 监控内存
while proc.poll() is None:
    try:
        with open(f'/proc/{proc.pid}/status') as f:
            for line in f:
                if line.startswith('VmRSS:'):
                    rss_kb = int(line.split()[1])
                    print(f"[{time.strftime('%H:%M:%S')}] PID {proc.pid} RSS: {rss_kb/1024:.0f}MB", flush=True)
                    break
    except:
        pass
    time.sleep(30)

print(f"进程退出码: {proc.returncode}", flush=True)
