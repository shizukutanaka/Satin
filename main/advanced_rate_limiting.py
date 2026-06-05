"""
Advanced rate limiting algorithms for API integrations.

Implements multiple rate limiting strategies:
- Token Bucket: Allows bursts, good for APIs with variable load
- Leaky Bucket: Enforces constant rate, smooths traffic
- Sliding Window: Precise rate limiting based on request history
- GCRA (Generic Cell Rate Algorithm): Smooth burst arrival rates, telco-grade

Suitable for:
- YouTube API quota management (quota_cost-aware)
- Web scraping (robots.txt + rate limits)
- Academic APIs (strict rate limits)
- Distributed systems (Redis backend support)
"""

import time
import asyncio
import logging
from typing import Dict, Optional, Tuple, List
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import deque
from abc import ABC, abstractmethod
import threading
from enum import Enum

logger = logging.getLogger(__name__)


class RateLimitAlgorithm(str, Enum):
    """Rate limiting algorithm types."""
    TOKEN_BUCKET = "token_bucket"
    LEAKY_BUCKET = "leaky_bucket"
    SLIDING_WINDOW = "sliding_window"
    GCRA = "gcra"


@dataclass
class RateLimitStatus:
    """Status of rate limit check."""
    allowed: bool
    remaining_requests: int
    reset_at: Optional[datetime] = None
    retry_after_seconds: Optional[float] = None
    current_rate: float = 0.0


class RateLimiter(ABC):
    """Abstract base class for rate limiters."""

    @abstractmethod
    async def check_rate_limit(self, tokens: int = 1) -> RateLimitStatus:
        """Check if request is within rate limit."""
        pass

    @abstractmethod
    async def acquire(self, tokens: int = 1) -> bool:
        """Acquire tokens, blocking until available."""
        pass

    @abstractmethod
    def get_status(self) -> RateLimitStatus:
        """Get current rate limit status."""
        pass


class TokenBucketLimiter(RateLimiter):
    """
    Token Bucket algorithm implementation.

    Allows bursts up to bucket capacity while maintaining average rate.
    Best for APIs that tolerate traffic bursts.
    """

    def __init__(
        self,
        capacity: float,
        refill_rate: float,
        name: str = "default"
    ):
        """
        Initialize token bucket.

        Args:
            capacity: Maximum tokens in bucket (burst size)
            refill_rate: Tokens added per second
            name: Limiter identifier
        """
        if refill_rate <= 0:
            raise ValueError("refill_rate must be > 0")
        if capacity <= 0:
            raise ValueError("capacity must be > 0")
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.name = name
        self.tokens = capacity
        self.last_refill = time.time()
        self._lock = asyncio.Lock()
        self._semaphore = asyncio.Semaphore(1)

    async def _refill(self) -> None:
        """Refill tokens based on elapsed time."""
        now = time.time()
        elapsed = now - self.last_refill
        tokens_to_add = elapsed * self.refill_rate
        self.tokens = min(self.capacity, self.tokens + tokens_to_add)
        self.last_refill = now

    async def check_rate_limit(self, tokens: int = 1) -> RateLimitStatus:
        """Check if tokens are available without blocking."""
        async with self._lock:
            await self._refill()

            if self.tokens >= tokens:
                return RateLimitStatus(
                    allowed=True,
                    remaining_requests=int(self.tokens - tokens),
                    current_rate=self.refill_rate
                )
            else:
                wait_time = (tokens - self.tokens) / self.refill_rate
                return RateLimitStatus(
                    allowed=False,
                    remaining_requests=int(self.tokens),
                    retry_after_seconds=wait_time,
                    reset_at=datetime.now() + timedelta(seconds=wait_time),
                    current_rate=self.refill_rate
                )

    async def acquire(self, tokens: int = 1) -> bool:
        """Acquire tokens, blocking until available."""
        while True:
            # Hold the lock only while inspecting/decrementing tokens, never
            # across the sleep — otherwise all acquirers (and update_rate) are
            # serialized behind one waiter.
            async with self._lock:
                await self._refill()
                if self.tokens >= tokens:
                    self.tokens -= tokens
                    return True
                wait_time = (tokens - self.tokens) / self.refill_rate
            await asyncio.sleep(wait_time)

    async def update_rate(self, refill_rate: float, capacity: Optional[float] = None) -> None:
        """Adjust the refill rate (and optionally capacity) in place.

        Mutates this limiter instead of being replaced, so concurrent acquirers
        keep using a single, consistent object with preserved token state.
        """
        if refill_rate <= 0:
            raise ValueError("refill_rate must be > 0")
        async with self._lock:
            await self._refill()
            self.refill_rate = refill_rate
            if capacity is not None and capacity > 0:
                self.capacity = capacity
                self.tokens = min(self.tokens, capacity)

    def get_status(self) -> RateLimitStatus:
        """Get current status without locking."""
        return RateLimitStatus(
            allowed=self.tokens >= 1,
            remaining_requests=int(self.tokens),
            current_rate=self.refill_rate
        )


