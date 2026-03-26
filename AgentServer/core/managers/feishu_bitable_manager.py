"""
飞书多维表格管理器

负责:
- 策略触发信号自动写入实时监控表
- 获取历史信号记录
- 删除测试数据

支持:
- app_token: 多维表格应用 token
- table_id: 数据表 ID
- 自动 tenant_access_token 刷新
"""

import asyncio
import httpx
from typing import Optional, List, Dict, Any
from datetime import datetime
from dataclasses import dataclass

from .base import BaseManager
from ..settings import settings
from ..protocols import StrategyAlert


@dataclass
class FeishuBitableConfig:
    """飞书多维表格配置"""
    app_id: str = ""
    app_secret: str = ""
    app_token: str = ""
    table_id: str = ""
    enabled: bool = False


class FeishuBitableManager(BaseManager):
    """
    飞书多维表格管理器
    
    用于将策略触发信号自动写入实时监控表。
    """
    
    def __init__(self):
        super().__init__()
        self._config = self._load_config()
        self._client: Optional[httpx.AsyncClient] = None
        self._tenant_access_token: Optional[str] = None
        self._token_expire_time: int = 0  # 过期时间戳
    
    def _load_config(self) -> FeishuBitableConfig:
        """从 settings 加载配置"""
        return FeishuBitableConfig(
            app_id=getattr(settings.feishu, "app_id", ""),
            app_secret=getattr(settings.feishu, "app_secret", ""),
            app_token=getattr(settings.feishu, "bitable_app_token", ""),
            table_id=getattr(settings.feishu, "bitable_table_id", ""),
            enabled=getattr(settings.feishu, "enabled", False),
        )
    
    @property
    def is_configured(self) -> bool:
        """是否已配置"""
        return (
            self._config.enabled
            and bool(self._config.app_id)
            and bool(self._config.app_secret)
            and bool(self._config.app_token)
            and bool(self._config.table_id)
        )
    
    async def initialize(self) -> None:
        """初始化"""
        if self._initialized:
            return
        
        self.logger.info("Initializing FeishuBitableManager...")
        
        if not self.is_configured:
            self.logger.warning("Feishu Bitable not configured, skipping initialization")
            self._initialized = True
            return
        
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(15.0),
        )
        
        # 获取首次 token
        await self._refresh_token()
        
        self._initialized = True
        self.logger.info("FeishuBitableManager initialized ✓")
    
    async def shutdown(self) -> None:
        """关闭"""
        if self._client:
            await self._client.aclose()
            self._client = None
        self._initialized = False
        self.logger.info("FeishuBitableManager shutdown")
    
    async def _refresh_token(self) -> bool:
        """刷新 tenant_access_token"""
        if not self._client:
            return False
        
        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        payload = {
            "app_id": self._config.app_id,
            "app_secret": self._config.app_secret,
        }
        
        try:
            response = await self._client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
            
            if data.get("code") == 0:
                self._tenant_access_token = data.get("tenant_access_token")
                expire_in = data.get("expire", 7200)
                self._token_expire_time = int(datetime.now().timestamp()) + expire_in - 60
                self.logger.debug(f"Token refreshed, expires in {expire_in}s")
                return True
            else:
                self.logger.error(f"Failed to refresh token: {data}")
                return False
        
        except Exception as e:
            self.logger.error(f"Error refreshing token: {e}")
            return False
    
    async def _ensure_token(self) -> bool:
        """确保 token 有效"""
        if not self._tenant_access_token:
            return await self._refresh_token()
        
        # 检查是否过期
        now = int(datetime.now().timestamp())
        if now >= self._token_expire_time:
            return await self._refresh_token()
        
        return True
    
    async def add_alert_record(self, alert: StrategyAlert) -> Optional[str]:
        """
        添加策略触发预警记录到多维表格
        
        Args:
            alert: 策略预警对象
            
        Returns:
            记录 ID，如果失败返回 None
        """
        if not self.is_configured or not self._client:
            self.logger.warning("[FEISHU] Not configured, skip writing record")
            return None
        
        if not await self._ensure_token():
            self.logger.error("[FEISHU] Failed to get token, cannot write record")
            return None
        
        # 构建记录字段
        # 根据多维表格实际字段调整
        fields = {
            "股票代码": alert.ts_code,
            "股票名称": alert.stock_name,
            "策略ID": alert.strategy_id,
            "策略名称": alert.strategy_name,
            "策略类型": alert.strategy_id,  # 实际就是策略类型
            "触发价格": alert.trigger_price,
            "触发原因": alert.trigger_reason,
            "触发时间": int(datetime.now().timestamp() * 1000),
            "额外数据": str(alert.extra_data),
        }
        
        # API 文档: https://open.feishu.cn/document/ukTMukTMukTM/uUDN04SN0QjL1QDN/bitable-v1/app-table-record/create
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{self._config.app_token}/tables/{self._config.table_id}/records"
        
        headers = {
            "Authorization": f"Bearer {self._tenant_access_token}",
            "Content-Type": "application/json; charset=utf-8",
        }
        
        payload = {
            "fields": fields,
        }
        
        try:
            response = await self._client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
            
            code = data.get("code", -1)
            if code == 0:
                record_id = data.get("data", {}).get("record_id")
                self.logger.info(
                    f"[FEISHU] ✅ Record added: {alert.ts_code} {alert.stock_name} -> record_id={record_id}"
                )
                return record_id
            else:
                self.logger.error(f"[FEISHU] Failed to add record: code={code}, msg={data.get('msg')}")
                return None
        
        except Exception as e:
            self.logger.error(f"[FEISHU] Exception adding record: {e}")
            return None
    
    async def list_records(self, page_size: int = 100) -> Optional[List[Dict[str, Any]]]:
        """列出表格记录"""
        if not self.is_configured or not self._client:
            return None
        
        if not await self._ensure_token():
            return None
        
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{self._config.app_token}/tables/{self._config.table_id}/records"
        headers = {
            "Authorization": f"Bearer {self._tenant_access_token}",
        }
        params = {
            "page_size": page_size,
        }
        
        try:
            response = await self._client.get(url, headers=headers, params=params)
            response.raise_for_status()
            data = response.json()
            
            if data.get("code") == 0:
                return data.get("data", {}).get("items", [])
            else:
                self.logger.error(f"Failed to list records: {data}")
                return None
        
        except Exception as e:
            self.logger.error(f"Error listing records: {e}")
            return None
    
    async def delete_record(self, record_id: str) -> bool:
        """删除记录"""
        if not self.is_configured or not self._client:
            return False
        
        if not await self._ensure_token():
            return False
        
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{self._config.app_token}/tables/{self._config.table_id}/records/{record_id}"
        headers = {
            "Authorization": f"Bearer {self._tenant_access_token}",
        }
        
        try:
            response = await self._client.delete(url, headers=headers)
            response.raise_for_status()
            data = response.json()
            
            if data.get("code") == 0:
                self.logger.info(f"[FEISHU] Record deleted: {record_id}")
                return True
            else:
                self.logger.error(f"Failed to delete record: {data}")
                return False
        
        except Exception as e:
            self.logger.error(f"Exception deleting record: {e}")
            return False
    
    async def health_check(self) -> bool:
        """健康检查"""
        return self._initialized and self.is_configured
    
    async def add_preselected_pool_records(
        self,
        trade_date: str,
        ts_codes: List[str],
        valid_stocks: Dict[str, Dict[str, Any]]
    ) -> int:
        """
        添加盘前预选池记录到飞书多维表格
        
        Args:
            trade_date: 交易日期 (YYYYMMDD)
            ts_codes: 预选股票代码列表
            valid_stocks: 股票信息字典
            
        Returns:
            成功写入的数量
        """
        if not self.is_configured or not self._client:
            self.logger.warning("[FEISHU] Feishu Bitable not configured, skip writing pre-selected pool")
            return 0
        
        if not await self._ensure_token():
            self.logger.error("[FEISHU] Failed to get token, skip writing pre-selected pool")
            return 0
        
        written_count = 0
        
        for ts_code in ts_codes:
            stock_info = valid_stocks.get(ts_code, {})
            stock_name = stock_info.get("name", "")
            circ_mv = stock_info.get("circ_mv", 0)
            
            fields = {
                "trade_date": trade_date,
                "ts_code": ts_code,
                "stock_name": stock_name,
                "circ_mv": circ_mv if circ_mv else None,
                "create_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            
            # 过滤掉 None 值
            fields = {k: v for k, v in fields.items() if v is not None}
            
            url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{self._config.app_token}/tables/{self._config.table_id}/records"
            headers = {
                "Authorization": f"Bearer {self._tenant_access_token}",
                "Content-Type": "application/json; charset=utf-8",
            }
            
            payload = {
                "fields": fields,
            }
            
            try:
                response = await self._client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
                
                code = data.get("code", -1)
                if code == 0:
                    written_count += 1
                else:
                    self.logger.error(f"[FEISHU] Failed to add pre-selected record: {ts_code}, code={code}, msg={data.get('msg')}")
            
            except Exception as e:
                self.logger.error(f"[FEISHU] Exception adding pre-selected record {ts_code}: {e}")
        
        self.logger.info(f"[FEISHU] ✅ Pre-selected pool written: {written_count}/{len(ts_codes)} records")
        return written_count


# 全局单例
feishu_bitable_manager = FeishuBitableManager()
