import random
import re
from typing import List, Tuple

def roll_dice(notation: str) -> Tuple[List[int], int, int]:
    """Parses standard dice notation (e.g., '1d20+5') and returns result and individual rolls."""
    notation = notation.lower().replace(' ', '')
    match = re.match(r'^(\d+)?d(\d+)([+-]\d+)?$', notation)
    
    if not match:
        raise ValueError("Invalid dice notation. Use format like '1d20' or '2d6+3'.")
    
    count = int(match.group(1)) if match.group(1) else 1
    sides = int(match.group(2))
    modifier = int(match.group(3)) if match.group(3) else 0
    
    if count > 100 or sides > 1000:
        raise ValueError("Too many dice or too many sides! Keep it reasonable.")

    rolls = [random.randint(1, sides) for _ in range(count)]
    total = sum(rolls) + modifier
    
    return rolls, modifier, total

# Test the function
if __name__ == "__main__":
    test_cases = ["1d20", "2d6+3", "d10-1", "3d100"]
    for tc in test_cases:
        try:
            rolls, mod, total = roll_dice(tc)
            print(f"{tc}: Rolls={rolls}, Mod={mod}, Total={total}")
        except Exception as e:
            print(f"{tc}: Error - {e}")
