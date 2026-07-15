"""Per-key quota / concurrency / RPM enforcement for inbound db_sk_ keys."""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from typing import Any


class KeyQuotaError(Exception):
    def __init__(self, message: str, status_code: int = 429) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


class KeyQuotaGate:
    """Process-local concurrency + RPM gate; durable quotas live on the store."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._inflight: dict[str, int] = defaultdict(int)
        self._rpm: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key_row: dict[str, Any]) -> None:
        key_id = key_row.get("key_id") or ""
        max_req = key_row.get("max_requests")
        used_req = int(key_row.get("used_requests") or 0)
        if max_req is not None and used_req >= int(max_req):
            raise KeyQuotaError(f"API key request quota exceeded ({used_req}/{max_req})")

        max_tok = key_row.get("max_tokens")
        used_tok = int(key_row.get("used_tokens") or 0)
        if max_tok is not None and used_tok >= int(max_tok):
            raise KeyQuotaError(f"API key token quota exceeded ({used_tok}/{max_tok})")

        conc = key_row.get("concurrency_limit")
        rpm = key_row.get("rpm_limit")
        now = time.monotonic()
        with self._lock:
            if conc is not None and self._inflight[key_id] >= int(conc):
                raise KeyQuotaError(
                    f"API key concurrency limit exceeded ({conc})",
                )
            if rpm is not None:
                window = self._rpm[key_id]
                while window and now - window[0] >= 60.0:
                    window.popleft()
                if len(window) >= int(rpm):
                    raise KeyQuotaError(f"API key RPM limit exceeded ({rpm}/min)")

    def acquire(self, key_row: dict[str, Any]) -> None:
        """Reserve concurrency + RPM slots after check() passed."""
        key_id = key_row.get("key_id") or ""
        now = time.monotonic()
        with self._lock:
            self._inflight[key_id] += 1
            if key_row.get("rpm_limit") is not None:
                self._rpm[key_id].append(now)

    def release(self, key_id: str) -> None:
        with self._lock:
            if self._inflight[key_id] > 0:
                self._inflight[key_id] -= 1
