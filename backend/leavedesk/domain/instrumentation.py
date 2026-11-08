
"""Audit logging and timing for LeaveDesk (FR-9)."""

import functools
import inspect
import logging
import time
from contextlib import contextmanager
from typing import Iterator

logger = logging.getLogger("leavedesk")


class Timer:
    """Holds the elapsed time of a timed operation, in milliseconds."""

    def __init__(self, operation: str) -> None:
        self.operation = operation
        self.elapsed_ms: float = 0.0


@contextmanager
def timed(operation: str) -> Iterator[Timer]:
    """Time the code inside a with block, even if it raises an error.

    Example:
        with timed("load data") as timer:
            ...
        print(timer.elapsed_ms)
    """
    timer = Timer(operation)
    start = time.perf_counter()
    try:
        yield timer
    finally:
        timer.elapsed_ms = (time.perf_counter() - start) * 1000
        logger.info("TIMER %s took %.2f ms", operation, timer.elapsed_ms)


def _describe_call(func, args, kwargs) -> str:
    # Skip self so the log shows only the real arguments.
    if args and hasattr(args[0], func.__name__):
        args = args[1:]
    parts = [repr(arg) for arg in args]
    parts += [f"{key}={value!r}" for key, value in kwargs.items()]
    return f"{func.__qualname__}({', '.join(parts)})"


def audit(func):
    """Log every call: its arguments, whether it worked, and how long it took.

    Works on both normal and async functions.
    """
    if inspect.iscoroutinefunction(func):

        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            call = _describe_call(func, args, kwargs)
            start = time.perf_counter()
            try:
                result = await func(*args, **kwargs)
            except Exception as error:
                _log_failure(call, error, start)
                raise
            _log_success(call, start)
            return result

        return async_wrapper

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        call = _describe_call(func, args, kwargs)
        start = time.perf_counter()
        try:
            result = func(*args, **kwargs)
        except Exception as error:
            _log_failure(call, error, start)
            raise
        _log_success(call, start)
        return result

    return wrapper


def _elapsed_ms(start: float) -> float:
    return (time.perf_counter() - start) * 1000


def _log_success(call: str, start: float) -> None:
    logger.info("AUDIT %s -> OK in %.2f ms", call, _elapsed_ms(start))


def _log_failure(call: str, error: Exception, start: float) -> None:
    logger.warning(
        "AUDIT %s -> FAILED in %.2f ms with %s: %s",
        call,
        _elapsed_ms(start),
        type(error).__name__,
        error,
    )