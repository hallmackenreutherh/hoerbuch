"""Optionale strukturierte Fortschrittsereignisse; die CLI bleibt unverändert."""
from contextlib import contextmanager
from contextvars import ContextVar

_listener = ContextVar("hoerbuch_progress_listener", default=None)


@contextmanager
def beobachten(listener):
    token = _listener.set(listener)
    try:
        yield
    finally:
        _listener.reset(token)


def aktiv():
    return _listener.get() is not None


def melden(phase, text, erledigt=None, gesamt=None):
    listener = _listener.get()
    if listener:
        event = {"phase": phase, "text": text}
        if gesamt is not None and gesamt > 0 and erledigt is not None:
            event.update(erledigt=max(0, min(erledigt, gesamt)), gesamt=gesamt)
        listener(event)