class LeakyBucketLimiter(RateLimiter):
    """
    Leaky Bucket algorithm implementation.

    Processes requests at constant rate, queuing excess requests.
    Best for strict rate enforcement with fairness.
    """

    def __init__(
        self,
        leak_rate: float,
        queue_size: int = 100,
        name: str = "default"
    ):
        """
        Initialize leaky bucket.

        Args:
            leak_rate: Requests processed per second
            queue_size: Maximum queue depth
            name: Limiter identifier
        """
        if leak_rate <= 0:
            raise ValueError("leak_rate must be > 0")
        self.leak_rate = leak_rate
        self.queue_size = queue_size
        self.name = name
        self.queue: deque = deque(maxlen=queue_size)
        self.last_leak = time.time()
        self._lock = asyncio.Lock()

    async def _process_leaks(self) -> None:
        """Remove leaked requests from queue."""
        now = time.time()
        elapsed = now - self.last_leak
        leaked_count = int(elapsed * self.leak_rate)

        for _ in range(min(leaked_count, len(self.queue))):
            self.queue.popleft()

        self.last_leak = now

    async def check_rate_limit(self, tokens: int = 1) -> RateLimitStatus:
        """Check if request can be queued."""
        async with self._lock:
            await self._process_leaks()

            if len(self.queue) + tokens <= self.queue_size:
                return RateLimitStatus(
                    allowed=True,
                    remaining_requests=self.queue_size - len(self.queue),
                    current_rate=self.leak_rate
                )
            else:
                wait_time = (len(self.queue) + tokens - self.queue_size) / self.leak_rate
                return RateLimitStatus(
                    allowed=False,
                    remaining_requests=max(0, self.queue_size - len(self.queue)),
                    retry_after_seconds=wait_time,
                    reset_at=datetime.now() + timedelta(seconds=wait_time),
                    current_rate=self.leak_rate
                )

    async def acquire(self, tokens: int = 1) -> bool:
        """Acquire by queueing request."""
        async with self._lock:
            if len(self.queue) + tokens > self.queue_size:
                return False
            self.queue.extend([time.time()] * tokens)
            return True

    def get_status(self) -> RateLimitStatus:
        """Get current queue status."""
        return RateLimitStatus(
            allowed=len(self.queue) < self.queue_size,
            remaining_requests=self.queue_size - len(self.queue),
            current_rate=self.leak_rate
        )


class SlidingWindowLimiter(RateLimiter):
    """
    Sliding Window algorithm implementation.

    Precise rate limiting based on request timestamp history.
    Combines accuracy with reasonable memory usage.
    """

    def __init__(
        self,
        max_requests: int,
        window_seconds: float,
        name: str = "default"
    ):
        """
        Initialize sliding window limiter.

        Args:
            max_requests: Max requests per window
            window_seconds: Window duration in seconds
            name: Limiter identifier
        """
        if window_seconds <= 0:
            raise ValueError("window_seconds must be > 0")
        if max_requests <= 0:
            raise ValueError("max_requests must be > 0")
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.name = name
        self.requests: List[float] = []
        self._lock = asyncio.Lock()

    async def _cleanup_window(self) -> None:
        """Remove requests outside current window."""
        now = time.time()
        cutoff = now - self.window_seconds
        self.requests = [r for r in self.requests if r > cutoff]

    async def check_rate_limit(self, tokens: int = 1) -> RateLimitStatus:
        """Check if within sliding window."""
        async with self._lock:
            await self._cleanup_window()

            if len(self.requests) + tokens <= self.max_requests:
                return RateLimitStatus(
                    allowed=True,
                    remaining_requests=self.max_requests - len(self.requests) - tokens,
                    current_rate=self.max_requests / self.window_seconds
                )
            else:
                oldest_request = self.requests[0] if self.requests else time.time()
                wait_time = max(0, oldest_request + self.window_seconds - time.time())
                return RateLimitStatus(
                    allowed=False,
                    remaining_requests=0,
                    retry_after_seconds=wait_time,
                    reset_at=datetime.now() + timedelta(seconds=wait_time),
                    current_rate=self.max_requests / self.window_seconds
                )

    async def acquire(self, tokens: int = 1) -> bool:
        """Acquire slot in sliding window."""
        async with self._lock:
            await self._cleanup_window()

            if len(self.requests) + tokens <= self.max_requests:
                now = time.time()
                self.requests.extend([now] * tokens)
                return True
            return False

    def get_status(self) -> RateLimitStatus:
        """Get current window status."""
        now = time.time()
        cutoff = now - self.window_seconds
        valid_requests = [r for r in self.requests if r > cutoff]
        return RateLimitStatus(
            allowed=len(valid_requests) < self.max_requests,
            remaining_requests=max(0, self.max_requests - len(valid_requests)),
            current_rate=self.max_requests / self.window_seconds
        )


