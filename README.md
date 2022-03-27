# ex_astra_bot

## Setup
- `cp config.py.template config.py`
- update this new config.py file with your discord bot token
- Create a python venv using `scripts/setup_env`
- Switch to that venv using `source .env/bin/activate`
- Install packages with `pip install -r requirements.txt`

### Running database migrations
Changes to database schema are managed with migrations using the Alembic tool.
To bring your local schema up to date, run `alembic upgrade head`

Moving from an un-managed schema to a schema managed by alembic requires some
additional steps.
1. back up the ex_astra.db file
2. run the `database_etl` script found in the scripts/ directory
- this dumps the database, creates a new db using the first schema migration,
transforms the data, and loads it into the new database.
3. Further schema migrations can be run normally using `alembic upgrade head`

### Setup a discord bot
If you need to add a bot for testing, follow the instructions here:
https://discordpy.readthedocs.io/en/stable/discord.html
