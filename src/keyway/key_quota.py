"""Per-key quota / concurrency / RPM enforcement for inbound db_sk_ keys."""

from __future__ import annotations

import threading
import time
from collections import deque
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
        self._inflight: dict[str, int] = {}
        self._rpm: dict[str, deque[float]] = {}

    def check_and_acquire(self, key_row: dict[str, Any]) -> None:
        """Check durable quotas + concurrency/RPM limits and reserve the
        slots in a single lock hold (no TOCTOU gap between check and
        acquire). The caller must call :meth:`release` when done.
        """
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
            if conc is not None and self._inflight.get(key_id, 0) >= int(conc):
                raise KeyQuotaError(
                    f"API key concurrency limit exceeded ({conc})",
                )
            window = self._rpm.get(key_id)
            if window is not None:
                while window and now - window[0] >= 60.0:
                    window.popleft()
                if not window:
                    del self._rpm[key_id]
                    window = None
            if rpm is not None and window is not None and len(window) >= int(rpm):
                raise KeyQuotaError(f"API key RPM limit exceeded ({rpm}/min)")
            self._inflight[key_id] = self._inflight.get(key_id, 0) + 1
            if rpm is not None:
                if window is None:
                    window = deque()
                    self._rpm[key_id] = window
                window.append(now)

    def release(self, key_id: str) -> None:
        with self._lock:
            n = self._inflight.get(key_id, 0)
            if n <= 1:
                self._inflight.pop(key_id, None)
            else:
                self._inflight[key_id] = n - 1
