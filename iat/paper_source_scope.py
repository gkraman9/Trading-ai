"""In-process file-bound research capability. No execution permission or label override.

Only the E5 loader registers a source after checking actual files/review bindings.
This is a single-owner producer boundary, not a hostile-Python security sandbox.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from weakref import WeakSet

_CURRENT = ContextVar("iat_e5_paper_source", default=None)
_SOURCES = WeakSet()


def current_source():
    source = _CURRENT.get()
    return source if source in _SOURCES else None


def _register_source(source):
    _SOURCES.add(source)
    return source


@contextmanager
def source_scope(source):
    if source not in _SOURCES:
        raise ValueError("E5_UNQUALIFIED_SOURCE_CAPABILITY")
    token = _CURRENT.set(source)
    try:
        yield source
    finally:
        _CURRENT.reset(token)


def require_scope(owner):
    if owner is not current_source():
        raise ValueError("E5_SOURCE_SCOPE_MISMATCH")


def context_allowed(context, owner):
    active = current_source()
    if owner is not active:
        return False
    return (
        context.provenance == "SYNTHETIC_RESEARCH"
        if active is None
        else active.authenticates_context(context)
    )


def report_allowed(report, owner):
    active = current_source()
    return owner is active and report.get("provenance") == (
        "SYNTHETIC_RESEARCH" if active is None else active.provenance
    )
