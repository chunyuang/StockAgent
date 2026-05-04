"""
集合名常量一致性测试
"""
import pytest
import sys
import os

_base = os.path.join(os.path.dirname(__file__), '..', '..')
if _base not in sys.path:
    sys.path.insert(0, _base)

# 直接导入constants.py（无外部依赖）
from core.constants import C


class TestConstants:
    """集合名常量测试"""

    def test_stock_daily_value(self):
        assert C.STOCK_DAILY == "stock_daily_ak_full"

    def test_stock_basic_value(self):
        assert C.STOCK_BASIC == "stock_basic"

    def test_index_daily_value(self):
        assert C.INDEX_DAILY == "index_daily"

    def test_daily_basic_value(self):
        assert C.DAILY_BASIC == "daily_basic"

    def test_limit_list_value(self):
        assert C.LIMIT_LIST == "limit_list"

    def test_positions_value(self):
        assert C.POSITIONS == "positions"

    def test_no_duplicate_values(self):
        """常量值不应重复"""
        values = {}
        for attr in dir(C):
            if attr.startswith('_'):
                continue
            value = getattr(C, attr)
            if isinstance(value, str):
                if value in values:
                    pytest.fail(f"C.{attr} 和 C.{values[value]} 的值重复: '{value}'")
                values[value] = attr

    def test_name_map_coverage(self):
        """_NAME_MAP 覆盖核心常量"""
        core = [C.STOCK_DAILY, C.STOCK_BASIC, C.INDEX_DAILY, C.LIMIT_LIST, C.POSITIONS]
        for const in core:
            assert const in C._NAME_MAP