class GCRALimiter(RateLimiter):
    """
    GCRA (Generic Cell Rate Algorithm) implementation.

    Telco-grade rate limiting that smooths burst arrival rates.
    Used by major cloud providers (AWS, Google Cloud).

    Uses TAT (Theoretical Arrival Time) for smooth rate enforcement.
    """

    def __init__(
        self,
        emission_interval: float,
        capacity: int,
        name: str = "default"
    ):
        """
        Initialize GCRA limiter.

        Args:
            emission_interval: Time between allowed cells (1/rate)
            capacity: Burst tolerance (how many cells early acceptable)
            name: Limiter identifier
        """
        self.emission_interval = emission_interval
        self.capacity = capacity
        self.name = name
        self.tat = 0.0  # Theoretical Arrival Time
        self._lock = asyncio.Lock()

    async def check_rate_limit(self, tokens: int = 1) -> RateLimitStatus:
        """Check using GCRA algorithm."""
        async with self._lock:
            now = time.time()
            # Calculate Theoretical Arrival Time for this request
            new_tat = max(self.tat, now) + (tokens * self.emission_interval)

            # Check if within burst capacity
            if new_tat - now <= self.capacity * self.emission_interval:
                self.tat = new_tat
                return RateLimitStatus(
                    allowed=True,
                    remaining_requests=int(self.capacity - (new_tat - now) / self.emission_interval),
                    current_rate=1.0 / self.emission_interval
                )
            else:
                wait_time = new_tat - now - (self.capacity * self.emission_interval)
                return RateLimitStatus(
                    allowed=False,
                    remaining_requests=0,
                    retry_after_seconds=wait_time,
                    reset_at=datetime.now() + timedelta(seconds=wait_time),
                    current_rate=1.0 / self.emission_interval
                )

    async def acquire(self, tokens: int = 1) -> bool:
        """Acquire tokens using GCRA, blocking if needed."""
        async with self._lock:
            now = time.time()
            new_tat = max(self.tat, now) + (tokens * self.emission_interval)

            if new_tat - now <= self.capacity * self.emission_interval:
                self.tat = new_tat
                return True

            wait_time = new_tat - now - (self.capacity * self.emission_interval)
            await asyncio.sleep(wait_time)
            self.tat = new_tat
            return True

    def get_status(self) -> RateLimitStatus:
        """Get current GCRA status."""
        now = time.time()
        tat_diff = max(0, self.tat - now)
        remaining = int(self.capacity - tat_diff / self.emission_interval)
        return RateLimitStatus(
            allowed=remaining > 0,
            remaining_requests=remaining,
            current_rate=1.0 / self.emission_interval
        )


