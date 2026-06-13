#!/usr/bin/env python3
"""
MarketScanner REST API - 路由注册层

原6195行单文件已拆分为9个功能模块:
  scanner_core.py      - 核心状态/控制/持仓/信号 (16 routes)
  scanner_trading.py   - 交易/买卖/熔断/结算 (13 routes)
  scanner_review.py    - 复盘/归因/偏差/参数漂移 (13 routes)
  scanner_sentiment.py - 市场情绪/情绪矩阵 (3 routes)
  scanner_debug.py     - 调试/模拟/热更新 (6 routes)
  scanner_strategy.py  - 策略参数/绩效/快照 (10 routes)
  scanner_report.py    - 日报/周报/历史复盘 (3 routes)
  scanner_system.py    - 系统健康/守护/Stream (8 routes)
  scanner_scan.py      - 扫描追踪/盘前/行情/风控 (10 routes)

共享依赖在 scanner_shared.py:
  _get_scanner, _get_scanner_instance, _clean_mongo,
  _fill_stock_names, _safe_read_shared, Request Models
"""
from fastapi import APIRouter

from nodes.web.api.scanner_core import router as core_router
from nodes.web.api.scanner_trading import router as trading_router
from nodes.web.api.scanner_review import router as review_router
from nodes.web.api.scanner_sentiment import router as sentiment_router
from nodes.web.api.scanner_debug import router as debug_router
from nodes.web.api.scanner_strategy import router as strategy_router
from nodes.web.api.scanner_report import router as report_router
from nodes.web.api.scanner_analysis import router as analysis_router
from nodes.web.api.scanner_system import router as system_router
from nodes.web.api.scanner_scan import router as scan_router

router = APIRouter(tags=["市场监听"])

# 挂载所有子模块路由
router.include_router(core_router)
router.include_router(trading_router)
router.include_router(review_router)
router.include_router(sentiment_router)
router.include_router(debug_router)
router.include_router(strategy_router)
router.include_router(report_router)
router.include_router(analysis_router)
router.include_router(system_router)
router.include_router(scan_router)
