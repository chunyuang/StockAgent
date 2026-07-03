#!/usr/bin/env python3
"""
数据写入校验工具 - 所有数据写入脚本应调用

用法:
  from scripts.data_write_validator import validate_ak_full, validate_daily_basic
  
  # 写入stock_daily_ak_full前
  errors = validate_ak_full(doc)
  if errors:
      print(f"⚠️ 校验失败: {errors}")
      return  # 跳过写入
  
  # 写入daily_basic前
  errors = validate_daily_basic(doc)
  if errors:
      print(f"⚠️ 校验失败: {errors}")
      return
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


def validate_ak_full(doc: dict, strict: bool = False) -> list[str]:
    """校验stock_daily_ak_full写入数据单位
    
    Args:
        doc: 要写入的文档
        strict: 严格模式(更敏感的阈值)
    
    Returns:
        错误列表(空=通过)
    """
    errors = []
    ts_code = doc.get('ts_code', '?')
    
    # close: 元 (0.01-100000)
    close = doc.get('close', 0)
    if close is not None:
        if close < 0.1 or close > 100000:
            errors.append(f"{ts_code}: close={close} 异常(0.1-100000元)")
    
    # vol: 手 (最小1)
    vol = doc.get('vol', 0)
    if vol is not None and vol < 0:
        errors.append(f"{ts_code}: vol={vol} 异常(手, 不应为负)")
    
    # amount: 百元 (最小1)
    amount = doc.get('amount', 0)
    if amount is not None and amount < 0:
        errors.append(f"{ts_code}: amount={amount} 异常(百元, 不应为负)")
    
    # turnover_rate: 百分数 (0.01-100)
    tr = doc.get('turnover_rate', 0)
    if tr is not None and tr != 0:
        if tr > 100:
            errors.append(f"{ts_code}: turnover_rate={tr}% >100! 可能被×100(应为百分数如5.31)")
        if tr < 0.001 and strict:
            errors.append(f"{ts_code}: turnover_rate={tr}% <0.001! 可能是小数未×100(应为百分数如5.31)")
    
    # volume_ratio: 倍数 (0-50)
    vr = doc.get('volume_ratio', 0)
    if vr is not None and vr != 0:
        if vr > 50:
            errors.append(f"{ts_code}: volume_ratio={vr} >50! 异常")
    
    # circ_mv: 万元 (100-1e8)
    cm = doc.get('circ_mv', 0)
    if cm is not None and cm != 0:
        if cm < 100:
            errors.append(f"{ts_code}: circ_mv={cm}万元 <100万! 可能是亿元(需×10000)或百万元(需×100)")
        if cm > 1e9:
            errors.append(f"{ts_code}: circ_mv={cm}万元 >1万亿! 可能是元(需÷10000)")
    
    # total_mv: 万元
    tm = doc.get('total_mv', 0)
    if tm is not None and tm != 0:
        if tm < 100:
            errors.append(f"{ts_code}: total_mv={tm}万元 <100万! 可能是亿元")
        if tm > 1e9:
            errors.append(f"{ts_code}: total_mv={tm}万元 >1万亿! 可能是元")
    
    # pct_chg: 百分数 (-30~+30)
    pct = doc.get('pct_chg', 0)
    if pct is not None and pct != 0:
        if abs(pct) > 30:
            errors.append(f"{ts_code}: pct_chg={pct}% 异常(|pct|>30)")
    
    return errors


def validate_daily_basic(doc: dict, strict: bool = False) -> list[str]:
    """校验daily_basic写入数据单位
    
    Args:
        doc: 要写入的文档
        strict: 严格模式
    
    Returns:
        错误列表(空=通过)
    """
    errors = []
    ts_code = doc.get('ts_code', '?')
    
    # turnover_rate: 百分数 (0.01-100)
    tr = doc.get('turnover_rate', 0)
    if tr is not None and tr != 0:
        if tr > 100:
            errors.append(f"{ts_code}: turnover_rate={tr}% >100! 可能被×100")
        if tr < 0.001 and strict:
            errors.append(f"{ts_code}: turnover_rate={tr}% <0.001! 可能是小数未×100")
    
    # circ_mv: 亿元 (0.01-10000)
    cm = doc.get('circ_mv', 0)
    if cm is not None and cm != 0:
        if cm < 0.001:
            errors.append(f"{ts_code}: circ_mv={cm}亿元 <0.001亿! 可能是万元(需÷10000)")
        if cm > 100000:
            errors.append(f"{ts_code}: circ_mv={cm}亿元 >10万亿! 可能是万元(需÷10000)或元(需÷1e8)")
    
    # total_mv: 亿元
    tm = doc.get('total_mv', 0)
    if tm is not None and tm != 0:
        if tm < 0.001:
            errors.append(f"{ts_code}: total_mv={tm}亿元 <0.001亿! 可能是万元")
        if tm > 100000:
            errors.append(f"{ts_code}: total_mv={tm}亿元 >10万亿! 可能是万元或元")
    
    # pe_ttm: 倍数 (-1000~1000)
    pe = doc.get('pe_ttm', 0)
    if pe is not None and pe != 0:
        if abs(pe) > 10000:
            errors.append(f"{ts_code}: pe_ttm={pe} 异常(|pe|>10000)")
    
    # pb: 倍数 (0-100)
    pb = doc.get('pb', 0)
    if pb is not None and pb != 0:
        if pb < 0 or pb > 1000:
            errors.append(f"{ts_code}: pb={pb} 异常")
    
    return errors
