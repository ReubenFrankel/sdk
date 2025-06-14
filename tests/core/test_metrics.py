from __future__ import annotations

import json
import logging
import os

import pytest
import time_machine

from singer_sdk import metrics
from singer_sdk.helpers._compat import SingerSDKDeprecationWarning


class CustomObject:
    def __init__(self, name: str, value: int):
        self.name = name
        self.value = value

    def __str__(self) -> str:
        return f"{self.name}={self.value}"


def test_singer_metrics_formatter():
    with pytest.warns(SingerSDKDeprecationWarning):
        formatter = metrics.SingerMetricsFormatter(fmt="{metric_json}", style="{")

    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="test.py",
        lineno=1,
        msg="METRIC",
        args=(),
        exc_info=None,
    )

    assert not formatter.format(record)

    metric_dict = {
        "type": "counter",
        "metric": "test_metric",
        "tags": {"test_tag": "test_value"},
        "value": 1,
    }
    record.__dict__["point"] = metric_dict

    assert formatter.format(record) == json.dumps(metric_dict)


def test_meter():
    pid = os.getpid()

    class _MyMeter(metrics.Meter):
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

    meter = _MyMeter(metrics.Metric.RECORD_COUNT)

    assert meter.tags == {metrics.Tag.PID: pid}

    stream_context = {"parent_id": 1}
    meter.context = stream_context
    assert meter.tags == {
        metrics.Tag.CONTEXT: stream_context,
        metrics.Tag.PID: pid,
    }

    meter.context = None
    assert metrics.Tag.CONTEXT not in meter.tags


def test_record_counter(caplog: pytest.LogCaptureFixture):
    metrics_logger = logging.getLogger(metrics.METRICS_LOGGER_NAME)
    metrics_logger.propagate = True

    caplog.set_level(logging.INFO, logger=metrics.METRICS_LOGGER_NAME)
    pid = os.getpid()
    custom_object = CustomObject("test", 1)

    with metrics.record_counter(
        "test_stream",
        endpoint="test_endpoint",
        custom_tag="pytest",
        custom_obj=custom_object,
    ) as counter:
        for _ in range(100):
            counter.last_log_time = 0
            assert counter._ready_to_log()

            counter.increment()

    total = 0

    assert len(caplog.records) == 100 + 1
    # raise AssertionError

    for record in caplog.records:
        assert record.levelname == "INFO"
        assert record.msg.startswith("METRIC")

        point = record.__dict__["point"]
        assert point["type"] == "counter"
        assert point["metric"] == "record_count"
        assert point["tags"] == {
            metrics.Tag.STREAM: "test_stream",
            metrics.Tag.ENDPOINT: "test_endpoint",
            metrics.Tag.PID: pid,
            "custom_tag": "pytest",
            "custom_obj": custom_object,
        }

        total += point["value"]

    assert total == 100


def test_sync_timer(caplog: pytest.LogCaptureFixture):
    metrics_logger = logging.getLogger(metrics.METRICS_LOGGER_NAME)
    metrics_logger.propagate = True

    caplog.set_level(logging.INFO, logger=metrics.METRICS_LOGGER_NAME)

    pid = os.getpid()
    traveler = time_machine.travel(0, tick=False)
    traveler.start()

    with metrics.sync_timer("test_stream", custom_tag="pytest"):
        traveler.stop()

        traveler = time_machine.travel(10, tick=False)
        traveler.start()

    traveler.stop()

    record = caplog.records[0]
    assert record.levelname == "INFO"
    assert record.msg.startswith("METRIC")

    point = record.__dict__["point"]
    assert point["type"] == "timer"
    assert point["metric"] == "sync_duration"
    assert point["tags"] == {
        metrics.Tag.STREAM: "test_stream",
        metrics.Tag.STATUS: "succeeded",
        metrics.Tag.PID: pid,
        "custom_tag": "pytest",
    }

    assert pytest.approx(point["value"], rel=0.001) == 10.0
