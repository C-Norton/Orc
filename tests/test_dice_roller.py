import pytest
from dice_roller import roll_dice


# ---------------------------------------------------------------------------
# Valid notation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("notation,expected_count,sides", [
    ("1d20", 1, 20),
    ("2d6",  2, 6),
    ("d10",  1, 10),   # no count prefix → defaults to 1
    ("3d8",  3, 8),
    ("1d1",  1, 1),
])
def test_valid_notation_returns_correct_structure(notation, expected_count, sides):
    rolls, modifier, total = roll_dice(notation)
    assert len(rolls) == expected_count
    assert all(1 <= r <= sides for r in rolls)
    assert modifier == 0
    assert total == sum(rolls)


def test_positive_modifier():
    rolls, modifier, total = roll_dice("2d6+3")
    assert modifier == 3
    assert total == sum(rolls) + 3


def test_negative_modifier():
    rolls, modifier, total = roll_dice("1d8-2")
    assert modifier == -2
    assert total == sum(rolls) - 2


def test_d20_and_1d20_are_equivalent():
    # Both should produce a single roll between 1 and 20
    for _ in range(10):
        rolls_short, _, _ = roll_dice("d20")
        rolls_long, _, _ = roll_dice("1d20")
        assert len(rolls_short) == 1
        assert len(rolls_long) == 1


def test_multiple_dice_total_is_sum_plus_modifier():
    for _ in range(20):
        rolls, mod, total = roll_dice("4d6+2")
        assert total == sum(rolls) + 2


def test_roll_is_within_bounds():
    for _ in range(50):
        rolls, _, _ = roll_dice("1d100")
        assert 1 <= rolls[0] <= 100


# ---------------------------------------------------------------------------
# Boundary: limits
# ---------------------------------------------------------------------------

def test_exactly_100_dice_is_allowed():
    rolls, _, _ = roll_dice("100d6")
    assert len(rolls) == 100


def test_exactly_1000_sides_is_allowed():
    rolls, _, _ = roll_dice("1d1000")
    assert len(rolls) == 1


def test_101_dice_raises():
    with pytest.raises(ValueError, match="Too many"):
        roll_dice("101d6")


def test_1001_sides_raises():
    with pytest.raises(ValueError, match="Too many"):
        roll_dice("1d1001")


# ---------------------------------------------------------------------------
# Invalid notation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad", [
    "abc",
    "1d",
    "d",
    "20",
    "1d6d6",
    "",
])
def test_invalid_notation_raises_value_error(bad):
    with pytest.raises(ValueError, match="Invalid dice notation"):
        roll_dice(bad)
