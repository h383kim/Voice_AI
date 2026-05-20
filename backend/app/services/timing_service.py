"""Tiny timing helper: record per-stage latency in milliseconds."""
from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Iterator, MutableMapping


@contextmanager
def timer(label: str, store: MutableMapping[str, float]) -> Iterator[None]:
    """Measure the wrapped block and write elapsed ms into store[label]."""
    start = time.perf_counter()
    try:
        yield
    finally:
        store[label] = round((time.perf_counter() - start) * 1000, 2)
