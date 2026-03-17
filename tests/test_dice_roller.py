import pytest
from dice_roller import (
    roll_dice,
    parse_expression_tokens,
    evaluate_expression,
    ExpressionResult,
    TermResult,
)


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


# ===========================================================================
# parse_expression_tokens
# ===========================================================================

class TestParseExpressionTokens:
    def test_single_dice(self):
        assert parse_expression_tokens("2d6") == [(1, "2d6")]

    def test_implicit_one_die(self):
        assert parse_expression_tokens("d8") == [(1, "d8")]

    def test_dice_plus_flat(self):
        assert parse_expression_tokens("2d6+3") == [(1, "2d6"), (1, "3")]

    def test_dice_minus_flat(self):
        assert parse_expression_tokens("1d20-2") == [(1, "1d20"), (-1, "2")]

    def test_complex_mixed(self):
        tokens = parse_expression_tokens("2d8-Initiative+8+2d6+perception")
        assert tokens == [
            (1, "2d8"),
            (-1, "initiative"),
            (1, "8"),
            (1, "2d6"),
            (1, "perception"),
        ]

    def test_leading_negative(self):
        assert parse_expression_tokens("-2+1d6") == [(-1, "2"), (1, "1d6")]

    def test_case_normalised_to_lower(self):
        assert parse_expression_tokens("1D20+STR") == [(1, "1d20"), (1, "str")]

    def test_multiple_dice_groups(self):
        tokens = parse_expression_tokens("1d4+1d6+1d8+1d10+1d12")
        assert len(tokens) == 5

    def test_pure_number(self):
        assert parse_expression_tokens("5") == [(1, "5")]

    def test_whitespace_stripped(self):
        assert parse_expression_tokens("  2d6 + 3 ") == [(1, "2d6"), (1, "3")]


# ===========================================================================
# evaluate_expression — pure dice / numbers
# ===========================================================================

class TestEvaluateExpressionPure:
    def test_single_die(self, mocker):
        mocker.patch("dice_roller.random.randint", return_value=4)
        result = evaluate_expression([(1, "1d6")])
        assert isinstance(result, ExpressionResult)
        assert result.total == 4

    def test_multiple_same_dice(self, mocker):
        mocker.patch("dice_roller.random.randint", side_effect=[3, 5])
        result = evaluate_expression([(1, "2d6")])
        assert result.total == 8

    def test_dice_plus_flat(self, mocker):
        mocker.patch("dice_roller.random.randint", return_value=4)
        result = evaluate_expression([(1, "1d6"), (1, "3")])
        assert result.total == 7

    def test_dice_minus_flat(self, mocker):
        mocker.patch("dice_roller.random.randint", return_value=10)
        result = evaluate_expression([(1, "1d20"), (-1, "2")])
        assert result.total == 8

    def test_multiple_dice_types(self, mocker):
        mocker.patch("dice_roller.random.randint", side_effect=[2, 4, 6])
        result = evaluate_expression([(1, "1d4"), (1, "1d6"), (1, "1d8")])
        assert result.total == 12

    def test_pure_flat_number(self):
        result = evaluate_expression([(1, "5")])
        assert result.total == 5

    def test_negative_flat(self):
        result = evaluate_expression([(-1, "3")])
        assert result.total == -3

    def test_terms_count(self, mocker):
        mocker.patch("dice_roller.random.randint", return_value=1)
        result = evaluate_expression([(1, "1d6"), (1, "3"), (-1, "1")])
        assert len(result.terms) == 3

    def test_term_is_termresult(self, mocker):
        mocker.patch("dice_roller.random.randint", return_value=5)
        result = evaluate_expression([(1, "1d6")])
        term = result.terms[0]
        assert isinstance(term, TermResult)
        assert term.rolls == [5]
        assert term.value == 5
        assert term.sign == 1

    def test_number_term_has_no_rolls(self):
        result = evaluate_expression([(1, "4")])
        assert result.terms[0].rolls == []

    def test_over_100_dice_raises(self):
        tokens = parse_expression_tokens("101d6")
        with pytest.raises(ValueError, match="Too many"):
            evaluate_expression(tokens)


# ===========================================================================
# evaluate_expression — named modifiers
# ===========================================================================

