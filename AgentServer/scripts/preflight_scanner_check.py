#!/usr/bin/env python3
"""
开盘前Scanner就绪检查 — 09:25执行

检测项:
1. scanner进程存活
2. scanner._is_running == True
3. scan_loop实际在跑 (scan_count>0 或 last_scan_time非空)
4. 持仓数 <= MAX_POSITIONS
5. position-risk-matrix API返回非空
6. 风控线程存活

如果_is_running=True但scan_loop没跑 -> 自动stop/start自愈
如果持仓超限 -> 告警(不自动卖)
"""

import sys, os, json, time, requests, logging
from datetime import datetime

os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, '.')

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
logger = logging.getLogger("preflight")

API_BASE = "http://localhost:8000/api/v1"
MAX_POSITIONS = 8  # v2.9.124: 硬上限从10->8

def get_scanner_status() -> dict:
    """获取scanner完整状态"""
    try:
        resp = requests.get(f"{API_BASE}/scanner/status", timeout=10)
        data = resp.json()
        return data.get('data', data)
    except Exception as e:
        logger.error(f"无法连接API: {e}")
        return {}

def get_position_risk_matrix() -> dict:
    """获取风控矩阵"""
    try:
        resp = requests.get(f"{API_BASE}/scanner/position-risk-matrix", timeout=10)
        data = resp.json()
        return data.get('data', {})
    except Exception as e:
        logger.error(f"无法获取风控矩阵: {e}")
        return {}

def is_trading_day() -> bool:
    """简单判断是否交易日(周一-周五)"""
    return datetime.now().weekday() < 5

def is_premarket_time() -> bool:
    """09:20-09:30之间"""
    now = datetime.now()
    h, m = now.hour, now.minute
    return h == 9 and 20 <= m <= 30

def auto_heal_false_running():
    """自愈: _is_running=True但scan_loop没跑 -> stop/start"""
    logger.warning("检测到scanner假运行, 尝试自愈(stop+start)...")
    try:
        # stop
        resp = requests.post(f"{API_BASE}/scanner/stop", json={}, timeout=15)
        logger.info(f"stop响应: {resp.json()}")
        time.sleep(3)
        # start
        resp = requests.post(f"{API_BASE}/scanner/start", json={}, timeout=15)
        logger.info(f"start响应: {resp.json()}")
        time.sleep(8)
        # 验证
        status = get_scanner_status()
        if status.get('is_running') and status.get('scan_count', 0) > 0:
            logger.info("✅ 自愈成功: scanner已恢复扫描")
            return True
        else:
            logger.error(f"❌ 自愈后仍异常: is_running={status.get('is_running')}, scan_count={status.get('scan_count')}")
            return False
    except Exception as e:
        logger.error(f"自愈失败: {e}")
        return False

def run_check():
    """执行就绪检查, 返回(通过, 问题列表)"""
    issues = []
    
    # 1. API连通性
    status = get_scanner_status()
    if not status:
        issues.append("[P0] API不可达 - web进程可能未启动")
        return False, issues
    
    # 2. scanner是否运行
    is_running = status.get('is_running', False)
    scan_count = status.get('scan_count', 0)
    last_scan_time = status.get('last_scan_time', '')
    
    if not is_running:
        # 明确未运行, 尝试启动
        logger.warning("scanner未运行, 尝试启动...")
        try:
            resp = requests.post(f"{API_BASE}/scanner/start", json={}, timeout=15)
            logger.info(f"start响应: {resp.json()}")
            time.sleep(12)  # 等待async start()完成
            status = get_scanner_status()
            if not status.get('is_running'):
                issues.append("[P0] 启动后is_running仍为False")
                return False, issues
        except Exception as e:
            issues.append(f"[P0] 启动异常: {e}")
            return False, issues
    else:
        # is_running=True, 检查是否假运行
        # 假运行: _is_running=True但scan_count=0且last_scan_time为空
        # (start API内部也会检测, 但这里提前检测更快)
        now = datetime.now()
        h, m = now.hour, now.minute
        is_after_open = h > 9 or (h == 9 and m >= 30)
        
        if is_after_open and scan_count == 0 and not last_scan_time:
            issues.append("[P0] scanner假运行: is_running=True但scan_count=0, 尝试自愈...")
            if auto_heal_false_running():
                issues.append("[P0] 自愈成功")
                status = get_scanner_status()
            else:
                issues.append("[P0] 自愈失败, 需人工介入")
                return False, issues
    
    # 4. 持仓数检查
    positions = status.get('positions', [])
    if isinstance(positions, list):
        pos_count = len(positions)
    else:
        pos_count = positions  # 有时返回的是数字
    
    if pos_count > MAX_POSITIONS:
        issues.append(f"[P1] 持仓超限: {pos_count}只 > MAX_POSITIONS={MAX_POSITIONS}")
    
    # 5. 风控矩阵API
    matrix = get_position_risk_matrix()
    matrix_positions = matrix.get('positions', [])
    if not matrix_positions:
        issues.append("[P1] 风控矩阵返回空 - 前端将无数据")
    else:
        # 检查关键字段
        for p in matrix_positions:
            if p.get('cost_price') is None:
                issues.append(f"[P1] {p.get('ts_code')} cost_price=None - 盈亏计算将异常")
                break
    
    # 6. 风控线程
    rw = status.get('risk_watchdog', {})
    if rw:
        heartbeat_age = rw.get('scanner_heartbeat_age', 999)
        if isinstance(heartbeat_age, (int, float)) and heartbeat_age > 60:
            issues.append(f"[P1] 风控线程心跳超时: {heartbeat_age}秒")
    
    return len(issues) == 0, issues

def main():
    logger.info(f"=== 开盘前就绪检查 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===")
    
    if not is_trading_day():
        logger.info("非交易日, 跳过")
        return
    
    ok, issues = run_check()
    
    if ok:
        logger.info("✅ 全部通过, scanner就绪")
        print(json.dumps({"success": True, "issues": [], "message": "scanner就绪"}, ensure_ascii=False))
    else:
        logger.error(f"❌ 发现{len(issues)}个问题:")
        for issue in issues:
            logger.error(f"  {issue}")
        print(json.dumps({"success": False, "issues": issues, "message": "scanner未就绪"}, ensure_ascii=False))

if __name__ == '__main__':
    main()
