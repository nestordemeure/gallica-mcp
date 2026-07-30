"""Request pacing that holds across processes.

An in-process limiter was sufficient while the only caller was a long-lived MCP
server handling one request at a time. It is not sufficient now: each CLI
invocation is a separate process with its own limiter, and callers are expected
to fan work out across several at once. Pacing therefore has to live somewhere
both processes can see - a small state file guarded by an exclusive lock.

BnF publishes no rate limit for the SRU and ContentSearch endpoints, only a
policy of open access "except in case of abusive usage". Established Gallica
clients settle on one request every three seconds as the threshold above which
BnF starts treating traffic as malicious, so that is the default here.

Exceeding it does not produce a 429. Gallica answers HTTP 200 with an ALTCHA
"Vérification de sécurité" challenge page, and the resulting block is measured in
hours - so pacing conservatively costs far less than being wrong.

The OCR endpoint is metered differently, and needs a second limiter on top.
`RequestDigitalElement` does not care about spacing: measured against it, five
requests three seconds apart and four requests five seconds apart both ended in
HTTP 429, and roughly two minutes of quiet restored the allowance. That is a
token bucket - a small burst plus a slow refill - so `CrossProcessTokenBucket`
models it as one. Pacing alone cannot express it: a short download should go at
full speed, and only a long one should crawl.

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

#: OCR budget, from measurement rather than documentation: 429 arrived on the
#: fifth request of a burst, so the capacity is set one below the smallest
#: observed failure point, and the refill to the ~25s/request that two minutes
#: of recovery for five requests implies.
DEFAULT_OCR_BURST = 4
DEFAULT_OCR_REFILL_SECONDS = 25.0
OCR_BURST_ENV_VAR = "GALLICA_OCR_BURST"
OCR_REFILL_ENV_VAR = "GALLICA_OCR_REFILL_SECONDS"


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


def _configured_number(variable: str, default: float, minimum: float) -> float:
    """Read a numeric override from the environment, or fall back."""
    raw = os.environ.get(variable)
    if raw is None:
        return default

    try:
        value = float(raw)
    except ValueError:
        raise ValueError(f"{variable} must be a number, got {raw!r}") from None

    if value < minimum:
        raise ValueError(f"{variable} must be at least {minimum}, got {value}")
    return value


def configured_ocr_burst() -> float:
    """How many OCR pages may be fetched back to back."""
    return _configured_number(OCR_BURST_ENV_VAR, DEFAULT_OCR_BURST, 1)


def configured_ocr_refill() -> float:
    """Seconds the OCR budget takes to regain one request."""
    return _configured_number(OCR_REFILL_ENV_VAR, DEFAULT_OCR_REFILL_SECONDS, 0)


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


class CrossProcessTokenBucket:
    """A burst allowance that refills over time, shared across processes.

    Gallica's OCR endpoint tolerates a few requests in quick succession and
    then refuses for minutes, which a minimum-interval limiter cannot express:
    set the interval short and a long download walks into a 429, set it long
    and fetching three pages takes over a minute for no reason. A bucket gives
    both - the common case of a few pages runs at full speed, and only a
    download long enough to actually exhaust the budget slows to the refill
    rate.

    State is the same shape as :class:`CrossProcessRateLimiter`'s: a file under
    the shared cache, so subagents fanned out across processes draw on one
    budget rather than each believing it has its own.
    """

    def __init__(self, state_file: Path, capacity: float, refill_seconds: float) -> None:
        self.state_file = state_file
        self.capacity = capacity
        self.refill_seconds = refill_seconds

    async def acquire(self) -> None:
        """Block until a token is available, then spend it."""
        if self.refill_seconds <= 0:
            return

        while True:
            wait_seconds = await asyncio.to_thread(self._take_token)
            if wait_seconds <= 0:
                return
            await asyncio.sleep(wait_seconds)

    async def drain(self) -> None:
        """Empty the bucket after the server has refused a request.

        A 429 means the real budget was already lower than this bucket
        believed. Zeroing it stops the next call - very possibly in another
        process - from spending a token the server will not honour, which is
        how a single refusal turns into a run of them.
        """
        if self.refill_seconds <= 0:
            return
        await asyncio.to_thread(self._zero)

    def _zero(self) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.state_file, "a+", encoding="utf-8") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                self._write_state(handle, 0.0, time.time())
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def _take_token(self) -> float:
        """Spend a token, or report the seconds until one exists."""
        self.state_file.parent.mkdir(parents=True, exist_ok=True)

        with open(self.state_file, "a+", encoding="utf-8") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                handle.seek(0)
                tokens, updated_at = self._read_state(handle.read().strip())
                now = time.time()

                # A clock stepping backwards must not hand out free tokens, nor
                # stall every caller until real time catches up.
                elapsed = max(now - updated_at, 0.0)
                tokens = min(self.capacity, tokens + elapsed / self.refill_seconds)

                if tokens < 1.0:
                    return (1.0 - tokens) * self.refill_seconds

                self._write_state(handle, tokens - 1.0, now)
                return 0.0
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def _read_state(self, content: str) -> tuple[float, float]:
        """Parse the state file, treating anything unreadable as a full bucket.

        A corrupt file should not wedge downloads forever; the worst case is one
        burst more than the budget allowed, which the server answers with a 429
        the client already handles.
        """
        try:
            tokens_text, _, updated_text = content.partition(" ")
            return float(tokens_text), float(updated_text)
        except ValueError:
            return self.capacity, time.time()

    @staticmethod
    def _write_state(handle, tokens: float, now: float) -> None:
        handle.seek(0)
        handle.truncate()
        handle.write(f"{tokens!r} {now!r}")
        handle.flush()