class TestEvaluateExpressionNamed:
    def test_named_requires_resolver(self):
        with pytest.raises(ValueError, match="requires a character"):
            evaluate_expression([(1, "perception")])

    def test_named_with_resolver(self, mocker):
        mocker.patch("dice_roller.random.randint", side_effect=[3, 5])
        resolver = lambda name: (5, "Perception(+5)")
        result = evaluate_expression([(1, "2d6"), (1, "perception")], named_resolver=resolver)
        assert result.total == 13  # 3+5 + 5

    def test_named_negative_modifier(self, mocker):
        # -Initiative where modifier=-2: contribution = sign(-1) * value(-2) = +2
        mocker.patch("dice_roller.random.randint", side_effect=[5, 5])
        resolver = lambda name: (-2, "Initiative(-2)")
        result = evaluate_expression([(1, "2d8"), (-1, "initiative")], named_resolver=resolver)
        assert result.total == 12  # (5+5) + (-1 * -2)

    def test_named_resolver_receives_correct_name(self):
        calls = []
        def resolver(name):
            calls.append(name)
            return (3, "X(+3)")
        evaluate_expression([(1, "testname")], named_resolver=resolver)
        assert calls == ["testname"]

    def test_complex_full_expression(self, mocker):
        # 2d8 - initiative + 8 + 2d6 + perception
        # 2d8=[3,5]=8, -init=-(-2)=+2, +8, 2d6=[4,2]=6, +perc=+5 → total=29
        mocker.patch("dice_roller.random.randint", side_effect=[3, 5, 4, 2])
        def resolver(name):
            return (-2, "Initiative(-2)") if name == "initiative" else (5, "Perception(+5)")
        tokens = parse_expression_tokens("2d8-initiative+8+2d6+perception")
        result = evaluate_expression(tokens, named_resolver=resolver)
        assert result.total == 29


# ===========================================================================
# evaluate_expression — advantage / disadvantage
# ===========================================================================

class TestEvaluateExpressionAdvantage:
    def test_advantage_on_1d20_takes_higher(self, mocker):
        mocker.patch("dice_roller.random.randint", side_effect=[15, 9])
        result = evaluate_expression([(1, "1d20")], advantage="advantage")
        assert result.total == 15

    def test_disadvantage_on_1d20_takes_lower(self, mocker):
        mocker.patch("dice_roller.random.randint", side_effect=[15, 9])
        result = evaluate_expression([(1, "1d20")], advantage="disadvantage")
        assert result.total == 9

    def test_advantage_second_roll_higher(self, mocker):
        mocker.patch("dice_roller.random.randint", side_effect=[7, 18])
        result = evaluate_expression([(1, "1d20")], advantage="advantage")
        assert result.total == 18

    def test_advantage_not_applied_to_non_d20(self, mocker):
        mocker.patch("dice_roller.random.randint", side_effect=[3, 5])
        result = evaluate_expression([(1, "2d6")], advantage="advantage")
        assert result.total == 8

    def test_advantage_not_applied_to_multi_d20(self, mocker):
        # 2d20 is not a single d20 — advantage doesn't apply
        mocker.patch("dice_roller.random.randint", side_effect=[12, 8])
        result = evaluate_expression([(1, "2d20")], advantage="advantage")
        assert result.total == 20  # both rolled normally

    def test_advantage_d20_with_flat_modifier(self, mocker):
        mocker.patch("dice_roller.random.randint", side_effect=[15, 9])
        result = evaluate_expression([(1, "1d20"), (1, "5")], advantage="advantage")
        assert result.total == 20  # 15 (higher) + 5

    def test_advantage_records_both_rolls(self, mocker):
        mocker.patch("dice_roller.random.randint", side_effect=[15, 9])
        result = evaluate_expression([(1, "1d20")], advantage="advantage")
        assert len(result.terms[0].rolls) == 2
        assert 15 in result.terms[0].rolls
        assert 9 in result.terms[0].rolls


# ===========================================================================
# ExpressionResult.breakdown
# ===========================================================================

class TestBreakdown:
    def test_single_term_contains_dice_label(self, mocker):
        mocker.patch("dice_roller.random.randint", return_value=5)
        result = evaluate_expression([(1, "1d6")])
        assert "1d6" in result.breakdown()

    def test_addition_shown(self, mocker):
        mocker.patch("dice_roller.random.randint", return_value=4)
        result = evaluate_expression([(1, "1d6"), (1, "3")])
        assert "+" in result.breakdown()

    def test_subtraction_shown(self, mocker):
        mocker.patch("dice_roller.random.randint", return_value=10)
        result = evaluate_expression([(1, "1d20"), (-1, "2")])
        bd = result.breakdown()
        assert "−" in bd or "-" in bd

    def test_named_modifier_in_breakdown(self, mocker):
        mocker.patch("dice_roller.random.randint", return_value=3)
        result = evaluate_expression(
            [(1, "1d6"), (1, "perc")],
            named_resolver=lambda n: (5, "Perception(+5)")
        )
        assert "Perception(+5)" in result.breakdown()

    def test_advantage_label_shows_both_rolls_and_symbol(self, mocker):
        mocker.patch("dice_roller.random.randint", side_effect=[15, 9])
        result = evaluate_expression([(1, "1d20")], advantage="advantage")
        bd = result.breakdown()
        assert "15" in bd
        assert "9" in bd
        assert "↑" in bd

    def test_disadvantage_symbol(self, mocker):
        mocker.patch("dice_roller.random.randint", side_effect=[15, 9])
        result = evaluate_expression([(1, "1d20")], advantage="disadvantage")
        assert "↓" in result.breakdown()
