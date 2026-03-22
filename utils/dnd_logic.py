from typing import TYPE_CHECKING, Optional
import random
from dice_roller import parse_expression_tokens, evaluate_expression, has_named_tokens
from enums.skill_proficiency_status import SkillProficiencyStatus
from utils.constants import SKILL_TO_STAT, STAT_NAMES
from utils.logging_config import get_logger
from utils.strings import Strings

logger = get_logger(__name__)

if TYPE_CHECKING:
    from models import Character
    from sqlalchemy.orm import Session


def roll_initiative_for_character(char: "Character") -> tuple[int, int]:
    """Roll initiative for a character. Returns (total, bonus_used).
    Uses initiative_bonus override if set, otherwise dexterity modifier."""
    dex_mod = get_stat_modifier(char.dexterity)
    bonus = char.initiative_bonus if char.initiative_bonus is not None else dex_mod
    total = random.randint(1, 20) + bonus
    return total, bonus


def get_proficiency_bonus(level: int) -> int:
    return (level - 1) // 4 + 2


def get_stat_modifier(score: Optional[int]) -> int:
    if score is None:
        return 0
    return (score - 10) // 2


def resolve_named_modifier(
    name: str, char: "Character", db: "Session"
) -> tuple[int, str]:
    """
    Resolve a named modifier token against a character.
    Returns (int_value, display_label).
    Raises ValueError for unknown names.
    """
    clean = name.lower().strip()
    prof_bonus = get_proficiency_bonus(char.level)

    # Skill modifier
    skill_name = next((s for s in SKILL_TO_STAT.keys() if s.lower() == clean), None)
    if skill_name:
        stat_name = SKILL_TO_STAT[skill_name]
        stat_mod = get_stat_modifier(getattr(char, stat_name))
        from models import CharacterSkill

        char_skill = (
            db.query(CharacterSkill)
            .filter_by(character_id=char.id, skill_name=skill_name)
            .first()
        )
        prof_status = (
            char_skill.proficiency
            if char_skill
            else SkillProficiencyStatus.NOT_PROFICIENT
        )
        mod = stat_mod
        if prof_status == SkillProficiencyStatus.PROFICIENT:
            mod += prof_bonus
        elif prof_status == SkillProficiencyStatus.EXPERTISE:
            mod += 2 * prof_bonus
        elif prof_status == SkillProficiencyStatus.JACK_OF_ALL_TRADES:
            mod += prof_bonus // 2
        return mod, f"{skill_name}({mod:+d})"

    # Initiative
    if clean in ("initiative", "init"):
        dex_mod = get_stat_modifier(char.dexterity)
        init_bonus = (
            char.initiative_bonus if char.initiative_bonus is not None else dex_mod
        )
        return init_bonus, f"Initiative({init_bonus:+d})"

    # Stat modifier (full name or abbreviation)
    stat_name = STAT_NAMES.get(clean)
    if stat_name:
        mod = get_stat_modifier(getattr(char, stat_name))
        return mod, f"{stat_name.title()}({mod:+d})"

    raise ValueError(
        f"Unknown named modifier: '{name}'. Use a skill, stat, or 'initiative'."
    )


def _roll_d20_with_advantage(advantage: Optional[str]) -> tuple[int, Optional[int]]:
    """
    Roll a d20, optionally with advantage or disadvantage.
    Returns (kept_roll, discarded_roll_or_None).
    """
    if advantage in ("advantage", "disadvantage"):
        r1 = random.randint(1, 20)
        r2 = random.randint(1, 20)
        if advantage == "advantage":
            kept, discarded = max(r1, r2), min(r1, r2)
        else:
            kept, discarded = min(r1, r2), max(r1, r2)
        return kept, discarded
    return random.randint(1, 20), None


def _format_d20_roll(
    kept: int, discarded: Optional[int], advantage: Optional[str]
) -> str:
    if discarded is None:
        return f"d20({kept})"
    sym = "↑" if advantage == "advantage" else "↓"
    return f"d20[{kept}{sym},{discarded}]"


