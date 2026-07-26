"""Request pacing that holds across processes.

An in-process limiter was sufficient while the only caller was a long-lived MCP
server handling one request at a time. It is not sufficient now: each CLI
invocation is a separate process with its own limiter, and callers are expected
to fan work out across several at once. Pacing therefore has to live somewhere
both processes can see - a small state file guarded by an exclusive lock.

BnF publishes no rate limit for the SRU, ContentSearch and texteBrut endpoints,
only a policy of open access "except in case of abusive usage". Established
Gallica clients settle on one request every three seconds as the threshold above
which BnF starts treating traffic as malicious, so that is the default here.

Exceeding it does not produce a 429. Gallica answers HTTP 200 with an ALTCHA
"Vérification de sécurité" challenge page, and the resulting block is measured in
hours - so pacing conservatively costs far less than being wrong.

Unix only; `fcntl` has no Windows equivalent here.
"""

from __future__ import annotations

import asyncio
import fcntl
import os
import time
from pathlib import Path

DEFAULT_MIN_INTERVAL_SECONDS = 3.0
MIN_INTERVAL_ENV_VAR = "GALLICA_MIN_REQUEST_INTERVAL"


def configured_interval() -> float:
    """Seconds to leave between requests, overridable by environment."""
    raw = os.environ.get(MIN_INTERVAL_ENV_VAR)
    if raw is None:
        return DEFAULT_MIN_INTERVAL_SECONDS

    try:
        interval = float(raw)
    except ValueError:
        raise ValueError(
            f"{MIN_INTERVAL_ENV_VAR} must be a number of seconds, got {raw!r}"
        ) from None

    if interval < 0:
        raise ValueError(f"{MIN_INTERVAL_ENV_VAR} must not be negative, got {interval}")
    return interval


class CrossProcessRateLimiter:
    """Spaces requests by at least `min_interval`, across every process sharing
    `state_file`."""

    def __init__(self, state_file: Path, min_interval: float) -> None:
        self.state_file = state_file
        self.min_interval = min_interval

    async def acquire(self) -> None:
        """Block until a request may be sent, then claim that slot."""
        if self.min_interval <= 0:
            return

        while True:
            # The lock is held blocking, so it must not run on the event loop.
            wait_seconds = await asyncio.to_thread(self._claim_slot)
            if wait_seconds <= 0:
                return
            await asyncio.sleep(wait_seconds)

    def _claim_slot(self) -> float:
        """Claim the next slot, or report how long until one is free.

        Returns 0 when the slot is claimed. The lock is never held across a
        sleep: waiters release it and retry, so a slow caller cannot wedge the
        others behind it.
        """
        self.state_file.parent.mkdir(parents=True, exist_ok=True)

        with open(self.state_file, "a+", encoding="utf-8") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                handle.seek(0)
                content = handle.read().strip()
                # Wall clock, not monotonic: only wall clock is comparable
                # between processes.
                last_request = float(content) if content else 0.0
                now = time.time()

                # A clock stepping backwards would otherwise stall every caller
                # until real time caught up.
                elapsed = now - last_request
                if 0 <= elapsed < self.min_interval:
                    return self.min_interval - elapsed

                handle.seek(0)
                handle.truncate()
                handle.write(repr(now))
                handle.flush()
                return 0.0
            except ValueError:
                # An unreadable state file should not block requests forever.
                handle.seek(0)
                handle.truncate()
                handle.write(repr(time.time()))
                handle.flush()
                return 0.0
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)
