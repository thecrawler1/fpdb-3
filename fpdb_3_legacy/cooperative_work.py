"""Cancellation and short GIL-yield checkpoints for CPU-heavy data preparation."""

from threading import local
from time import sleep

context = local()


class TaskCancelled(Exception):
    pass


def checkpoint():
    cancelled = getattr(context, "cancelled", None)
    if cancelled is not None and cancelled.is_set():
        raise TaskCancelled
    # A zero-length sleep can immediately reacquire the GIL on Linux, starving
    # Python Qt event handlers even though the computation is on another thread.
    sleep(.001)
