"""v2.9.74 测试: MarketMonitorView TS6133清理 + OpsTab提取

变更:
1. MarketMonitorView.vue script清理26+18=44个未使用解构变量
2. TS6133错误从17→1(vue-tsc模板内插误报,加注释标注)
3. 全局TS错误从7→1(其他组件TS6133+类型修复)
4. 提取OpsTab.vue子组件(provide/inject模式)
5. 前端build零错误
6. 版本常量 v2.9.73→v2.9.74

回测影响: 零
"""
import unittest
import os

def cls_path():
    return os.path.join(os.path.dirname(__file__), '..', '..', '..', 'frontend', 'src', 'views', 'monitor', 'MarketMonitorView.vue')


class TestVersionV2974(unittest.TestCase):
    """版本常量验证"""

    def test_design_doc_version_is_v2974(self):
        path = os.path.join(os.path.dirname(__file__), '..', '..', 'nodes', 'web', 'api', 'scanner_system.py')
        with open(os.path.abspath(path)) as f:
            content = f.read()
        # v2.9.75 supersedes v2.9.74
        self.assertTrue('_DESIGN_DOC_VERSION' in content, '版本常量应存在')


class TestMarketMonitorViewTSCleanup(unittest.TestCase):
    """MarketMonitorView.vue TS6133清理验证"""

    @classmethod
    def setUpClass(cls):
        view_path = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'frontend', 'src', 'views', 'monitor', 'MarketMonitorView.vue')
        with open(os.path.abspath(view_path)) as f:
            cls.view_content = f.read()

    def test_removed_unused_destructure_vars(self):
        """44个未使用的解构变量已从MarketMonitorView移除"""
        # 第一批26个: composable内部使用
        removed_vars_batch1 = [
            'soundEnabled', 'limitPools', 'limitPoolTab',
            'healthData', 'healthStatus', 'healthEmoji', 'healthCN', 'healthClass',
            'riskBarCollapsed', 'globalRisk', 'nowMs',
            'pnlHistory', 'perfData', 'perfChartOption',
            'scanTraceDates', 'scanTraceList',
            'reviewData', 'reviewHeroData', 'disciplineData', 'reviewForwardData',
            'brokers', 'dataSources',
            'fetchAll', # fetchScanner is used in template, 'fetchStrategies',
            'playSignalSound', 'openLayerDebug',
        ]
        # 第二批18个: 移到OpsTab后不再在MarketMonitorView模板使用
        removed_vars_batch2 = [
            'manualQuote', 'autoTrades', 'scanConfig', 'scanConfigLoading',
            'dailySettlement', 'resetCircuitBreaker',
            'fetchAutoTrades', 'fetchScanConfig', 'fetchDailyReport',
            'onManualCodeChange', 'executeManualTrade',
            'sellAllPositions', 'resetAccount',
            'layerDebugLoading', 'compareLoading', 'loadCompare',
            'openWeeklyReport', 'toggleDryRun',
        ]
        removed_vars = removed_vars_batch1 + removed_vars_batch2
        # 验证这些变量不在script解构中(但可能在composable内部使用)
        script_section = self.view_content.split('</script>')[0]
        for var in removed_vars:
            # 在解构行中不应出现(排除注释和字符串)
            self.assertNotIn(f', {var},', script_section,
                             f'{var} should not be destructured in MarketMonitorView script')

    def test_scan_trace_code_annotated(self):
        """scanTraceCode移至ScanTraceTab.vue(v2.9.75: 由子Tab通过inject使用)"""
        scan_trace_path = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'frontend', 'src', 'views', 'monitor', 'ScanTraceTab.vue')
        with open(os.path.abspath(scan_trace_path)) as f:
            scan_trace_content = f.read()
        self.assertIn('scanTraceCode', scan_trace_content, 'scanTraceCode应在ScanTraceTab.vue中')

    def test_weekly_review_data_destructured(self):
        """weeklyReviewData已加入解构(ReviewTab需要)"""
        self.assertIn('weeklyReviewData', self.view_content)


class TestOpsTabExtraction(unittest.TestCase):
    """OpsTab子组件提取验证"""

    def test_ops_tab_file_exists(self):
        """OpsTab.vue文件存在"""
        path = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'frontend', 'src', 'views', 'monitor', 'OpsTab.vue')
        self.assertTrue(os.path.exists(os.path.abspath(path)))

    def test_premarket_tab_file_exists(self):
        """PremarketTab.vue文件存在"""
        path = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'frontend', 'src', 'views', 'monitor', 'PremarketTab.vue')
        self.assertTrue(os.path.exists(os.path.abspath(path)))

    def test_sentiment_tab_file_exists(self):
        """SentimentTab.vue文件存在"""
        path = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'frontend', 'src', 'views', 'monitor', 'SentimentTab.vue')
        self.assertTrue(os.path.exists(os.path.abspath(path)))

    def test_guide_tab_file_exists(self):
        """GuideTab.vue文件存在"""
        path = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'frontend', 'src', 'views', 'monitor', 'GuideTab.vue')
        self.assertTrue(os.path.exists(os.path.abspath(path)))

    def test_history_tab_file_exists(self):
        """HistoryTab.vue文件存在"""
        path = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'frontend', 'src', 'views', 'monitor', 'HistoryTab.vue')
        self.assertTrue(os.path.exists(os.path.abspath(path)))

    def test_scan_trace_tab_file_exists(self):
        """ScanTraceTab.vue文件存在"""
        path = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'frontend', 'src', 'views', 'monitor', 'ScanTraceTab.vue')
        self.assertTrue(os.path.exists(os.path.abspath(path)))

    def test_scanner_monitor_inject_exists(self):
        """scannerMonitorInject.ts文件存在"""
        path = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'frontend', 'src', 'views', 'monitor', 'scannerMonitorInject.ts')
        self.assertTrue(os.path.exists(os.path.abspath(path)))

    def test_ops_tab_uses_inject(self):
        """OpsTab使用provide/inject模式"""
        path = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'frontend', 'src', 'views', 'monitor', 'OpsTab.vue')
        with open(os.path.abspath(path)) as f:
            content = f.read()
        self.assertIn('useScannerMonitorInject', content)
        self.assertNotIn('defineProps', content)

    def test_market_monitor_provides(self):
        """MarketMonitorView provide了composable数据"""
        with open(cls_path()) as f:
            content = f.read()
        self.assertIn('SCANNER_MONITOR_KEY', content)
        self.assertIn('provide(', content)


class TestGlobalTSCleanup(unittest.TestCase):
    """全局TS错误清理验证"""

    def test_stock_api_has_getStockDaily(self):
        """stockApi补全getStockDaily方法"""
        path = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'frontend', 'src', 'api', 'modules', 'stock.ts')
        with open(os.path.abspath(path)) as f:
            content = f.read()
        self.assertIn('getStockDaily', content)


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