async def perform_roll(
    char: "Character",
    notation: str,
    db: "Session",
    advantage: Optional[str] = None,
) -> str:
    """
    Shared roll logic for /roll, /partyroll, /rollas.

    Handles (in order):
    1. Simple named checks: skill, saving throw, stat check, initiative — d20 + modifier,
       with optional advantage/disadvantage.
    2. Complex expressions containing named modifiers (e.g. '2d8+perception').
    3. Pure dice/number expressions (e.g. '2d6+3').
    """
    logger.debug(
        f"perform_roll: char={char.name} notation={notation!r} advantage={advantage}"
    )
    clean = notation.lower().strip()

    # ------------------------------------------------------------------
    # 1. Simple named checks (existing behaviour, extended with advantage)
    # ------------------------------------------------------------------
    is_save = False
    save_stat = None
    if "save" in clean:
        stat_part = clean.replace("save", "").replace("_", "").strip()
        if stat_part in STAT_NAMES:
            is_save = True
            save_stat = STAT_NAMES[stat_part]

    matched_skill = next((s for s in SKILL_TO_STAT.keys() if s.lower() == clean), None)
    matched_stat = STAT_NAMES.get(clean) if not is_save and not matched_skill else None
    is_initiative = clean in ("initiative", "init")

    if matched_skill or is_save or matched_stat or is_initiative:
        prof_bonus = get_proficiency_bonus(char.level)
        d20_roll, discarded = _roll_d20_with_advantage(advantage)
        d20_str = _format_d20_roll(d20_roll, discarded, advantage)

        if matched_skill:
            skill = matched_skill
            stat_name = SKILL_TO_STAT[skill]
            stat_score = getattr(char, stat_name)
            stat_mod = get_stat_modifier(stat_score)
            from models import CharacterSkill

            char_skill = (
                db.query(CharacterSkill)
                .filter_by(character_id=char.id, skill_name=skill)
                .first()
            )
            prof_status = (
                char_skill.proficiency
                if char_skill
                else SkillProficiencyStatus.NOT_PROFICIENT
            )
            skill_mod = stat_mod
            if prof_status == SkillProficiencyStatus.PROFICIENT:
                skill_mod += prof_bonus
            elif prof_status == SkillProficiencyStatus.EXPERTISE:
                skill_mod += 2 * prof_bonus
            elif prof_status == SkillProficiencyStatus.JACK_OF_ALL_TRADES:
                skill_mod += prof_bonus // 2
            total = d20_roll + skill_mod
            label = f"{skill} ({stat_name.title()})"
            return Strings.ROLL_RESULT_CHAR.format(
                char_name=char.name,
                label=label,
                d20_roll=d20_str,
                modifier=skill_mod,
                total=total,
                tip=random.choice(Strings.TIPS),
            )

        elif is_save:
            stat_name = save_stat
            stat_score = getattr(char, stat_name)
            stat_mod = get_stat_modifier(stat_score)
            is_proficient = getattr(char, f"st_prof_{stat_name}")
            save_mod = stat_mod + (prof_bonus if is_proficient else 0)
            total = d20_roll + save_mod
            return Strings.ROLL_RESULT_CHAR.format(
                char_name=char.name,
                label=f"{stat_name.title()} Save",
                d20_roll=d20_str,
                modifier=save_mod,
                total=total,
                tip=random.choice(Strings.TIPS),
            )

        elif is_initiative:
            dex_mod = get_stat_modifier(char.dexterity)
            init_bonus = (
                char.initiative_bonus if char.initiative_bonus is not None else dex_mod
            )
            total = d20_roll + init_bonus
            return Strings.ROLL_RESULT_CHAR.format(
                char_name=char.name,
                label="Initiative",
                d20_roll=d20_str,
                modifier=init_bonus,
                total=total,
                tip=random.choice(Strings.TIPS),
            )

        else:  # matched_stat
            stat_name = matched_stat
            stat_score = getattr(char, stat_name)
            stat_mod = get_stat_modifier(stat_score)
            total = d20_roll + stat_mod
            return Strings.ROLL_RESULT_CHAR.format(
                char_name=char.name,
                label=f"{stat_name.title()} Check",
                d20_roll=d20_str,
                modifier=stat_mod,
                total=total,
                tip=random.choice(Strings.TIPS),
            )

    # ------------------------------------------------------------------
    # 2 & 3. Complex / pure-dice expressions
    # ------------------------------------------------------------------
    try:
        tokens = parse_expression_tokens(notation)
        resolver = None
        if has_named_tokens(tokens):
            resolver = lambda name: resolve_named_modifier(name, char, db)
        result = evaluate_expression(
            tokens, named_resolver=resolver, advantage=advantage
        )
        return Strings.ROLL_RESULT_CHAR_EXPR.format(
            char_name=char.name,
            notation=notation,
            breakdown=result.breakdown(),
            total=result.total,
            tip=random.choice(Strings.TIPS),
        )
    except ValueError as e:
        logger.debug(f"ValueError in perform_roll for {notation!r}: {e}")
        return Strings.ROLL_ERROR_CHAR.format(char_name=char.name, error=str(e))
