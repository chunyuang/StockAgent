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
        """
        更新策略参数
        
        1. 合并到当前参数
        2. 写入MongoDB
        3. 记录历史
        4. 通知Scanner(热更新)
        """
        try:
            from core.managers import mongo_manager
            if mongo_manager.db is None:
                logger.warning("[PARAMS] MongoDB未连接, 无法更新参数")
                return False
            
            # 获取当前参数
            current = await self.get_strategy_params(strategy_id)
            
            # 深度合并updates到current
            merged = self._deep_merge(current, updates)
            merged["strategy_id"] = strategy_id
            merged["updated_at"] = datetime.now().isoformat()
            merged["updated_by"] = updated_by
            
            # 写入MongoDB (upsert)
            await mongo_manager.db[self.COLLECTION].update_one(
                {"strategy_id": strategy_id},
                {"$set": merged},
                upsert=True,
            )
            
            # 记录历史
            history_doc = {
                "strategy_id": strategy_id,
                "before": current,
                "after": deepcopy(merged),
                "updates": updates,
                "updated_by": updated_by,
                "comment": comment,
                "timestamp": datetime.now().isoformat(),
            }
            await mongo_manager.db[self.HISTORY_COLLECTION].insert_one(history_doc)
            
            # 更新缓存
            self._cache[strategy_id] = merged
            
            # 通知Scanner热更新
            if self._on_update:
                try:
                    await self._on_update(strategy_id, merged)
                    logger.info(f"[PARAMS] 热更新通知已发送: {strategy_id}")
                except Exception as e:
                    logger.warning(f"[PARAMS] 热更新通知失败: {e}")
            
            logger.info(
                f"[PARAMS] 参数已更新: {strategy_id}, "
                f"fields={list(updates.keys())}, by={updated_by}"
            )
            return True
            
        except Exception as e:
            logger.error(f"[PARAMS] 更新失败: {e}")
            return False
    
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
        except Exception:
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


# 全局单例
param_center = StrategyParamCenter()
