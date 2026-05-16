.PHONY: test test-contract test-single-source test-parity test-all

# 回测系统3层防线测试
# 第1层：回测数据契约（需要先跑一次回测）
# 第2层：参数单一来源（不需要回测结果）
# 第3层：回测vs实盘应一致项白名单（不需要回测结果）

test-contract:
	@echo "🛡️ 第1层防线：回测数据契约测试"
	cd AgentServer && source venv/bin/activate && \
	python -m pytest tests/test_backtest_contract.py -v --tb=short

test-single-source:
	@echo "🛡️ 第2层防线：参数单一来源校验"
	cd AgentServer && source venv/bin/activate && \
	python -m pytest tests/test_single_source.py -v --tb=short

test-parity:
	@echo "🛡️ 第3层防线：回测vs实盘应一致项白名单"
	cd AgentServer && source venv/bin/activate && \
	python -m pytest tests/test_backtest_live_parity.py -v --tb=short

test-all:
	@echo "🛡️ 运行全部防线测试（第2层+第3层，不需要回测结果）"
	cd AgentServer && source venv/bin/activate && \
	python -m pytest tests/test_single_source.py tests/test_backtest_live_parity.py -v --tb=short

test:
	@echo "🛡️ 运行全部防线测试"
	cd AgentServer && source venv/bin/activate && \
	python -m pytest tests/test_backtest_contract.py tests/test_single_source.py tests/test_backtest_live_parity.py -v --tb=short