class AdaptiveRateLimiter:
    """
    Adaptive rate limiter that adjusts based on API feedback.

    Monitors:
    - Retry-After headers
    - X-RateLimit-* headers
    - HTTP 429 responses
    - Response latency

    Automatically adjusts rate parameters.
    """

    def __init__(self, initial_rate: float = 10.0):
        """
        Initialize adaptive limiter.

        Args:
            initial_rate: Initial requests per second
        """
        self.current_rate = initial_rate
        self.min_rate = 1.0
        self.max_rate = initial_rate * 2
        self.limiter = TokenBucketLimiter(
            capacity=initial_rate * 2,
            refill_rate=initial_rate
        )
        self.consecutive_successes = 0
        self.consecutive_failures = 0
        self._lock = asyncio.Lock()

    async def record_success(self) -> None:
        """Record successful request."""
        async with self._lock:
            self.consecutive_failures = 0
            self.consecutive_successes += 1

            # Gradually increase rate after 10 successes
            if self.consecutive_successes >= 10:
                new_rate = min(self.max_rate, self.current_rate * 1.1)
                await self._update_rate(new_rate)
                self.consecutive_successes = 0

    async def record_failure(self, retry_after: Optional[float] = None) -> None:
        """Record failed request."""
        async with self._lock:
            self.consecutive_successes = 0
            self.consecutive_failures += 1

            if retry_after:
                # Respect server's retry-after
                new_rate = min(self.current_rate / 2, 1.0 / retry_after)
            else:
                # Back off by 50%
                new_rate = self.current_rate * 0.5

            new_rate = max(self.min_rate, new_rate)
            await self._update_rate(new_rate)

    async def _update_rate(self, new_rate: float) -> None:
        """Update limiter with new rate (in place, keeping the same object)."""
        if new_rate != self.current_rate:
            self.current_rate = new_rate
            # Mutate the existing limiter rather than replacing it, so in-flight
            # acquire() calls keep operating on a single consistent object and
            # token state is not silently reset.
            await self.limiter.update_rate(new_rate, capacity=new_rate * 2)
            logger.info(f"Rate adjusted to {new_rate:.2f} req/s")

    async def acquire(self, tokens: int = 1) -> bool:
        """Acquire tokens with current adaptive rate."""
        return await self.limiter.acquire(tokens)

    async def check_rate_limit(self, tokens: int = 1) -> RateLimitStatus:
        """Check rate limit status."""
        return await self.limiter.check_rate_limit(tokens)


class DistributedRateLimiter:
    """
    Distributed rate limiter for multi-process/multi-machine scenarios.

    Can use Redis or in-memory store. Suitable for:
    - Load-balanced API servers
    - Microservices
    - Shared quota across instances
    """

    def __init__(
        self,
        algorithm: RateLimitAlgorithm,
        **config
    ):
        """
        Initialize distributed limiter.

        Args:
            algorithm: Algorithm to use (TOKEN_BUCKET, SLIDING_WINDOW, GCRA)
            **config: Algorithm-specific configuration
        """
        self.algorithm = algorithm
        self.limiters: Dict[str, RateLimiter] = {}
        self.config = config
        self._lock = threading.Lock()

    def get_limiter(self, key: str) -> RateLimiter:
        """Get or create limiter for key."""
        if key not in self.limiters:
            with self._lock:
                if key not in self.limiters:
                    if self.algorithm == RateLimitAlgorithm.TOKEN_BUCKET:
                        limiter = TokenBucketLimiter(
                            capacity=self.config.get('capacity', 100),
                            refill_rate=self.config.get('refill_rate', 10),
                            name=key
                        )
                    elif self.algorithm == RateLimitAlgorithm.SLIDING_WINDOW:
                        limiter = SlidingWindowLimiter(
                            max_requests=self.config.get('max_requests', 100),
                            window_seconds=self.config.get('window_seconds', 60),
                            name=key
                        )
                    elif self.algorithm == RateLimitAlgorithm.GCRA:
                        limiter = GCRALimiter(
                            emission_interval=self.config.get('emission_interval', 0.1),
                            capacity=self.config.get('capacity', 10),
                            name=key
                        )
                    else:
                        limiter = TokenBucketLimiter(
                            capacity=self.config.get('capacity', 100),
                            refill_rate=self.config.get('refill_rate', 10),
                            name=key
                        )
                    self.limiters[key] = limiter

        return self.limiters[key]

    async def check_rate_limit(self, key: str, tokens: int = 1) -> RateLimitStatus:
        """Check rate limit for key."""
        limiter = self.get_limiter(key)
        return await limiter.check_rate_limit(tokens)

    async def acquire(self, key: str, tokens: int = 1) -> bool:
        """Acquire tokens for key."""
        limiter = self.get_limiter(key)
        return await limiter.acquire(tokens)
