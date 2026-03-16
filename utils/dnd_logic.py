from typing import TYPE_CHECKING, Optional, Any
import random
from dice_roller import roll_dice
from enums.skill_proficiency_status import SkillProficiencyStatus
from utils.constants import SKILL_TO_STAT, STAT_NAMES
from utils.logging_config import get_logger

logger = get_logger(__name__)

if TYPE_CHECKING:
    from models import Character
    from sqlalchemy.orm import Session

def get_proficiency_bonus(level: int) -> int:
    return (level - 1) // 4 + 2

def get_stat_modifier(score: Optional[int]) -> int:
    if score is None:
        return 0
    return (score - 10) // 2

async def perform_roll(char: "Character", notation: str, db: "Session") -> str:
    """Shared roll logic extracted from /roll."""
    logger.debug(f"Performing roll for {char.name} (ID: {char.id}) with notation: {notation}")
    clean_notation = notation.lower().strip()
    is_save = False
    save_stat = None
    if "save" in clean_notation:
        stat_part = clean_notation.replace("save", "").replace("_", "").strip()
        if stat_part in STAT_NAMES:
            is_save = True
            save_stat = STAT_NAMES[stat_part]

    matched_skill = next((s for s in SKILL_TO_STAT.keys() if s.lower() == clean_notation), None)
    matched_stat = STAT_NAMES.get(clean_notation) if not is_save and not matched_skill else None
    is_initiative = clean_notation in ["initiative", "init"]

    if matched_skill or is_save or matched_stat or is_initiative:
        prof_bonus = get_proficiency_bonus(char.level)
        d20_roll = random.randint(1, 20)

        if matched_skill:
            skill = matched_skill
            stat_name = SKILL_TO_STAT[skill]
            stat_score = getattr(char, stat_name)
            stat_mod = get_stat_modifier(stat_score)

            from models import CharacterSkill
            char_skill = db.query(CharacterSkill).filter_by(character_id=char.id, skill_name=skill).first()
            prof_status = char_skill.proficiency if char_skill else SkillProficiencyStatus.NOT_PROFICIENT

            skill_mod = stat_mod
            if prof_status == SkillProficiencyStatus.PROFICIENT:
                skill_mod += prof_bonus
            elif prof_status == SkillProficiencyStatus.EXPERTISE:
                skill_mod += 2 * prof_bonus
            elif prof_status == SkillProficiencyStatus.JACK_OF_ALL_TRADES:
                skill_mod += prof_bonus // 2

            total = d20_roll + skill_mod
            return f"**{char.name}**: {skill} ({stat_name.title()}) `d20({d20_roll}) + {skill_mod}` = **{total}**"

        elif is_save:
            stat_name = save_stat
            stat_score = getattr(char, stat_name)
            stat_mod = get_stat_modifier(stat_score)
            is_proficient = getattr(char, f"st_prof_{stat_name}")
            save_mod = stat_mod + (prof_bonus if is_proficient else 0)
            total = d20_roll + save_mod
            return f"**{char.name}**: {stat_name.title()} Save `d20({d20_roll}) + {save_mod}` = **{total}**"

        elif is_initiative:
            dex_mod = get_stat_modifier(char.dexterity)
            init_bonus = char.initiative_bonus if char.initiative_bonus is not None else dex_mod
            total = d20_roll + init_bonus
            return f"**{char.name}**: Initiative `d20({d20_roll}) + {init_bonus}` = **{total}**"

        else: # matched_stat
            stat_name = matched_stat
            stat_score = getattr(char, stat_name)
            stat_mod = get_stat_modifier(stat_score)
            total = d20_roll + stat_mod
            return f"**{char.name}**: {stat_name.title()} Check `d20({d20_roll}) + {stat_mod}` = **{total}**"
    else:
        try:
            rolls, modifier, total = roll_dice(notation)
            rolls_str = ", ".join(map(str, rolls))
            mod_str = f" {modifier:+d}" if modifier != 0 else ""
            return f"**{char.name}**: `{notation}` ({rolls_str}){mod_str} = **{total}**"
        except ValueError as e:
            logger.debug(f"ValueError in perform_roll for {notation}: {e}")
            return f"**{char.name}**: ❌ Error: {str(e)}"
