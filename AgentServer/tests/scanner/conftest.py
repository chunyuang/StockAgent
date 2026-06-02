"""conftest.py for scanner tests — adds test directory to sys.path for scanner_test_helpers"""
import sys
import os

# Ensure test directory is in sys.path for scanner_test_helpers import
test_dir = os.path.dirname(__file__)
if test_dir not in sys.path:
    sys.path.insert(0, test_dir)
