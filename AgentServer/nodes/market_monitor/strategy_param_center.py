"""
StrategyParamCenter — 策略参数中心

解决核心问题: 回测与实盘参数一致性
- 之前: 回测从strategy_defaults.py读, 实盘从settings/硬编码读, 改一个不会同步
- 现在: 所有策略参数统一存储在MongoDB strategy_params集合
  - 回测和实盘都从此读取
  - 修改后通过SignalDispatcher实时推送到Scanner(无需重启)
  - 支持参数版本历史(可追溯每次修改)

设计原则:
1. 单一真相源: MongoDB strategy_params 是唯一参数来源
2. 热更新: 参数修改后主动推送到Scanner, 无需重启
3. 版本化: 每次修改记录历史, 支持回滚
4. 兜底: MongoDB不可用时fallback到strategy_defaults.py

用法:
    # 读取参数
    params = await param_center.get_strategy_params("halfway_chase")
    sl_pct = params.get("stop_loss_pct", 0.04)  # 4%止损
    
    # 更新参数(自动推送到Scanner)
    await param_center.update_strategy_params("halfway_chase", {"stop_loss_pct": 0.05})
    
    # Scanner端: 注册接收回调
    param_center.on_update = scanner.update_strategy_config
"""

import asyncio
import logging
import time
from datetime import datetime
from typing import Dict, Optional, Any, Callable, Awaitable
from copy import deepcopy

logger = logging.getLogger("param_center")


