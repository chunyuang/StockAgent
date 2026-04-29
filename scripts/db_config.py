"""
Scripts 公共配置

所有 scripts/ 下的脚本应通过此模块获取数据库连接等配置，
避免在各脚本中硬编码连接地址。
"""
import os
from pymongo import MongoClient

# MongoDB 配置 - 从环境变量读取，提供合理默认值
MONGO_HOST = os.getenv("MONGO_HOST", "localhost")
MONGO_PORT = int(os.getenv("MONGO_PORT", "27017"))
MONGO_DATABASE = os.getenv("MONGO_DATABASE", "stock_agent")
MONGO_USERNAME = os.getenv("MONGO_USERNAME", "")
MONGO_PASSWORD = os.getenv("MONGO_PASSWORD", "")

# Tushare Token
TUSHARE_TOKEN = os.getenv("TUSHARE_TOKEN", "")
if not TUSHARE_TOKEN:
    # 尝试从 .env 文件读取
    env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line.startswith('TUSHARE_TOKEN='):
                    TUSHARE_TOKEN = line.split('=', 1)[1].strip()
                    break


def get_mongo_client() -> MongoClient:
    """获取 MongoDB 客户端连接"""
    if MONGO_USERNAME and MONGO_PASSWORD:
        uri = f"mongodb://{MONGO_USERNAME}:{MONGO_PASSWORD}@{MONGO_HOST}:{MONGO_PORT}/"
    else:
        uri = f"mongodb://{MONGO_HOST}:{MONGO_PORT}/"
    return MongoClient(uri)


def get_db(database: str = None):
    """获取数据库连接"""
    client = get_mongo_client()
    return client[database or MONGO_DATABASE]
