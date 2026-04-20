"""
Baostock 免费日线数据源管理器

负责:
- 免费获取 A 股历史日线数据
- 数据格式标准化为与 Tushare 一致格式
- 作为 TuShare/AKShare 的免费补充数据源
- 特别适合回测获取完整历史数据

Baostock 特点:
- 完全免费，不需要注册
- 提供完整 A 股历史日线数据
- 数据更新到上一交易日
- 接口稳定，无调用限制

官网: http://baostock.com/
"""

from typing import Optional, List
from datetime import date
import pandas as pd

from .base import BaseManager


class BaostockManager(BaseManager):
    """
    Baostock 免费日线数据源管理器
    
    提供免费完整的 A 股历史日线数据，作为 TuShare 的补充。
    """
    
    def __init__(self):
        super().__init__()
        self._bs = None
        self._logged_in = False
    
    async def initialize(self) -> None:
        """初始化 Baostock"""
        try:
            import baostock as bs
            self._bs = bs
            # 登录
            lg = bs.login()
            if lg.error_code == '0':
                self._logged_in = True
                self._initialized = True
                self.logger.info("Baostock 登录成功")
            else:
                self.logger.error(f"Baostock 登录失败: {lg.error_msg}")
                self._logged_in = False
                self._initialized = False
        except ImportError:
            self.logger.error("baostock 未安装，请执行: pip install baostock")
            self._initialized = False
        except Exception as e:
            self.logger.error(f"Baostock 初始化失败: {e}")
            self._initialized = False
    
    async def shutdown(self) -> None:
        """关闭连接"""
        if self._logged_in and self._bs:
            try:
                self._bs.logout()
            except:
                pass
        self._initialized = False
        self._logged_in = False
    
    async def health_check(self) -> bool:
        """健康检查"""
        return self._initialized and self._logged_in
    
    def _convert_code(self, code: str) -> str:
        """
        转换代码格式为 Baostock 格式
        
        Tushare: 000001 → Baostock: sz.000001
        """
        if code.startswith('6'):
            return f"sh.{code}"
        elif code.startswith('0') or code.startswith('3'):
            return f"sz.{code}"
        elif code.startswith('8') or code.startswith('4'):
            return f"bj.{code}"
        return code
    
    def _standardize_df(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        标准化数据框为 Tushare 格式
        
        Baostock 字段 → Tushare 字段:
        date → trade_date
        code → ts_code
        open → open
        high → high
        low → low
        close → close
        volume → vol
        amount → amount
        pctChg → pct_chg
        """
        if df.empty:
            return df
        
        # 重命名字段
        df = df.rename(columns={
            'date': 'trade_date',
            'code': 'ts_code',
            'volume': 'vol',
            'pctChg': 'pct_chg',
        })
        
        # 转换日期格式 YYYY-MM-DD → YYYYMMDD
        df['trade_date'] = df['trade_date'].str.replace('-', '').astype(int)
        
        # 调整列顺序，匹配 Tushare
        desired_cols = [
            'ts_code', 'trade_date', 'open', 'high', 'low', 'close',
            'pre_close', 'vol', 'amount', 'pct_chg'
        ]
        
        # 只保留存在的列
        existing_cols = [col for col in desired_cols if col in df.columns]
        df = df[existing_cols]
        
        return df
    
    async def get_daily(
        self,
        ts_code: str,
        start_date: Optional[int] = None,
        end_date: Optional[int] = None
    ) -> Optional[pd.DataFrame]:
        """
        获取单只股票日线数据
        
        Args:
            ts_code: 股票代码 (e.g., 000001)
            start_date: 开始日期 YYYYMMDD
            end_date: 结束日期 YYYYMMDD
            
        Returns:
            标准化的日线 DataFrame，失败返回 None
        """
        self._ensure_initialized()
        
        if not self._logged_in:
            return None
        
        try:
            # 转换代码格式
            bs_code = self._convert_code(ts_code)
            
            # 转换日期格式
            start_str = None
            end_str = None
            if start_date:
                start_str = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}"
            if end_date:
                end_str = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}"
            
            # 默认获取全部历史
            if not start_str:
                start_str = "1990-01-01"
            if not end_str:
                today = date.today().strftime("%Y-%m-%d")
                end_str = today
            
            # 定义需要获取的字段
            # 详见: http://baostock.com/baostock/index.php/A股K线数据
            fields = "date,code,open,high,low,close,preclose,volume,amount,pctChg"
            
            # 查询
            rs = self._bs.query_history_k_data_plus(
                bs_code,
                start_date=start_str,
                end_date=end_str,
                fields=fields,
                adjustflag="3"  # 前复权
            )
            
            if rs.error_code != '0':
                self.logger.warning(f"获取 {ts_code} 日线失败: {rs.error_msg}")
                return None
            
            # 转换为DataFrame
            data_list = []
            while (rs.next()):
                row = rs.get_row_data()
                data_list.append(row)
            
            if not data_list:
                return pd.DataFrame()
            
            df = pd.DataFrame(data_list, columns=rs.fields)
            
            # 标准化
            df = self._standardize_df(df)
            
            # 按日期降序排列（最新在前）
            df = df.sort_values('trade_date', ascending=False).reset_index(drop=True)
            
            return df
            
        except Exception as e:
            self.logger.error(f"获取 {ts_code} 日线异常: {e}")
            return None
    
    async def get_trade_dates(self, start_date: str, end_date: str) -> Optional[List[str]]:
        """
        获取交易日历
        
        Args:
            start_date: 开始日期 YYYYMMDD
            end_date: 结束日期 YYYYMMDD
        
        Returns:
            交易日列表 ["YYYYMMDD", ...]
        """
        self._ensure_initialized()
        
        if not self._logged_in:
            return None
        
        try:
            # 转换格式
            start_str = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}"
            end_str = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}"
            
            rs = self._bs.query_trade_dates(start_date=start_str, end_date=end_str)
            
            if rs.error_code != '0':
                self.logger.warning(f"获取交易日历失败: {rs.error_msg}")
                return None
            
            data_list = []
            while (rs.next()):
                data_list.append(rs.get_row_data()[0])
            
            # 转换回 YYYYMMDD 格式
            result = [d.replace('-', '') for d in data_list]
            
            self.logger.info(f"获取交易日历成功: {len(result)} 个交易日从 {start_date} 到 {end_date}")
            return result
            
        except Exception as e:
            self.logger.error(f"获取交易日历异常: {e}")
            return None
    
    async def get_stock_basic(self) -> Optional[pd.DataFrame]:
        """
        获取股票基础信息列表
        
        Returns:
            包含 ts_code, code, name 等基本信息
        """
        self._ensure_initialized()
        
        if not self._logged_in:
            return None
        
        try:
            rs = self._bs.query_stock_basic()
            if rs.error_code != '0':
                self.logger.error(f"获取股票基础信息失败: {rs.error_msg}")
                return None
            
            data_list = []
            while (rs.next()):
                data_list.append(rs.get_row_data())
            
            if not data_list:
                return pd.DataFrame()
            
            df = pd.DataFrame(data_list, columns=rs.fields)
            
            # 提取代码（去掉 sh./sz. 前缀）
            df['ts_code'] = df['code'].apply(lambda x: x.split('.')[1])
            
            return df
            
        except Exception as e:
            self.logger.error(f"获取股票基础信息异常: {e}")
            return None


# 全局单例
baostock_manager = BaostockManager()
