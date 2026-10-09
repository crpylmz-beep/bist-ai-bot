"""Bounded in-memory daily-history coalescing; manual analysis stays unrestricted.

A one-second cache only coalesces overlapping scans, not separate five-minute bars.
Failures are not cached and independent symbol locks do not serialize the universe.
"""
from collections import OrderedDict
from threading import RLock
from time import monotonic
from copy import deepcopy

_lock=RLock()
_cache=OrderedDict()
_locks={}
MAX_ENTRIES=650
TTL=1.0


def history(ticker, symbol, period):
    key=(symbol,period)
    with _lock:
        if key not in _locks and len(_locks)<MAX_ENTRIES:
            _locks[key]=RLock()
        guard=_locks.get(key)
    if guard is None:return ticker.history(period=period)
    with guard:
        with _lock:
            item=_cache.get(key)
            if item and monotonic()-item[0]<TTL:return deepcopy(item[1])
        value=ticker.history(period=period)
        if value is not None and not value.empty:
            with _lock:
                _cache[key]=(monotonic(),deepcopy(value));_cache.move_to_end(key)
                while len(_cache)>MAX_ENTRIES:_cache.popitem(last=False)
        return value
