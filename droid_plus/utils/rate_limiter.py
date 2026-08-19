# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""
Rate limiting utilities for control loops.
"""
from __future__ import annotations

import time


class RateLimiter:
    """
    Drift-corrected rate limiter for fixed-frequency control loops.

    Uses wall-clock time to maintain a consistent average rate, even when
    individual iterations take varying amounts of time.

    Example:
        rate = RateLimiter(rate_hz=50.0)  # 50 Hz = 20ms per iteration

        while running:
            # Do work...
            process_data()

            # Sleep to maintain rate
            rate.sleep()
    """

    def __init__(self, rate_hz: float) -> None:
        """
        Initialize the rate limiter.

        Args:
            rate_hz: Target frequency in Hz (iterations per second)
        """
        if rate_hz <= 0:
            raise ValueError("rate_hz must be positive")

        self._period_s = 1.0 / float(rate_hz)
        self._rate_hz = float(rate_hz)
        self._t_next = time.time()

    @property
    def rate_hz(self) -> float:
        """Target rate in Hz."""
        return self._rate_hz

    @property
    def period_s(self) -> float:
        """Target period in seconds."""
        return self._period_s

    def reset(self) -> None:
        """Reset the timing reference to now."""
        self._t_next = time.time()

    def sleep(self) -> float:
        """
        Sleep to maintain the target rate.

        Uses drift correction: if previous iterations ran long, this will
        sleep less (or not at all) to catch up.

        Returns:
            Actual sleep duration in seconds (may be 0 if behind schedule)
        """
        self._t_next += self._period_s
        sleep_s = self._t_next - time.time()

        if sleep_s > 0:
            time.sleep(sleep_s)
            return sleep_s
        else:
            # Behind schedule - don't sleep, but don't accumulate debt forever
            # Reset if we're more than 10 periods behind
            if sleep_s < -10 * self._period_s:
                self.reset()
            return 0.0

    def time_until_next(self) -> float:
        """
        Return time remaining until next scheduled tick.

        Returns:
            Seconds until next tick (negative if behind schedule)
        """
        return self._t_next - time.time()
