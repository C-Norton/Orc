import random
import re
from typing import List, Tuple
from utils.logging_config import get_logger

logger = get_logger(__name__)

def roll_dice(notation: str) -> Tuple[List[int], int, int]:
    """Parses standard dice notation (e.g., '1d20+5') and returns result and individual rolls."""
    logger.debug(f"Rolling dice with notation: {notation}")
    notation = notation.lower().replace(' ', '')
    match = re.match(r'^(\d+)?d(\d+)([+-]\d+)?$', notation)
    
    if not match:
        logger.debug(f"Invalid dice notation: {notation}")
        raise ValueError("Invalid dice notation. Use format like '1d20' or '2d6+3'.")
    
    count = int(match.group(1)) if match.group(1) else 1
    sides = int(match.group(2))
    modifier = int(match.group(3)) if match.group(3) else 0
    
    if count > 100 or sides > 1000:
        logger.warning(f"Dice roll exceeded limits: {count}d{sides}")
        raise ValueError("Too many dice or too many sides! Keep it reasonable.")

    rolls = [random.randint(1, sides) for _ in range(count)]
    total = sum(rolls) + modifier
    
    logger.debug(f"Result for {notation}: rolls={rolls}, modifier={modifier}, total={total}")
    return rolls, modifier, total

# Test the function
if __name__ == "__main__":
    from utils.logging_config import setup_logging
    setup_logging()
    test_cases = ["1d20", "2d6+3", "d10-1", "3d100"]
    for tc in test_cases:
        try:
            rolls, mod, total = roll_dice(tc)
            logger.info(f"{tc}: Rolls={rolls}, Mod={mod}, Total={total}")
        except Exception as e:
            logger.error(f"{tc}: Error - {e}")
