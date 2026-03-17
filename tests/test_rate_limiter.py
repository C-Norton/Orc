import pytest
import utils.rate_limiter as rl


@pytest.fixture(autouse=True)
def reset_windows():
    """Wipe rate-limiter state before and after every test."""
    rl._windows.clear()
    yield
    rl._windows.clear()


# ---------------------------------------------------------------------------
# Threshold behaviour  (THRESHOLD = 8, so the 9th command triggers the limit)
# ---------------------------------------------------------------------------

def test_under_threshold_returns_false():
    for _ in range(8):
        result = rl.check_rate_limit("user1", "guild1")
    assert result is False


def test_at_threshold_9th_returns_true():
    for _ in range(8):
        rl.check_rate_limit("user1", "guild1")
    assert rl.check_rate_limit("user1", "guild1") is True


def test_continues_true_while_in_window():
    for _ in range(9):
        rl.check_rate_limit("user1", "guild1")
    # Still within the window
    assert rl.check_rate_limit("user1", "guild1") is True


# ---------------------------------------------------------------------------
# Sliding window expiry
# ---------------------------------------------------------------------------

def test_old_entries_expire_and_window_resets(mocker):
    now = 1000.0

    # Fill window at t=0
    mock_mono = mocker.patch("utils.rate_limiter.time.monotonic", return_value=now)
    for _ in range(9):
        rl.check_rate_limit("user1", "guild1")

    # Advance past the 10-second window
    mock_mono.return_value = now + 11
    result = rl.check_rate_limit("user1", "guild1")

    assert result is False  # old entries evicted, window contains only 1 new command


# ---------------------------------------------------------------------------
# Isolation between keys
# ---------------------------------------------------------------------------

def test_different_users_are_independent():
    for _ in range(9):
        rl.check_rate_limit("user_A", "guild1")
    # user_B has made zero commands
    assert rl.check_rate_limit("user_B", "guild1") is False


def test_different_guilds_are_independent():
    for _ in range(9):
        rl.check_rate_limit("user1", "guild_A")
    assert rl.check_rate_limit("user1", "guild_B") is False
