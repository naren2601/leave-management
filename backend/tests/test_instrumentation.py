import asyncio
import logging

import pytest

from leavedesk.domain.instrumentation import audit, timed


class Calculator:
    @audit
    def divide(self, a, b):
        return a / b

    @audit
    async def add_later(self, a, b=1):
        await asyncio.sleep(0)
        return a + b


def test_audit_logs_a_successful_call(caplog):
    caplog.set_level(logging.INFO, logger="leavedesk")

    assert Calculator().divide(6, 3) == 2

    assert "AUDIT Calculator.divide(6, 3) -> OK" in caplog.text


def test_audit_logs_a_failed_call_and_reraises(caplog):
    caplog.set_level(logging.INFO, logger="leavedesk")

    with pytest.raises(ZeroDivisionError):
        Calculator().divide(1, 0)

    assert "FAILED" in caplog.text
    assert "ZeroDivisionError" in caplog.text


def test_audit_works_on_async_methods(caplog):
    caplog.set_level(logging.INFO, logger="leavedesk")

    assert asyncio.run(Calculator().add_later(2, b=3)) == 5

    assert "Calculator.add_later(2, b=3) -> OK" in caplog.text


def test_audit_keeps_the_function_name():
    assert Calculator.divide.__name__ == "divide"


def test_timed_records_elapsed_time(caplog):
    caplog.set_level(logging.INFO, logger="leavedesk")

    with timed("sum numbers") as timer:
        sum(range(1000))

    assert timer.elapsed_ms >= 0
    assert "TIMER sum numbers took" in caplog.text


def test_timed_still_records_when_an_error_happens(caplog):
    caplog.set_level(logging.INFO, logger="leavedesk")

    with pytest.raises(ValueError):
        with timed("broken step") as timer:
            raise ValueError("boom")

    assert timer.elapsed_ms >= 0
    assert "TIMER broken step took" in caplog.text
