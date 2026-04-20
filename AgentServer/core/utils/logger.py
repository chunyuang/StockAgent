"""
专业级统一日志工具类
超短量化回测系统专用
支持全局单例、自动注入元信息、分级打印、时序保障
"""
import logging
from datetime import datetime
from typing import Optional
from pathlib import Path

# 日志级别定义
LOG_LEVELS = {
    'DEBUG': 10,
    'INFO': 20,
    'SUCCESS': 25,  # 自定义成功级别
    'WARN': 30,
    'ERROR': 40
}

# 级别样式前缀
LEVEL_PREFIX = {
    'DEBUG': '🐛DEBUG',
    'INFO': 'ℹ️INFO',
    'SUCCESS': '✅SUCCESS',
    'WARN': '⚠️WARN',
    'ERROR': '❌ERROR'
}

# 模块前缀
MODULE_PREFIX = {
    'INIT': '🔧INIT',
    'DATA': '📊DATA',
    'STRATEGY': '🎯STRATEGY',
    'TRADE': '💰TRADE',
    'RESULT': '📈RESULT',
    'ERROR': '🚨ERROR'
}

class UltraShortLogger:
    _instance: Optional['UltraShortLogger'] = None
    _seq_counter: int = 0
    _current_task_id: Optional[str] = None
    _log_cache: dict[str, list[str]] = {}  # 按task_id缓存日志
    _log_dir: Path = Path('/root/.openclaw/workspace/StockAgent/logs/backtest')

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super().__new__(cls)
            cls._instance._init_logger()
            # 确保日志目录存在
            cls._instance._log_dir.mkdir(parents=True, exist_ok=True)
        return cls._instance

    def _init_logger(self):
        """初始化基础logger"""
        self.logger = logging.getLogger('ultrashort')
        self.logger.setLevel(logging.DEBUG)
        
        # 避免重复添加handler
        if self.logger.handlers:
            return
            
        # 控制台输出handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter('%(message)s')
        console_handler.setFormatter(formatter)
        self.logger.addHandler(console_handler)

    def _get_next_seq(self) -> int:
        """获取下一个全局自增序号"""
        self._seq_counter += 1
        return self._seq_counter

    def set_task_id(self, task_id: str):
        """设置当前任务ID，后续日志自动绑定"""
        self._current_task_id = task_id
        # 初始化该任务的日志缓存
        if task_id not in self._log_cache:
            self._log_cache[task_id] = []

    def clear_task_id(self):
        """清除当前任务ID"""
        self._current_task_id = None

    def _log(self, level: str, module: str, message: str, *args, **kwargs):
        """统一日志打印方法"""
        if not self._current_task_id:
            # 没有任务ID时不打印，避免混乱
            return
            
        seq = self._get_next_seq()
        timestamp = datetime.now().strftime('%H:%M:%S')
        level_prefix = LEVEL_PREFIX.get(level, 'ℹ️INFO')
        module_prefix = MODULE_PREFIX.get(module, 'ℹ️INFO')
        
        # 格式化日志内容：只有当有参数时才格式化，避免message本身包含大括号导致解析错误
        if args or kwargs:
            formatted_message = message.format(*args, **kwargs)
        else:
            formatted_message = message
        formatted_msg = f"[{timestamp}] [{level_prefix}] [SEQ:{seq}] [TASK:{self._current_task_id}] [{module_prefix}] {formatted_message}"
        
        # 输出到控制台
        if level == 'SUCCESS':
            self.logger.log(LOG_LEVELS['SUCCESS'], formatted_msg)
        else:
            self.logger.log(LOG_LEVELS[level], formatted_msg)
        
        # 加入内存缓存
        if self._current_task_id in self._log_cache:
            self._log_cache[self._current_task_id].append(formatted_msg)
        
        # 写入本地文件持久化
        log_file = self._log_dir / f"{self._current_task_id}.log"
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(formatted_msg + '\n')

    # 快捷打印方法
    def debug(self, module: str, message: str, *args, **kwargs):
        self._log('DEBUG', module, message, *args, **kwargs)

    def info(self, module: str, message: str, *args, **kwargs):
        self._log('INFO', module, message, *args, **kwargs)

    def success(self, module: str, message: str, *args, **kwargs):
        self._log('SUCCESS', module, message, *args, **kwargs)

    def warn(self, module: str, message: str, *args, **kwargs):
        self._log('WARN', module, message, *args, **kwargs)

    def error(self, module: str, message: str, *args, **kwargs):
        self._log('ERROR', module, message, *args, **kwargs)

    def get_task_logs(self, task_id: str) -> list[str]:
        """获取指定任务的所有日志"""
        return self._log_cache.get(task_id, [])

    def get_task_log_file(self, task_id: str) -> Optional[Path]:
        """获取指定任务的日志文件路径"""
        log_file = self._log_dir / f"{task_id}.log"
        return log_file if log_file.exists() else None

# 全局单例
logger = UltraShortLogger()
