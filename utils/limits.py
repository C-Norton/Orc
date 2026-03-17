"""Hard caps on resource creation to prevent abuse and resource exhaustion.

All values are intentionally generous for legitimate play. Adjust here if
stricter or looser bounds are needed — commands import from this module so
changes take effect everywhere automatically.
"""

MAX_CHARACTERS_PER_USER: int = 50
"""Maximum total characters a single Discord user may own across all servers."""

MAX_GM_PARTIES_PER_USER: int = 20
"""Maximum number of parties a single user may simultaneously be a GM of."""

MAX_CHARACTERS_PER_PARTY: int = 25
"""Maximum number of characters that can belong to a single party."""

MAX_ATTACKS_PER_CHARACTER: int = 25
"""Maximum number of saved attacks a single character may have."""

MAX_ENEMIES_PER_ENCOUNTER: int = 100
"""Maximum number of enemies that can be added to a single encounter."""

MAX_PARTIES_PER_SERVER: int = 60
"""Maximum number of parties that may exist in a single server."""
