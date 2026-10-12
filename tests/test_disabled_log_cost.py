"""Disabled wrapper calls avoid stack inspection and lazy argument formatting."""

import logging
from pathlib import Path

import pytest

from fpdb_3_legacy.loggingFpdb import FpdbLogger

CALLS = (("debug", logging.DEBUG), ("info", logging.INFO), ("log", logging.DEBUG),
         ("log", logging.INFO), ("log", logging.WARNING))


class ExpensiveArgument:
    def __init__(self):
        self.calls = 0

    def __str__(self):
        self.calls += 1
        return "formatted argument"


class Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []
        self.formatted = []
        self.setFormatter(logging.Formatter("%(funcName)s: %(message)s"))

    def emit(self, record):
        self.records.append(record)
        self.formatted.append(self.format(record))


@pytest.fixture
def wrapped(monkeypatch):
    wrapper = FpdbLogger("fpdb.tests.disabled_log_cost")
    # A standalone logger avoids registry/root-handler mutations and file I/O.
    logger = logging.Logger("fpdb.tests.disabled_log_cost", logging.DEBUG)
    logger.propagate = False
    capture = Capture()
    logger.addHandler(capture)
    monkeypatch.setattr(wrapper, "logger", logger)
    yield wrapper, capture
    capture.close()


def invoke(wrapper, method, level, argument):
    if method == "log":
        wrapper.log(level, "value=%s", argument)
    else:
        getattr(wrapper, method)("value=%s", argument)


@pytest.mark.parametrize(("method", "level"), CALLS)
@pytest.mark.parametrize("disabled_by", ["threshold", "logger_disabled"])
def test_disabled_calls_skip_caller_walk_and_argument_formatting(wrapped, monkeypatch, method, level, disabled_by):
    wrapper, capture = wrapped
    if disabled_by == "threshold":
        wrapper.logger.setLevel(logging.ERROR)
    else:
        wrapper.logger.disabled = True

    def forbidden_walk():
        raise AssertionError("Disabled logging inspected the caller stack")

    monkeypatch.setattr(wrapper, "_get_stacklevel", forbidden_walk)
    argument = ExpensiveArgument()
    invoke(wrapper, method, level, argument)
    assert argument.calls == 0
    assert capture.records == capture.formatted == []


@pytest.mark.parametrize(("method", "level"), CALLS)
def test_enabled_calls_preserve_formatting_and_caller_stacklevel(wrapped, monkeypatch, method, level):
    wrapper, capture = wrapped
    walks = []

    def caller_stacklevel():
        walks.append(True)
        # The wrapper must forward this value unchanged to logging: one frame
        # for its own method, then the actual caller below.
        return 2

    monkeypatch.setattr(wrapper, "_get_stacklevel", caller_stacklevel)
    argument = ExpensiveArgument()
    invoke(wrapper, method, level, argument)
    assert walks == [True]
    assert argument.calls == 1
    assert len(capture.records) == 1
    record = capture.records[0]
    assert record.levelno == level
    assert record.funcName == "invoke"
    assert Path(record.pathname) == Path(__file__)
    assert record.lineno in range(invoke.__code__.co_firstlineno, invoke.__code__.co_firstlineno + 6)
    assert record.msg == "value=%s" and record.args == (argument,)
    assert capture.formatted == ["invoke: value=formatted argument"]
