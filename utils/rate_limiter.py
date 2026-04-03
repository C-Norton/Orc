"""Sliding-window rate limiter for Discord slash commands.

Tracks command frequency per (user_id, guild_id) pair and flags users who
exceed the threshold within the rolling window.
"""

import time
from collections import defaultdict, deque

WINDOW_SECONDS = 10  # Length of the sliding window in seconds.
THRESHOLD = 8  # Maximum commands allowed within WINDOW_SECONDS before flagging.

_windows: dict[tuple[str, str], deque[float]] = defaultdict(deque)


def check_rate_limit(user_id: str, guild_id: str) -> bool:
    """Returns True if the user has exceeded the rate limit threshold.

    Uses a sliding window counter per (user_id, guild_id) pair. Does not block
    the user — callers are responsible for logging and alerting.
    """
    key = (user_id, guild_id)
    now = time.monotonic()
    window = _windows[key]

    while window and window[0] < now - WINDOW_SECONDS:
        window.popleft()

    window.append(now)
    return len(window) > THRESHOLD