class StrategyParamCenter:
    """
    策略参数中心
    
    数据流:
    MongoDB(strategy_params) → ParamCenter → Scanner/Backtest
    
    修改流:
    API/WebUI → ParamCenter.update() → MongoDB + 通知Scanner
    """
    
    COLLECTION = "strategy_params"
    HISTORY_COLLECTION = "strategy_params_history"
    
    def __init__(self):
        self._cache: Dict[str, Dict] = {}  # strategy_id → params
        self._last_load_time: float = 0
        self._cache_ttl: float = 60.0  # 缓存60秒
        self._on_update: Optional[Callable[[str, Dict], Awaitable[None]]] = None
        self._initialized = False
    
    async def initialize(self) -> bool:
        """初始化: 从MongoDB加载参数, 不存在则从strategy_defaults导入"""
        try:
            from core.managers import mongo_manager
            if mongo_manager.db is None:
                logger.warning("[PARAMS] MongoDB未连接, 使用默认参数")
                await self._load_from_defaults()
                return False
            
            # 检查是否有参数记录
            count = await mongo_manager.db[self.COLLECTION].count_documents({})
            if count == 0:
                # 首次: 从strategy_defaults导入
                logger.info("[PARAMS] 首次初始化, 从strategy_defaults导入参数")
                await self._import_from_defaults()
            else:
                # 从MongoDB加载
                await self._load_from_db()
            
            self._initialized = True
            logger.info(f"[PARAMS] 初始化完成, 已加载{len(self._cache)}个策略参数")
            return True
            
        except Exception as e:
            logger.error(f"[PARAMS] 初始化失败: {e}")
            await self._load_from_defaults()
            return False
    
    async def get_strategy_params(self, strategy_id: str) -> Dict:
        """
        获取策略参数
        
        优先级: MongoDB缓存 > strategy_defaults > 空dict
        """
        # 检查缓存是否过期
        if time.time() - self._last_load_time > self._cache_ttl:
            await self._load_from_db()
        
        if strategy_id in self._cache:
            return deepcopy(self._cache[strategy_id])
        
        # Fallback: 从strategy_defaults读取
        try:
            from nodes.backtest_engine.strategy_defaults import STRATEGY_CONFIGS, GLOBAL_RISK
            if strategy_id in STRATEGY_CONFIGS:
                cfg = STRATEGY_CONFIGS[strategy_id]
                params = {
                    "strategy_id": strategy_id,
                    "name": cfg.get("name", strategy_id),
                    "riskParams": deepcopy(cfg.get("riskParams", {})),
                    "filterConditions": deepcopy(cfg.get("filterConditions", {})),
                    "maxHoldDays": cfg.get("maxHoldDays", 3),
                    "globalRisk": deepcopy(GLOBAL_RISK),
                    "source": "defaults_fallback",
                    "updated_at": datetime.now().isoformat(),
                }
                self._cache[strategy_id] = params
                return deepcopy(params)
        except ImportError:
            pass
        
        # 最后兜底
        return {}
    
    async def get_all_params(self) -> Dict[str, Dict]:
        """获取所有策略参数"""
        if time.time() - self._last_load_time > self._cache_ttl:
            await self._load_from_db()
        return deepcopy(self._cache)
    
    async def update_strategy_params(
        self,
        strategy_id: str,
        updates: Dict[str, Any],
        updated_by: str = "api",
        comment: str = "",
    ) -> bool:
        """更新策略参数(编排方法: 合并→写入→历史→通知→审计)"""
        try:
            from core.managers import mongo_manager
            if mongo_manager.db is None:
                logger.warning("[PARAMS] MongoDB未连接, 无法更新参数")
                return False

            current = await self.get_strategy_params(strategy_id)

            danger_warnings = self.check_dangerous_params(strategy_id, updates)
            for w in danger_warnings:
                logger.warning(f"[PARAMS] {w}")

            merged = self._deep_merge(current, updates)
            merged["strategy_id"] = strategy_id
            merged["updated_at"] = datetime.now().isoformat()
            merged["updated_by"] = updated_by

            await self._persist_param_update(strategy_id, merged)
            await self._record_param_history(strategy_id, current, merged, updates, updated_by, comment)

            self._cache[strategy_id] = merged

            await self._notify_param_update(strategy_id, merged)
            asyncio.create_task(
                self._write_param_audit_log(strategy_id, updates, updated_by, danger_warnings, before=current, after=merged)
            )

            logger.info(f"[PARAMS] 参数已更新: {strategy_id}, fields={list(updates.keys())}, by={updated_by}")
            return True

        except Exception as e:
            logger.error(f"[PARAMS] 更新失败: {e}")
            return False

    async def _persist_param_update(self, strategy_id: str, merged: Dict) -> None:
        """将合并后参数写入MongoDB"""
        from core.managers import mongo_manager
        await mongo_manager.db[self.COLLECTION].update_one(
            {"strategy_id": strategy_id}, {"$set": merged}, upsert=True,
        )

    async def _record_param_history(
        self, strategy_id: str, before: Dict, after: Dict,
        updates: Dict, updated_by: str, comment: str,
    ) -> None:
        """记录参数变更历史"""
        from core.managers import mongo_manager
        history_doc = {
            "strategy_id": strategy_id,
            "before": before,
            "after": deepcopy(after),
            "updates": updates,
            "updated_by": updated_by,
            "comment": comment,
            "timestamp": datetime.now().isoformat(),
        }
        await mongo_manager.db[self.HISTORY_COLLECTION].insert_one(history_doc)

    async def _notify_param_update(self, strategy_id: str, merged: Dict) -> None:
        """通知Scanner热更新"""
        if self._on_update:
            try:
                await self._on_update(strategy_id, merged)
                logger.info(f"[PARAMS] 热更新通知已发送: {strategy_id}")
            except Exception as e:
                logger.warning(f"[PARAMS] 热更新通知失败: {e}")
    
    async def reset_to_defaults(self, strategy_id: str) -> bool:
        """重置策略参数为默认值"""
        try:
            from nodes.backtest_engine.strategy_defaults import STRATEGY_CONFIGS, GLOBAL_RISK
            if strategy_id not in STRATEGY_CONFIGS:
                return False
            
            cfg = STRATEGY_CONFIGS[strategy_id]
            defaults = {
                "strategy_id": strategy_id,
                "name": cfg.get("name", strategy_id),
                "riskParams": deepcopy(cfg.get("riskParams", {})),
                "filterConditions": deepcopy(cfg.get("filterConditions", {})),
                "maxHoldDays": cfg.get("maxHoldDays", 3),
                "globalRisk": deepcopy(GLOBAL_RISK),
                "source": "defaults_reset",
                "updated_at": datetime.now().isoformat(),
                "updated_by": "reset",
            }
            return await self.update_strategy_params(
                strategy_id, defaults, updated_by="reset", comment="重置为默认值"
            )
        except Exception as e:
            logger.error(f"[PARAMS] 重置失败: {e}")
            return False
    
    async def get_params_history(self, strategy_id: str, limit: int = 20) -> list:
        """获取参数修改历史"""
        try:
            from core.managers import mongo_manager
            if mongo_manager.db is None:
                return []
            cursor = mongo_manager.db[self.HISTORY_COLLECTION].find(
                {"strategy_id": strategy_id}
            ).sort("timestamp", -1).limit(limit)
            result = []
            async for doc in cursor:
                doc.pop("_id", None)
                result.append(doc)
            return result
        except Exception as _e:
            return []
    
    def set_on_update_callback(self, callback: Callable[[str, Dict], Awaitable[None]]) -> None:
        """设置参数更新回调(Scanner注册)"""
        self._on_update = callback
        logger.info("[PARAMS] 热更新回调已注册")
    
    # ==================== 内部方法 ====================
    
    async def _load_from_db(self) -> None:
        """从MongoDB加载参数到缓存"""
        try:
            from core.managers import mongo_manager
            if mongo_manager.db is None:
                return
            cursor = mongo_manager.db[self.COLLECTION].find({})
            new_cache = {}
            async for doc in cursor:
                doc.pop("_id", None)
                sid = doc.get("strategy_id", "unknown")
                new_cache[sid] = doc
            self._cache = new_cache
            self._last_load_time = time.time()
        except Exception as e:
            logger.warning(f"[PARAMS] DB加载失败, 使用缓存: {e}")
    
    async def _load_from_defaults(self) -> None:
        """从strategy_defaults.py加载参数(fallback)"""
        try:
            from nodes.backtest_engine.strategy_defaults import STRATEGY_CONFIGS, GLOBAL_RISK
            for sid, cfg in STRATEGY_CONFIGS.items():
                self._cache[sid] = {
                    "strategy_id": sid,
                    "name": cfg.get("name", sid),
                    "riskParams": deepcopy(cfg.get("riskParams", {})),
                    "filterConditions": deepcopy(cfg.get("filterConditions", {})),
                    "maxHoldDays": cfg.get("maxHoldDays", 3),
                    "globalRisk": deepcopy(GLOBAL_RISK),
                    "source": "defaults",
                }
            self._last_load_time = time.time()
            logger.info(f"[PARAMS] 从defaults加载{len(self._cache)}个策略参数")
        except ImportError as e:
            logger.error(f"[PARAMS] defaults加载失败: {e}")
    
    async def _import_from_defaults(self) -> None:
        """首次: 从strategy_defaults导入到MongoDB"""
        try:
            from nodes.backtest_engine.strategy_defaults import STRATEGY_CONFIGS, GLOBAL_RISK
            from core.managers import mongo_manager
            
            docs = []
            for sid, cfg in STRATEGY_CONFIGS.items():
                doc = {
                    "strategy_id": sid,
                    "name": cfg.get("name", sid),
                    "riskParams": deepcopy(cfg.get("riskParams", {})),
                    "filterConditions": deepcopy(cfg.get("filterConditions", {})),
                    "maxHoldDays": cfg.get("maxHoldDays", 3),
                    "globalRisk": deepcopy(GLOBAL_RISK),
                    "source": "defaults_import",
                    "imported_at": datetime.now().isoformat(),
                }
                docs.append(doc)
                self._cache[sid] = doc
            
            if docs:
                await mongo_manager.db[self.COLLECTION].insert_many(docs)
                logger.info(f"[PARAMS] 导入{len(docs)}个策略参数到MongoDB")
            
            self._last_load_time = time.time()
            
        except Exception as e:
            logger.error(f"[PARAMS] 导入失败: {e}")
            await self._load_from_defaults()
    
    @staticmethod
    def _deep_merge(base: Dict, override: Dict) -> Dict:
        """深度合并字典"""
        result = deepcopy(base)
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = StrategyParamCenter._deep_merge(result[key], value)
            else:
                result[key] = deepcopy(value)
        return result

    # ==================== Phase2.3: 参数补全+漂移检测+危险参数告警 ====================

    async def ensure_complete(self) -> int:
        """启动时确保MongoDB参数完整,缺失的从strategy_defaults.py补全
        
        Returns: 补全的策略数量
        """
        try:
            from core.managers import mongo_manager
            if mongo_manager.db is None:
                return 0
            
            defaults = self._get_all_defaults()
            patched = 0
            
            for strategy_id, config in defaults.items():
                existing = await mongo_manager.db[self.COLLECTION].find_one(
                    {"strategy_id": strategy_id}
                )
                if not existing:
                    # 完全缺失 → 导入
                    config["strategy_id"] = strategy_id
                    config["updated_at"] = datetime.now().isoformat()
                    config["updated_by"] = "ensure_complete"
                    await mongo_manager.db[self.COLLECTION].insert_one(config)
                    self._cache[strategy_id] = config
                    patched += 1
                    logger.info(f"[PARAMS] 补全新策略: {strategy_id}")
                else:
                    # 检测新字段(strategy_defaults新增但MongoDB没有的)
                    new_fields = set(config.keys()) - set(existing.keys()) - {"_id"}
                    if new_fields:
                        update_fields = {k: config[k] for k in new_fields}
                        await mongo_manager.db[self.COLLECTION].update_one(
                            {"strategy_id": strategy_id},
                            {"$set": update_fields}
                        )
                        # 更新缓存
                        for k, v in update_fields.items():
                            self._cache.get(strategy_id, {})[k] = v
                        patched += 1
                        logger.info(f"[PARAMS] 补全新字段: {strategy_id} +{new_fields}")
            
            return patched
        except Exception as e:
            logger.error(f"[PARAMS] ensure_complete失败: {e}")
            return 0

    async def detect_drift(self) -> list:
        """检测MongoDB与strategy_defaults.py的差异(漂移)"""
        drifts = []
        try:
            from core.managers import mongo_manager
            if mongo_manager.db is None:
                return drifts
            
            defaults = self._get_all_defaults()
            for strategy_id, config in defaults.items():
                existing = await mongo_manager.db[self.COLLECTION].find_one(
                    {"strategy_id": strategy_id}
                )
                if existing:
                    for k, v in config.items():
                        if k in existing and existing[k] != v:
                            drifts.append({
                                "strategy": strategy_id,
                                "key": k,
                                "mongodb_value": existing[k],
                                "defaults_value": v,
                            })
        except Exception as e:
            logger.error(f"[PARAMS] detect_drift失败: {e}")
        return drifts

    def _get_all_defaults(self) -> Dict:
        """获取strategy_defaults.py的全部参数"""
        try:
            from nodes.backtest_engine.strategy_defaults import STRATEGY_CONFIGS
            return deepcopy(STRATEGY_CONFIGS)
        except ImportError:
            return {}

    def check_dangerous_params(self, strategy_id: str, updates: Dict) -> list:
        """检查危险参数变更(超出合理范围)"""
        DANGEROUS_RANGES = {
            'stop_loss_pct': (0.01, 0.10),   # 1%-10%合理
            'take_profit_pct': (0.03, 0.50), # 3%-50%合理
            'max_hold_days': (1, 30),         # 1-30天合理
            'trailing_stop_pct': (0.01, 0.10),
        }
        warnings = []
        for key, value in updates.items():
            if key in DANGEROUS_RANGES:
                lo, hi = DANGEROUS_RANGES[key]
                if not isinstance(value, (int, float)) or not (lo <= value <= hi):
                    warnings.append(f"⚠️ {strategy_id}.{key}={value} 超出合理范围({lo}-{hi})")
        return warnings

    # ==================== Phase2.3: 参数变更审计日志 ====================

    async def _write_param_audit_log(self, strategy_id: str, updates: Dict,
                                     updated_by: str, danger_warnings: list,
                                     before: Dict = None, after: Dict = None) -> None:
        """参数变更审计日志(append-only, 存audit_log集合)"""
        try:
            from core.managers import mongo_manager
            if mongo_manager.db is None:
                return
            
            # 计算实际变更的键值(仅记录真正变化的字段)
            changed_fields = {}
            if before and after:
                for key in updates:
                    old_val = before.get(key)
                    new_val = after.get(key)
                    if old_val != new_val:
                        changed_fields[key] = {"old": old_val, "new": new_val}
            else:
                changed_fields = {k: {"new": v} for k, v in updates.items()}
            
            doc = {
                "timestamp": datetime.now().isoformat(),
                "type": "param_change",  # 区别于scanner的signal/trade审计
                "strategy_id": strategy_id,
                "changed_fields": changed_fields,
                "updated_by": updated_by,
                "danger_warnings": danger_warnings,
                "is_dangerous": len(danger_warnings) > 0,
            }
            await mongo_manager.db["audit_log"].insert_one(doc)
            
            if danger_warnings:
                logger.warning(
                    f"[PARAMS_AUDIT] 危险参数变更! strategy={strategy_id}, "
                    f"by={updated_by}, warnings={danger_warnings}"
                )
            else:
                logger.info(
                    f"[PARAMS_AUDIT] 参数变更: strategy={strategy_id}, "
                    f"fields={list(changed_fields.keys())}, by={updated_by}"
                )
        except Exception as e:
            logger.debug(f"[PARAMS_AUDIT] 审计日志写入失败(不影响主流程): {e}")

    async def get_param_audit_trail(self, strategy_id: str = None, limit: int = 50) -> list:
        """查询参数变更审计轨迹"""
        try:
            from core.managers import mongo_manager
            if mongo_manager.db is None:
                return []
            query = {"type": "param_change"}
            if strategy_id:
                query["strategy_id"] = strategy_id
            cursor = mongo_manager.db["audit_log"].find(query).sort(
                "timestamp", -1
            ).limit(limit)
            result = []
            async for doc in cursor:
                doc.pop("_id", None)
                result.append(doc)
            return result
        except Exception as _e:
            return []

    # ==================== Scanner配置管理辅助(静态方法) ====================

    @staticmethod
    def validate_live_params(broker, risk_getter) -> None:
        """实盘参数校验
        
        检查回测参数是否合理, 避免用不切实际的参数跑实盘。
        """
        warnings = []
        
        # 1. 滑点检查
        if broker and hasattr(broker, 'SLIPPAGE_RATE'):
            if broker.SLIPPAGE_RATE < 0.001:
                warnings.append(f"滑点{broker.SLIPPAGE_RATE*100:.2f}%过低, 实盘建议≥0.1%")
        
        # 2. 仓位上限
        if broker and hasattr(broker, 'MAX_TOTAL_RATIO'):
            if broker.MAX_TOTAL_RATIO > 0.8:
                warnings.append(f"总仓位上限{broker.MAX_TOTAL_RATIO*100:.0f}%过高, 实盘建议≤70%")
        
        # 3. 止损检查
        if risk_getter:
            risk = risk_getter("default")
            if risk.get("stop_loss_pct", 0.03) < 0.02:
                warnings.append("止损<2%过紧, 实盘容易被震出")
        
        for w in warnings:
            logger.warning(f"[VALIDATE] ⚠️ {w}")

    @staticmethod
    def update_scanner_config(config: Dict, strategy_key: str, updates: Dict) -> None:
        """更新scanner.config中的strategy_overrides"""
        if "strategy_overrides" not in config:
            config["strategy_overrides"] = {}
        
        existing = config["strategy_overrides"].get(strategy_key, {})
        
        if "params" in updates:
            if "params" not in existing:
                existing["params"] = {}
            existing["params"].update(updates["params"])
        
        if "riskParams" in updates:
            if "riskParams" not in existing:
                existing["riskParams"] = {}
            existing["riskParams"].update(updates["riskParams"])
        
        if "enabled" in updates:
            existing["enabled"] = updates["enabled"]
        
        config["strategy_overrides"][strategy_key] = existing

    @staticmethod
    async def persist_scanner_overrides(config: Dict) -> None:
        """将strategy_overrides持久化到MongoDB"""
        try:
            from core.managers import mongo_manager
            if mongo_manager.db is None:
                return
            overrides = config.get("strategy_overrides", {})
            from datetime import datetime as dt
            await mongo_manager.db["scanner_config"].update_one(
                {"_id": "strategy_overrides"},
                {"$set": {"data": overrides, "updated_at": dt.now().isoformat()}},
                upsert=True,
            )
            logger.info(f"[SCANNER] 策略参数已持久化到MongoDB")
        except Exception as e:
            logger.warning(f"[SCANNER] 策略参数持久化失败(非关键): {e}")

    @staticmethod
    async def load_scanner_overrides() -> Dict:
        """从MongoDB恢复strategy_overrides"""
        try:
            from core.managers import mongo_manager
            if mongo_manager.db is None:
                return {}
            doc = await mongo_manager.db["scanner_config"].find_one({"_id": "strategy_overrides"})
            if doc and "data" in doc:
                return doc["data"]
        except Exception as e:
            logger.warning(f"[SCANNER] 策略参数恢复失败(非关键): {e}")
        return {}

    @staticmethod
    async def load_and_apply_scanner_overrides(scanner) -> None:
        """从MongoDB恢复strategy_overrides并应用到scanner.config【v2.9.42:从scanner._load_strategy_overrides提取】"""
        try:
            data = await StrategyParamCenter.load_scanner_overrides()
            if data:
                if "strategy_overrides" not in scanner.config:
                    scanner.config["strategy_overrides"] = {}
                scanner.config["strategy_overrides"].update(data)
                logger.info(f"[SCANNER] 从MongoDB恢复策略参数: {len(data)}个策略")
        except Exception as _e:
            logger.debug(f"[SCANNER] 从MongoDB恢复策略参数失败: {_e}")

    @staticmethod
    async def detect_and_publish_drift(scanner) -> None:
        """启动时检测参数漂移并发布事件【v2.9.42:从scanner._detect_param_drift提取】"""
        try:
            drifts = await param_center.detect_drift()
            if drifts:
                logger.warning(f"[PARAMS] 检测到{len(drifts)}个参数漂移: {drifts[:3]}")
                await scanner._publish_scanner_event("status", {
                    "type": "param_drift", "drifts": drifts[:5],
                })
        except Exception as e:
            logger.debug(f"[PARAMS] 漂移检测失败(非关键): {e}")

    @staticmethod
    def apply_scanner_config_update(scanner, strategy_key: str, updates: Dict[str, Any]) -> None:
        """策略参数热更新+EventBus+持久化【v2.9.42:从scanner.update_strategy_config提取】
        
        流程: 记录旧值→更新config→EventBus事件→持久化(非阻塞)
        """
        import asyncio as _asyncio
        
        # 1. 记录旧值(审计)
        old_values = {}
        try:
            strategy_config = scanner.config.get("strategies", {}).get(strategy_key, {})
            for k in updates:
                if k in strategy_config:
                    old_values[k] = strategy_config[k]
        except Exception as _e:
            logger.debug(f"[SCANNER] 策略参数旧值读取失败: {_e}")
        
        # 2. 更新config
        try:
            StrategyParamCenter.update_scanner_config(scanner.config, strategy_key, updates)
            logger.info(f"[SCANNER] 策略参数热更新: {strategy_key}")
        except Exception as _e:
            logger.warning(f"[SCANNER] 策略参数热更新失败: {strategy_key}: {_e}")
            return
        
        # 3. EventBus事件(非阻塞)
        try:
            from nodes.market_monitor.scanner_event_bus import ScannerEvents
            if scanner._loop and not scanner._loop.is_closed():
                scanner._loop.create_task(scanner._event_bus.emit(ScannerEvents.PARAM_UPDATED, {
                    "strategy_key": strategy_key, "updates": updates,
                    "old_values": old_values,
                }))
        except Exception as _e:
            logger.debug(f"[SCANNER] 参数更新事件发射失败: {_e}")
        
        # 4. 持久化(非阻塞)
        try:
            if scanner._loop and not scanner._loop.is_closed():
                scanner._loop.create_task(StrategyParamCenter.persist_scanner_overrides(scanner.config))
        except Exception as _e:
            logger.debug(f"[SCANNER] 参数持久化失败: {_e}")


# 全局单例
param_center = StrategyParamCenter()
