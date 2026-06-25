#!/usr/bin/env python3
"""v2.9.104 — 盘中实时情绪落库与复盘读取防旧值回归测试"""

import pytest


class DummyUpdateResult:
    pass


class DummyCollection:
    def __init__(self):
        self.calls = []

    async def update_one(self, query, update, upsert=False):
        self.calls.append((query, update, upsert))
        return DummyUpdateResult()


class DummyDB(dict):
    def __getitem__(self, key):
        if key not in self:
            self[key] = DummyCollection()
        return dict.__getitem__(self, key)


class DummyScanner:
    def __init__(self):
        self._trade_date = "20260625"
        self._current_sentiment = {
            "score": 47.73,
            "period": "chaos",
            "formula": "7dim",
            "dimensions": {
                "limit_up": 35,
                "limit_down": 1,
                "up_count": 2400,
                "down_count": 2600,
                "up_down_ratio": 0.48,
                "max_continue": 4,
                "today_premium": 0.12,
                "momentum": -0.01,
                "broken": 6,
                "broken_rate": 0.146,
                "sample_count": 12,
                "formula": "7dim",
            },
        }

    def get_current_sentiment(self):
        return self._current_sentiment


@pytest.mark.asyncio
async def test_persist_realtime_sentiment_writes_full_intraday_doc(monkeypatch):
    from nodes.market_monitor import emotion_cycle
    from nodes.market_monitor.emotion_cycle import EmotionCycleManager

    db = DummyDB()
    class DummyMongoManager:
        is_initialized = True
    DummyMongoManager.db = db
    monkeypatch.setattr(emotion_cycle, "mongo_manager", DummyMongoManager)

    ok = await EmotionCycleManager.persist_realtime_sentiment(DummyScanner(), "20260625")

    assert ok is True
    calls = db["sentiment_scores"].calls
    assert len(calls) == 1
    query, update, upsert = calls[0]
    doc = update["$set"]
    assert query == {"trade_date": 20260625}
    assert upsert is True
    assert doc["score"] == 47.73
    assert doc["period"] == "震荡"
    assert doc["missing_data"] is False
    assert doc["data_source"] == "scanner_intraday"
    assert doc["limit_up"] == 35
    assert doc["up_count"] == 2400
    assert doc["formula"] == "7dim"


def test_review_forward_prefers_scanner_realtime_over_old_db(monkeypatch):
    from nodes.web.api import scanner_review

    monkeypatch.setattr(scanner_review, "_get_scanner_instance", lambda: DummyScanner())
    doc = scanner_review._scanner_realtime_sentiment_for_date(20260625)

    assert doc is not None
    assert doc["score"] == 47.73
    assert doc["period"] == "震荡"
    assert doc["data_source"] == "scanner_intraday_memory"


def test_live_filter_pipeline_exposes_dimensions():
    from nodes.market_monitor.live_filter_pipeline import LiveFilterPipeline

    pipeline = LiveFilterPipeline()
    pipeline._sentiment_score = 47.73
    pipeline._sentiment_period = "chaos"
    pipeline._last_intraday_dimensions = {"limit_up": 35, "up_count": 2400, "formula": "7dim"}

    info = pipeline.get_sentiment_info()

    assert info["score"] == 47.73
    assert info["period"] == "chaos"
    assert info["formula"] == "7dim"
    assert info["dimensions"]["limit_up"] == 35
