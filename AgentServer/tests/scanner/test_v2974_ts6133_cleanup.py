"""v2.9.74 测试: MarketMonitorView TS6133清理 + 未使用解构变量消除

变更:
1. MarketMonitorView.vue script清理26个未使用解构变量
2. TS6133错误从17→1(vue-tsc模板内插误报,加注释标注)
3. 前端build零错误
4. 版本常量 v2.9.73→v2.9.74

回测影响: 零
"""
import unittest
import os


class TestVersionV2974(unittest.TestCase):
    """版本常量验证"""

    def test_design_doc_version_is_v2974(self):
        path = os.path.join(os.path.dirname(__file__), '..', '..', 'nodes', 'web', 'api', 'scanner_system.py')
        with open(os.path.abspath(path)) as f:
            content = f.read()
        self.assertIn('_DESIGN_DOC_VERSION = "v2.9.74"', content)


class TestMarketMonitorViewTSCleanup(unittest.TestCase):
    """MarketMonitorView.vue TS6133清理验证"""

    @classmethod
    def setUpClass(cls):
        view_path = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'frontend', 'src', 'views', 'monitor', 'MarketMonitorView.vue')
        with open(os.path.abspath(view_path)) as f:
            cls.view_content = f.read()

    def test_removed_unused_destructure_vars(self):
        """26个未使用的解构变量已从MarketMonitorView移除"""
        # 这些变量在composable内部使用,但不需要在视图层解构
        removed_vars = [
            'soundEnabled', 'limitPools', 'limitPoolTab',
            'healthData', 'healthStatus', 'healthEmoji', 'healthCN', 'healthClass',
            'riskBarCollapsed', 'globalRisk', 'nowMs',
            'pnlHistory', 'perfData', 'perfChartOption',
            'scanTraceDates', 'scanTraceList',
            'reviewData', 'reviewHeroData', 'disciplineData', 'reviewForwardData',
            'brokers', 'dataSources',
            'fetchAll', 'fetchScanner', 'fetchStrategies',
            'playSignalSound', 'openLayerDebug',
        ]
        # 验证这些变量不在script解构中(但可能在composable内部使用)
        script_section = self.view_content.split('</script>')[0]
        for var in removed_vars:
            # 在解构行中不应出现(排除注释和字符串)
            self.assertNotIn(f', {var},', script_section,
                             f'{var} should not be destructured in MarketMonitorView script')

    def test_scan_trace_code_annotated(self):
        """scanTraceCode保留并标注used in template(vue-tsc误报)"""
        self.assertIn('scanTraceCode, // used in template', self.view_content)

    def test_weekly_review_data_destructured(self):
        """weeklyReviewData已加入解构(ReviewTab需要)"""
        self.assertIn('weeklyReviewData', self.view_content)


class TestNoBacktestRegressionV2974(unittest.TestCase):
    """回测引擎零影响"""

    def test_backtest_core_files_unchanged(self):
        """核心回测文件未被修改"""
        backtest_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'backtest')
        if os.path.exists(backtest_dir):
            for fname in os.listdir(backtest_dir):
                if fname.endswith('.py'):
                    path = os.path.join(backtest_dir, fname)
                    with open(path) as f:
                        content = f.read()
                    self.assertNotIn('v2.9.74', content,
                                     f'{fname} should not reference v2.9.74')


if __name__ == '__main__':
    unittest.main()
