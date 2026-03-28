# ORC — Open-Source Roleplaying Companion

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Python 3.13+](https://img.shields.io/badge/python-3.13%2B-blue)](https://www.python.org/)
[![discord.py 2.x](https://img.shields.io/badge/discord.py-2.x-5865F2)](https://discordpy.readthedocs.io/)

A customizable Discord bot for D&D 5e. ORC helps your table manage characters, make rolls, and automate combat.

Orc is designed with ease of use and flexibility in mind, but with a goal of complete combat automation for theatre of the mind, play by post combat.

---

## Features

- **Character sheets** — Most major sheet logic (Stats, saving throws, skill proficiencies, AC, HP, and non-saving throw attacks), all accessible via a paginated in-Discord character sheet
- **Dice rolling** — Can roll with dice notation or with a skill name and similar
- **Weapon import** — Search the 2024 SRD via Open5e with `/weapon search` and import weapons with `/weapon add`; modifiers auto-computed from character stats
- **Attack rolls** — Saved custom attacks with hit modifiers and damage formulas; auto-rolls to-hit and damage in one command
- **Party system** — GM-managed parties with multiple GMs, character rosters, and active-party selection per user
- **Group rolls** — Roll the same check for the whole party at once, or roll as a specific character
- **Initiative tracker** — Full combat encounter management: add enemies (with bulk add and dice-formula HP), roll initiative, advance turns, and track rounds
- **HP tracking** — Current HP, max HP, and temp HP for player characters, with automatic death save tracking
- **Death saves** — Full death save loop: 3 successes stabilizes, 3 failures slays; nat-20 behaviour (regain 1 HP vs double success) is configurable per party; `/damage` at 0 HP auto-records a failure; `/heal` from 0 HP resets all counters; `death save` autocomplete surfaces only when your character is dying
- **Inspiration tracking** — `/inspiration grant/remove/status`; GMs can award to any party member; Perkins' crit rule automatically grants Inspiration on a nat-20 attack
- **Interactive help** — Paginated `/help` menu.

---

## Inviting ORC

> A public hosted instance is not yet available. To use ORC, self-host it using the instructions below or follow the project on [GitHub](https://github.com/C-Norton/orc) for release announcements.

When self-hosting, generate an invite URL from the [Discord Developer Portal](https://discord.com/developers/applications). The bot requires the following permissions:

- **Bot permissions:** Send Messages, Embed Links, Read Message History, Use Slash Commands
- **Privileged intents:** Message Content Intent (required for rate-limit monitoring)

---

## Quick Start

Once ORC is in your server:

1. **Open the help menu** — `/help` shows a paginated guide to every command category.
2. **Create a character** — `/character create` opens a step-by-step wizard covering name, class & level (with multiclass support), stats, AC, saving throws, skills, HP, and weapons. Every step has Back, Continue (saves entered data and advances), and Skip Step (bypasses the step) buttons; a Finish button commits at any point.
3. **Set your stats** — Stats are collected during the wizard; you can also use `/character stats strength:16 dexterity:14 ...` at any time.
4. **Roll a check** — `/roll check notation:perception` rolls with your proficiency automatically applied.
5. **Form a party** — A GM runs `/party create name:<name>`, then players join with `/party join party_name:<name>`.
6. **Start a fight** — The GM runs `/encounter create`, adds enemies with `/encounter enemy`, then `/encounter start` rolls initiative and posts the turn order.

---

## Command Overview

Use `/help` in Discord for the full interactive reference. Here is a category summary:

| Group        | Commands                                                                                                             | Notes                                                                                                                                                     |
|--------------|----------------------------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------|
| `/character` | `create`, `delete`, `switch`, `view`, `list`, `stats`, `skill`, `ac`, `class`, `saves`                               | `/character create` opens an 8-step wizard (multiclass, HP, weapons). Each step has Continue, Skip Step, Back, and Finish buttons. Can have multiple characters; use `view` for the paginated sheet. |
| `/roll`      | *(no subcommands)*                                                                                                   | Valid entries for the argument are `skill`/`stat`/`save`/`initiative`/`raw dice`/`death save`; must have a valid character to use anything but raw dice   |
| `/weapon`    | `search`                                                                                                             | Searches the SRD and adds weapons directly to your active character with computed hit modifiers. Also available in Step 8 of the character creation wizard. |
| `/attack`    | `add`, `roll`, `list`                                                                                                | A lighter-weight alternative to SRD Weapons, suitable for Spells, and non-SRD content. This is inelegent, and will likely be replaced in the future       |
| `/hp`        | `set_max`, `damage`, `heal`, `temp`, `party_temp`, `status`                                                          | `damage` requires GM when targeting another member; `heal` and `party_temp` are open to all                                                               |
| `/party`     | `create`, `delete`, `join`, `leave`, `active`, `view`, `list`, `character_remove`, `gm_add`, `gm_remove`, `settings` |                                                                                                                                                    |
| `/encounter` | `create`, `enemy`, `start`, `next`, `view`, `end`                                                                    |                                                                                                                                                           |
| `/help`      | *(no subcommands)*                                                                                                   |                                                                                                                                                           |

### Party Settings

GMs can tune per-party behavior with `/party settings`:

| Setting            | Values                                                          | Default       | Effect                                                                                                   |
|--------------------|-----------------------------------------------------------------|---------------|----------------------------------------------------------------------------------------------------------|
| `initiative_mode`  | `by_type`, `individual`, `shared`                               | `by_type`     | Controls how enemy initiative is rolled at `/encounter start`                                            |
| `enemy_ac`         | `True` / `False`                                                | `False`       | Whether enemy AC is visible to players in the initiative order                                           |
| `crit_rule`        | `double_dice`, `perkins`, `double_damage`, `max_damage`, `none` | `double_dice` | How a natural 20 attack roll is resolved                                                                 |
| `death_save_nat20` | `regain_hp`, `double_success`                                   | `regain_hp`   | How a nat-20 on a death save resolves (`regain_hp` = 5e 2024 RAW; `double_success` = common house rules) |

**Initiative modes:**
- `by_type` — Enemies that share the same base type (e.g. all "Goblin" in "Goblin 1"–"Goblin 4") roll once and act on the same initiative count.
- `individual` — Every enemy rolls separately.
- `shared` — All enemies share a single initiative roll.

**Crit rules:**
- `double_dice` — Roll twice the normal number of damage dice, then add the modifier once (default; closest to 5e 2024 RAW).
- `perkins` — Normal damage; the attacker gains Inspiration (Matt Perkins' house rule).
- `double_damage` — Roll damage normally, then double the total.
- `max_damage` — All damage dice show their maximum face value, then add the modifier.
- `none` — No special handling; treat a nat-20 as a normal hit.

---
## Feature Roadmap
- [ ] WorldAnvil integration
- [ ] Spell searching
- [ ] Saving throw based attacks
- [ ] Weapon proficiency and Expertise
- [ ] Armor tracking
- [ ] GM Rolls via DM
- [x] Weapon search and import via SRD (available in `/weapon search` and the character creation wizard)
- [ ] Full srd lookup for weapons (non-SRD / homebrew weapons)
- [ ] Full srd lookup for spells
- [ ] Full srd lookup for classes
- [ ] Full srd lookup for skills
- [ ] Full srd lookup for conditions
- [ ] Full srd lookup for languages
- [ ] Full srd lookup for races
- [ ] Full srd lookup for backgrounds
- [ ] Full srd lookup for equipment
---
## Known Bugs
None presently.

---
## Self-Hosting

### Requirements

- Python 3.13+
- A Discord bot token ([Discord Developer Portal](https://discord.com/developers/applications))
- SQLite or PostgreSQL supported. Postgres recommended for production— see [Database](#database)). Seeing as ORC is SQLAlchemy-based, any SQLAlchemy-supported database should work, but SQLite and PostgreSQL are the target DBs for this project.

### Setup

```bash
# Clone the repository
git clone https://github.com/C-Norton/orc.git
cd orc

# Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate      # Linux / macOS
.venv\Scripts\activate         # Windows

# Install dependencies
pip install -r requirements.txt
```

Create a `.env` file in the project root:

```
DISCORD_API_TOKEN
DISCORD_APPLICATION_ID
DISCORD_PUBLIC_KEY
LOG_LEVEL= (debug | info)
```

Apply database migrations and start the bot:

```bash
alembic upgrade head
python main.py
```

Slash commands are synced globally on startup. Discord can take **up to one hour** to propagate new commands to all servers. CTRL-R will reload commands on a client

### Database

The default configuration uses **SQLite** (`dnd_bot.db` in the project root), which requires no additional setup and is suitable for development and small deployments.

For production, swap in a **PostgreSQL** connection string in `database.py`:

```python
DB_PATH = "postgresql+psycopg2://user:password@host/dbname"
```

The project is designed for deployment on Google Cloud SQL (PostgreSQL) but works with any SQLAlchemy-compatible PostgreSQL instance. After changing the connection string, run `alembic upgrade head` against the new database.

### Managing Migrations

```bash
# Apply all pending migrations
alembic upgrade head

# Generate a migration after changing a model
alembic revision --autogenerate -m "describe your change"

# Roll back one migration
alembic downgrade -1
```

---

## Architecture

```
Discord slash command
    → commands/<feature>_commands.py   (validates input, calls DB)
    → SessionLocal()                    (SQLAlchemy session, always closed in finally)
    → models/                          (SQLAlchemy ORM models)
    → db.commit()
    → interaction.response.send_message()
```

### Key files

| File | Purpose |
|---|---|
| `main.py` | Bot entry point; registers all command groups, syncs slash commands |
| `database.py` | SQLAlchemy engine and `SessionLocal` factory |
| `dice_roller.py` | Dice notation parser (`NdX+M`); supports complex multi-term expressions |
| `commands/` | One file per feature group; each exports a `register_*_commands(bot)` function |
| `models/` | SQLAlchemy models; all exported from `models/__init__.py` |
| `enums/` | Project enums (skill proficiency status, encounter status, initiative mode, etc.) |
| `utils/` | Shared logic — D&D calculations, strings, logging config, rate limiter, limits |
| `alembic/versions/` | Database migration history |

### Data model summary

- **User** ↔ **Server** (many-to-many via `user_server_association`; also stores `active_party_id`)
- **Character** → User + Server; `is_active` flag per user per server
- **Party** → Server; has GMs (many-to-many) and Characters (many-to-many)
- **PartySettings** → Party (1:1, lazy-created with defaults)
- **Encounter** → Party; has Enemies and EncounterTurns
- **Enemy** → Encounter; has `type_name` (initiative grouping key), `ac`, `max_hp`, `current_hp`
- **EncounterTurn** → Encounter + (Character | Enemy); ordered by `order_position`

---

## Development

### Running tests

```bash
python -m pytest tests/
```

The test suite uses an in-memory SQLite database (via SQLAlchemy `StaticPool`) and `pytest-asyncio` for async command handlers. No running bot or database is required.

### Manual Testing

In addition to the test suite, it is required that the bot be tested manually in a Discord server when developing new features, both with "happy path" testing and edge cases. Behavior checklists are available upon request for those looking to test the bot. To keep the repository clean, These have not been included here.

### Code style

The project follows PEP 8 and uses [Ruff](https://docs.astral.sh/ruff/) for formatting:

```bash
ruff check .
ruff format .
```

All user-facing strings live in `utils/strings.py`. Create enums for any new named concept. Prefer verbose variable names over abbreviations.

### Test-driven development

All new features are developed test-first. When fixing a bug, include a regression test that fails before the fix and passes after.

---

## Contributing

Issues and pull requests are welcome at **https://github.com/C-Norton/orc**.

- **Bug reports** — Open an issue with steps to reproduce and the relevant log output (check `bot.log` or `bot_debug.log`).
- **Feature requests** — Open an issue describing the feature and the D&D rule it relates to, if applicable.
- **Pull requests** — Fork the repo, create a feature branch, write tests first, then implement. PRs without tests for new behavior will be asked to add them before merge.

Please follow the existing code style and ensure the full test suite passes (`python -m pytest tests/`) before submitting.

---

## License

ORC is free software, released under the **GNU General Public License v3.0**.
See the [LICENSE](LICENSE) file for the full text.

**In short:**
You are free to run, study, modify, and distribute this software under the terms of the GNU-GPL v3. Any modified version you distribute must also be made available as open source software under the GNU-GPLv3. Refer to the license file for more details. This license section of the readme does not overrule the license file.


## Support
If you like ORC, please consider starring the repository on GitHub to show your support and help others discover it. Your contributions and feedback are valuable in making ORC better for everyone. Once a stable release is available,I may put up a Kofi link here. That said, the best way to support Orc is to assist with his development if you have the know how.

I am currently collecting funny strings for the bot to say when you get a nat 20 or nat 1 on a die roll. If you have a string you would like to see added, please open an issue or submit a pull request with the string added in strings.py. Your contributions are greatly appreciated and will help make Orc even more fun and engaging for everyone.

## Credits

Channing Norton is the primary author of ORC. Thank you also to my parties for their support, feedback, and patience when developing the bot.

## Libraries and tooling used
- [Open5e](https://open5e.com/) for the SRD
- [Discord.py](https://discordpy.readthedocs.io/) for the Discord API wrapper



- [SQLAlchemy](https://www.sqlalchemy.org/) for database ORM
- [Alembic](https://alembic.sqlalchemy.org/) for database migrations


- [Ruff](https://docs.astral.sh/ruff/) for code formatting
- [pytest](https://docs.pytest.org/en/7.4.x/) for testing
- [pytest-cov](https://github.com/pytest-dev/pytest-cov) for test coverage
- [pytest-mock](https://github.com/pytest-dev/pytest-mock) for mocking
- [pytest-asyncio](https://github.com/pytest-dev/pytest-asyncio) for async testing