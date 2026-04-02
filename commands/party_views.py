import math
import discord
from typing import List
from database import db_session
from enums.encounter_status import EncounterStatus
from models import Character, Encounter, EncounterTurn, Party, User
from utils.logging_config import get_logger
from utils.strings import Strings

logger = get_logger(__name__)


class ConfirmCharacterRemoveView(discord.ui.View):
    """Ephemeral confirmation shown when removing a character who is in an active encounter.

    ✅ Remove — deletes their EncounterTurn and removes them from the party.
    ❌ Cancel  — aborts with no changes.
    """

    def __init__(
        self, party_id: int, char_id: int, party_name: str, char_name: str
    ) -> None:
        super().__init__(timeout=30)
        self.party_id = party_id
        self.char_id = char_id
        self.party_name = party_name
        self.char_name = char_name

    @discord.ui.button(
        label=Strings.BUTTON_REMOVE, emoji="✅", style=discord.ButtonStyle.danger
    )
    async def confirm(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Cascade-delete the character's EncounterTurn, then remove from party."""
        with db_session() as db:
            party = db.get(Party, self.party_id)
            char = db.get(Character, self.char_id)

            if not party or not char:
                await interaction.response.edit_message(
                    content=Strings.ERROR_CHAR_OR_PARTY_NO_LONGER_EXISTS, view=None
                )
                return

            active_turn = (
                db.query(EncounterTurn)
                .filter_by(character_id=char.id)
                .join(EncounterTurn.encounter)
                .filter(Encounter.status == EncounterStatus.ACTIVE)
                .first()
            )

            if active_turn:
                encounter = active_turn.encounter
                sorted_turns = sorted(
                    encounter.turns, key=lambda turn: turn.order_position
                )
                deleted_index = sorted_turns.index(active_turn)
                turn_count_after = len(sorted_turns) - 1

                db.delete(active_turn)
                db.flush()

                # Keep current_turn_index valid after the slot is gone
                if turn_count_after == 0:
                    # Last combatant removed — reset to the start
                    encounter.current_turn_index = 0
                elif deleted_index < encounter.current_turn_index:
                    # A slot before the active turn was removed — shift the index back one
                    encounter.current_turn_index -= 1
                elif deleted_index == encounter.current_turn_index:
                    # The active combatant was removed — if there's a next slot keep it,
                    # otherwise wrap to the start of a new round
                    if encounter.current_turn_index >= turn_count_after:
                        encounter.current_turn_index = 0
                        encounter.round_number += 1

            if char in party.characters:
                party.characters.remove(char)

            db.commit()
            logger.info(
                f"Confirmed removal of '{self.char_name}' from '{self.party_name}' "
                "including EncounterTurn cascade"
            )
            await interaction.response.edit_message(
                content=Strings.PARTY_REMOVE_ENCOUNTER_CONFIRMED.format(
                    char_name=self.char_name, party_name=self.party_name
                ),
                view=None,
            )
        self.stop()

    @discord.ui.button(
        label=Strings.BUTTON_CANCEL, emoji="❌", style=discord.ButtonStyle.secondary
    )
    async def cancel(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Abort — no changes made."""
        await interaction.response.edit_message(
            content=Strings.PARTY_REMOVE_CANCELLED, view=None
        )
        self.stop()


class ConfirmPartyDeleteView(discord.ui.View):
    """Ephemeral confirmation before permanently deleting a party.

    If the party has open encounters the initial message lists them; the
    confirm handler auto-completes them before deleting.

    ✅ Delete — auto-completes open encounters, then cascade-deletes the party.
    ❌ Cancel  — aborts with no changes.
    """

    def __init__(self, party_id: int, party_name: str) -> None:
        super().__init__(timeout=30)
        self.party_id = party_id
        self.party_name = party_name

    @discord.ui.button(
        label=Strings.BUTTON_DELETE, emoji="✅", style=discord.ButtonStyle.danger
    )
    async def confirm(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Auto-complete open encounters, then delete the party."""
        with db_session() as db:
            party = db.get(Party, self.party_id)
            if not party:
                await interaction.response.edit_message(
                    content=Strings.ERROR_PARTY_NO_LONGER_EXISTS, view=None
                )
                return

            # Auto-complete any open encounters before the party is deleted
            completed_names: list[str] = []
            for encounter in party.encounters:
                if encounter.status in (
                    EncounterStatus.PENDING,
                    EncounterStatus.ACTIVE,
                ):
                    encounter.status = EncounterStatus.COMPLETE
                    completed_names.append(encounter.name)
            if completed_names:
                # Flush the status updates before the delete so FK constraints are satisfied
                db.flush()

            db.delete(party)
            db.commit()
            logger.info(
                f"Confirmed deletion of party '{self.party_name}' (id={self.party_id})"
            )
            message = Strings.PARTY_DELETE_SUCCESS.format(party_name=self.party_name)
            if completed_names:
                for enc_name in completed_names:
                    message += "\n" + Strings.PARTY_DELETE_ENCOUNTER_COMPLETED.format(
                        encounter_name=enc_name
                    )
            await interaction.response.edit_message(content=message, view=None)
        self.stop()

    @discord.ui.button(
        label=Strings.BUTTON_CANCEL, emoji="❌", style=discord.ButtonStyle.secondary
    )
    async def cancel(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Abort — no changes made."""
        await interaction.response.edit_message(
            content=Strings.PARTY_DELETE_CANCELLED, view=None
        )
        self.stop()


class ConfirmSelfGMRemoveView(discord.ui.View):
    """Ephemeral confirmation shown when a GM tries to remove themselves.

    ✅ Remove  — removes the user from the party's GM list.
    ❌ Cancel  — aborts with no changes.
    """

    def __init__(self, party_id: int, party_name: str, user_discord_id: str) -> None:
        super().__init__(timeout=30)
        self.party_id = party_id
        self.party_name = party_name
        self.user_discord_id = user_discord_id

    @discord.ui.button(
        label=Strings.BUTTON_REMOVE_MYSELF, emoji="✅", style=discord.ButtonStyle.danger
    )
    async def confirm(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Remove the user from the party's GM list."""
        with db_session() as db:
            party = db.get(Party, self.party_id)
            user = db.query(User).filter_by(discord_id=self.user_discord_id).first()

            if not party or not user:
                await interaction.response.edit_message(
                    content=Strings.ERROR_PARTY_OR_USER_NO_LONGER_EXISTS, view=None
                )
                return

            if user not in party.gms:
                await interaction.response.edit_message(
                    content=Strings.ERROR_NO_LONGER_GM, view=None
                )
                return

            party.gms.remove(user)
            db.commit()
            logger.info(
                f"Confirmed self-GM-removal: user {self.user_discord_id} "
                f"left GMs of '{self.party_name}'"
            )
            await interaction.response.edit_message(
                content=Strings.GM_REMOVED.format(
                    discord_id=self.user_discord_id, party_name=self.party_name
                ),
                view=None,
            )
        self.stop()

    @discord.ui.button(
        label=Strings.BUTTON_CANCEL, emoji="❌", style=discord.ButtonStyle.secondary
    )
    async def cancel(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Abort — no changes made."""
        await interaction.response.edit_message(
            content=Strings.PARTY_GM_REMOVE_SELF_CANCELLED, view=None
        )
        self.stop()


class PartyListView(discord.ui.View):
    """Paginated embed view for /party list.

    Displays all parties on the server with their member counts, split into
    pages of :attr:`PARTIES_PER_PAGE` entries each.  Previous/Next buttons
    navigate between pages; both are disabled when only one page exists.
    """

    PARTIES_PER_PAGE: int = 10

    def __init__(self, parties: List[tuple], server_name: str) -> None:
        """Initialise the view with pre-loaded party data.

        Args:
            parties: Ordered list of ``(party_name, member_count)`` tuples.
            server_name: Display name of the Discord server (used in embed title).
        """
        super().__init__(timeout=120)
        self.parties = parties
        self.server_name = server_name
        self.current_page: int = 0
        self.total_pages: int = max(1, math.ceil(len(parties) / self.PARTIES_PER_PAGE))
        self._update_buttons()

    def _update_buttons(self) -> None:
        """Enable or disable navigation buttons based on the current page."""
        self.prev_button.disabled = self.current_page == 0
        self.next_button.disabled = self.current_page >= self.total_pages - 1

    def build_embed(self) -> discord.Embed:
        """Build and return the Discord Embed for the current page."""
        start = self.current_page * self.PARTIES_PER_PAGE
        page_parties = self.parties[start : start + self.PARTIES_PER_PAGE]

        embed = discord.Embed(
            title=Strings.PARTY_LIST_EMBED_TITLE.format(server_name=self.server_name),
            color=discord.Color.blue(),
        )
        for name, count in page_parties:
            plural = "s" if count != 1 else ""
            embed.add_field(
                name=name,
                value=Strings.PARTY_LIST_MEMBER_COUNT.format(
                    count=count, plural=plural
                ),
                inline=False,
            )
        embed.set_footer(
            text=Strings.PARTY_LIST_EMBED_FOOTER.format(
                page=self.current_page + 1,
                total_pages=self.total_pages,
                total_parties=len(self.parties),
            )
        )
        return embed

    @discord.ui.button(label=Strings.BUTTON_PREV, style=discord.ButtonStyle.secondary)
    async def prev_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Navigate to the previous page."""
        self.current_page -= 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label=Strings.BUTTON_NEXT, style=discord.ButtonStyle.secondary)
    async def next_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Navigate to the next page."""
        self.current_page += 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)
