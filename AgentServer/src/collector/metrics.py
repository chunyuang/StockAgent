"""
采集链路埋点监控

核心指标：
1. 采集成功率（按源优先级）
2. 去重命中率（各层命中比例）
3. LLM 增强耗时/成本
4. 事件有效率（非低价值事件比例）
5. 事件命中率（最终进入报告的比例）

监控对接：
- Prometheus metrics（可选）
- MongoDB 存储历史数据
- 支持 Grafana 查询
"""

import logging
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from enum import Enum

from src.config import config_manager


logger = logging.getLogger(__name__)


class MetricType(str, Enum):
    """指标类型"""
    COUNTER = "counter"      # 计数器
    GAUGE = "gauge"          # 瞬时值
    HISTOGRAM = "histogram"  # 分布


@dataclass
class MetricPoint:
    """指标数据点"""
    name: str
    value: float
    timestamp: datetime = field(default_factory=datetime.utcnow)
    labels: Dict[str, str] = field(default_factory=dict)
    metric_type: MetricType = MetricType.GAUGE


@dataclass
class CollectorMetrics:
    """采集器指标"""
    # 采集
    fetch_total: int = 0
    fetch_success: int = 0
    fetch_failed: int = 0
    fetch_duration_ms: float = 0
    
    # 去重
    dedup_total: int = 0
    dedup_redis_hit: int = 0
    dedup_memory_hit: int = 0
    dedup_fingerprint_hit: int = 0
    dedup_mongo_hit: int = 0
    dedup_new: int = 0
    
    # 按优先级统计
    by_priority: Dict[int, Dict[str, int]] = field(default_factory=dict)
    
    @property
    def fetch_success_rate(self) -> float:
        """采集成功率"""
        if self.fetch_total == 0:
            return 1.0
        return self.fetch_success / self.fetch_total
    
    @property
    def dedup_hit_rate(self) -> float:
        """去重命中率"""
        if self.dedup_total == 0:
            return 0.0
        hits = self.dedup_redis_hit + self.dedup_memory_hit + self.dedup_fingerprint_hit + self.dedup_mongo_hit
        return hits / self.dedup_total
    
    def get_priority_success_rate(self, priority: int) -> float:
        """获取指定优先级的成功率"""
        stats = self.by_priority.get(priority, {})
        total = stats.get("total", 0)
        success = stats.get("success", 0)
        if total == 0:
            return 1.0
        return success / total


@dataclass
class LLMMetrics:
    """LLM 增强指标"""
    invoke_total: int = 0
    invoke_success: int = 0
    invoke_failed: int = 0
    total_duration_ms: float = 0
    total_tokens: int = 0
    
    # 按增强类型统计
    full_enrich_count: int = 0
    partial_enrich_count: int = 0
    rule_fill_count: int = 0
    skip_count: int = 0
    
    @property
    def avg_duration_ms(self) -> float:
        """平均耗时"""
        if self.invoke_total == 0:
            return 0.0
        return self.total_duration_ms / self.invoke_total
    
    @property
    def success_rate(self) -> float:
        """成功率"""
        if self.invoke_total == 0:
            return 1.0
        return self.invoke_success / self.invoke_total
    
    @property
    def llm_call_ratio(self) -> float:
        """实际 LLM 调用比例（降本指标）"""
        total = self.full_enrich_count + self.partial_enrich_count + self.rule_fill_count + self.skip_count
        if total == 0:
            return 0.0
        llm_calls = self.full_enrich_count + self.partial_enrich_count
        return llm_calls / total


@dataclass
class EventMetrics:
    """事件指标"""
    # 聚类
    cluster_total: int = 0
    cluster_new: int = 0
    cluster_merged: int = 0
    
    # 过滤
    filter_total: int = 0
    filter_kept: int = 0
    filter_low_value: int = 0
    
    # 报告
    report_events_used: int = 0
    
    @property
    def event_valid_rate(self) -> float:
        """事件有效率"""
        if self.filter_total == 0:
            return 1.0
        return self.filter_kept / self.filter_total
    
    @property
    def event_hit_rate(self) -> float:
        """事件命中率（进入报告的比例）"""
        if self.filter_kept == 0:
            return 0.0
        return self.report_events_used / self.filter_kept


