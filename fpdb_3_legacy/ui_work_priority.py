"""Give pending interactive loads time slices ahead of background history replay."""

from threading import Event, Lock

_active = set()
_lock = Lock()
_pending = Event()


def begin_interactive_load():
    token = object()
    with _lock:
        _active.add(token)
        _pending.set()
    return token


def end_interactive_load(token):
    with _lock:
        _active.discard(token)
        if not _active:
            _pending.clear()


def interactive_load_pending():
    return _pending.is_set()