class MetricsCollector:
    """
    指标收集器（全局单例）
    
    收集采集链路各环节的指标，支持：
    - 实时查询当前指标
    - 持久化到 MongoDB
    - 按时间窗口聚合
    - 告警阈值检查
    
    Example:
        from src.collector.metrics import metrics_collector
        
        # 记录采集
        metrics_collector.record_fetch(source="gov", priority=5, success=True, duration_ms=100)
        
        # 记录去重
        metrics_collector.record_dedup(redis_hit=10, memory_hit=5, new=20)
        
        # 获取指标
        metrics = metrics_collector.get_current_metrics()
        
        # 检查告警
        alerts = await metrics_collector.check_alerts()
    """
    
    _instance: Optional["MetricsCollector"] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self.logger = logging.getLogger(f"{__name__}.MetricsCollector")
        
        # 当前周期指标
        self._collector_metrics = CollectorMetrics()
        self._llm_metrics = LLMMetrics()
        self._event_metrics = EventMetrics()
        
        # 指标重置时间
        self._last_reset = datetime.utcnow()
        self._reset_interval = timedelta(minutes=5)
        
        # MongoDB 管理器
        self._mongo_manager = None
        
        self._initialized = True
    
    async def _get_mongo(self):
        if self._mongo_manager is None:
            from core.managers import mongo_manager
            if not mongo_manager.is_initialized:
                await mongo_manager.initialize()
            self._mongo_manager = mongo_manager
        return self._mongo_manager
    
    # ==================== 采集指标 ====================
    
    def record_fetch(
        self,
        source: str,
        priority: int,
        success: bool,
        duration_ms: float,
        count: int = 1,
    ):
        """记录采集指标"""
        self._collector_metrics.fetch_total += count
        self._collector_metrics.fetch_duration_ms += duration_ms
        
        if success:
            self._collector_metrics.fetch_success += count
        else:
            self._collector_metrics.fetch_failed += count
        
        # 按优先级统计
        if priority not in self._collector_metrics.by_priority:
            self._collector_metrics.by_priority[priority] = {"total": 0, "success": 0, "failed": 0}
        
        self._collector_metrics.by_priority[priority]["total"] += count
        if success:
            self._collector_metrics.by_priority[priority]["success"] += count
        else:
            self._collector_metrics.by_priority[priority]["failed"] += count
    
    def record_dedup(
        self,
        total: int = 0,
        redis_hit: int = 0,
        memory_hit: int = 0,
        fingerprint_hit: int = 0,
        mongo_hit: int = 0,
        new: int = 0,
    ):
        """记录去重指标"""
        self._collector_metrics.dedup_total += total
        self._collector_metrics.dedup_redis_hit += redis_hit
        self._collector_metrics.dedup_memory_hit += memory_hit
        self._collector_metrics.dedup_fingerprint_hit += fingerprint_hit
        self._collector_metrics.dedup_mongo_hit += mongo_hit
        self._collector_metrics.dedup_new += new
    
    # ==================== LLM 指标 ====================
    
    def record_llm_invoke(
        self,
        success: bool,
        duration_ms: float,
        tokens: int = 0,
        enrich_type: str = "full",
    ):
        """记录 LLM 调用指标"""
        self._llm_metrics.invoke_total += 1
        self._llm_metrics.total_duration_ms += duration_ms
        self._llm_metrics.total_tokens += tokens
        
        if success:
            self._llm_metrics.invoke_success += 1
        else:
            self._llm_metrics.invoke_failed += 1
        
        # 按类型统计
        if enrich_type == "full":
            self._llm_metrics.full_enrich_count += 1
        elif enrich_type == "partial":
            self._llm_metrics.partial_enrich_count += 1
        elif enrich_type == "rule":
            self._llm_metrics.rule_fill_count += 1
        else:
            self._llm_metrics.skip_count += 1
    
    def record_llm_batch(
        self,
        full: int = 0,
        partial: int = 0,
        rule: int = 0,
        skip: int = 0,
        total_duration_ms: float = 0,
    ):
        """批量记录 LLM 增强结果"""
        self._llm_metrics.full_enrich_count += full
        self._llm_metrics.partial_enrich_count += partial
        self._llm_metrics.rule_fill_count += rule
        self._llm_metrics.skip_count += skip
        self._llm_metrics.invoke_total += full + partial
        self._llm_metrics.invoke_success += full + partial
        self._llm_metrics.total_duration_ms += total_duration_ms
    
    # ==================== 事件指标 ====================
    
    def record_cluster(
        self,
        total: int = 0,
        new: int = 0,
        merged: int = 0,
    ):
        """记录聚类指标"""
        self._event_metrics.cluster_total += total
        self._event_metrics.cluster_new += new
        self._event_metrics.cluster_merged += merged
    
    def record_filter(
        self,
        total: int = 0,
        kept: int = 0,
        low_value: int = 0,
    ):
        """记录过滤指标"""
        self._event_metrics.filter_total += total
        self._event_metrics.filter_kept += kept
        self._event_metrics.filter_low_value += low_value
    
    def record_report_usage(self, events_used: int):
        """记录报告使用的事件数"""
        self._event_metrics.report_events_used += events_used
    
    # ==================== 指标查询 ====================
    
    def get_current_metrics(self) -> Dict[str, Any]:
        """获取当前指标"""
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "period_minutes": (datetime.utcnow() - self._last_reset).total_seconds() / 60,
            "collector": {
                "fetch_total": self._collector_metrics.fetch_total,
                "fetch_success_rate": self._collector_metrics.fetch_success_rate,
                "fetch_duration_ms": self._collector_metrics.fetch_duration_ms,
                "dedup_total": self._collector_metrics.dedup_total,
                "dedup_hit_rate": self._collector_metrics.dedup_hit_rate,
                "dedup_by_layer": {
                    "redis": self._collector_metrics.dedup_redis_hit,
                    "memory": self._collector_metrics.dedup_memory_hit,
                    "fingerprint": self._collector_metrics.dedup_fingerprint_hit,
                    "mongo": self._collector_metrics.dedup_mongo_hit,
                },
                "by_priority": {
                    str(p): {
                        "total": stats.get("total", 0),
                        "success_rate": self._collector_metrics.get_priority_success_rate(p),
                    }
                    for p, stats in self._collector_metrics.by_priority.items()
                },
            },
            "llm": {
                "invoke_total": self._llm_metrics.invoke_total,
                "success_rate": self._llm_metrics.success_rate,
                "avg_duration_ms": self._llm_metrics.avg_duration_ms,
                "total_tokens": self._llm_metrics.total_tokens,
                "llm_call_ratio": self._llm_metrics.llm_call_ratio,
                "by_type": {
                    "full": self._llm_metrics.full_enrich_count,
                    "partial": self._llm_metrics.partial_enrich_count,
                    "rule": self._llm_metrics.rule_fill_count,
                    "skip": self._llm_metrics.skip_count,
                },
            },
            "event": {
                "cluster_total": self._event_metrics.cluster_total,
                "cluster_new": self._event_metrics.cluster_new,
                "cluster_merged": self._event_metrics.cluster_merged,
                "filter_total": self._event_metrics.filter_total,
                "event_valid_rate": self._event_metrics.event_valid_rate,
                "event_hit_rate": self._event_metrics.event_hit_rate,
                "report_events_used": self._event_metrics.report_events_used,
            },
        }
    
    async def persist_metrics(self, trace_id: Optional[str] = None):
        """持久化指标到 MongoDB"""
        mongo = await self._get_mongo()
        
        metrics = self.get_current_metrics()
        metrics["trace_id"] = trace_id
        metrics["_created_at"] = datetime.utcnow()
        
        try:
            await mongo.insert_one("collector_metrics", metrics)
            self.logger.debug(f"[{trace_id}] Metrics persisted")
        except Exception as e:
            self.logger.error(f"[{trace_id}] Persist metrics error: {e}")
    
    def reset_metrics(self):
        """重置指标（新周期）"""
        self._collector_metrics = CollectorMetrics()
        self._llm_metrics = LLMMetrics()
        self._event_metrics = EventMetrics()
        self._last_reset = datetime.utcnow()
    
    # ==================== 告警检查 ====================
    
    async def check_alerts(self, trace_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        检查告警阈值
        
        告警规则（从配置读取）：
        - P1/P2 采集成功率 < 99%
        - 去重命中率 > 95%（过高可能是采集问题）
        - LLM 调用比例 > 50%（成本过高）
        - 事件有效率 < 80%
        """
        alerts = []
        
        # 获取告警配置
        alert_config = config_manager.get("collector.metrics.alerts", {})
        
        # P1/P2 采集成功率
        p1_threshold = alert_config.get("p1_success_rate", 0.99)
        p1_rate = self._collector_metrics.get_priority_success_rate(5)
        p2_rate = self._collector_metrics.get_priority_success_rate(4)
        
        if p1_rate < p1_threshold and self._collector_metrics.by_priority.get(5, {}).get("total", 0) > 0:
            alerts.append({
                "level": "critical",
                "type": "p1_collect_fail",
                "message": f"P1 源采集成功率 {p1_rate:.1%} < {p1_threshold:.0%}",
                "value": p1_rate,
                "threshold": p1_threshold,
            })
        
        if p2_rate < p1_threshold and self._collector_metrics.by_priority.get(4, {}).get("total", 0) > 0:
            alerts.append({
                "level": "critical",
                "type": "p2_collect_fail",
                "message": f"P2 源采集成功率 {p2_rate:.1%} < {p1_threshold:.0%}",
                "value": p2_rate,
                "threshold": p1_threshold,
            })
        
        # 事件有效率
        valid_threshold = alert_config.get("event_valid_rate", 0.80)
        valid_rate = self._event_metrics.event_valid_rate
        
        if valid_rate < valid_threshold and self._event_metrics.filter_total > 10:
            alerts.append({
                "level": "warning",
                "type": "low_event_valid_rate",
                "message": f"事件有效率 {valid_rate:.1%} < {valid_threshold:.0%}",
                "value": valid_rate,
                "threshold": valid_threshold,
            })
        
        # LLM 调用比例
        llm_threshold = alert_config.get("llm_call_ratio", 0.50)
        llm_ratio = self._llm_metrics.llm_call_ratio
        
        if llm_ratio > llm_threshold and self._llm_metrics.invoke_total > 10:
            alerts.append({
                "level": "warning",
                "type": "high_llm_cost",
                "message": f"LLM 调用比例 {llm_ratio:.1%} > {llm_threshold:.0%}",
                "value": llm_ratio,
                "threshold": llm_threshold,
            })
        
        if alerts:
            self.logger.warning(f"[{trace_id}] Alerts triggered: {len(alerts)}")
            for alert in alerts:
                self.logger.warning(f"[{trace_id}] ALERT [{alert['level']}]: {alert['message']}")
        
        return alerts
    
    async def get_historical_metrics(
        self,
        hours: int = 24,
        trace_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """获取历史指标"""
        mongo = await self._get_mongo()
        
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        
        docs = await mongo.find_many(
            "collector_metrics",
            {"_created_at": {"$gte": cutoff}},
            sort=[("_created_at", -1)],
            limit=500,
        )
        
        return docs


# 全局单例
metrics_collector = MetricsCollector()
