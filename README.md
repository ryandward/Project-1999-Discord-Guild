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
2. dump the data from the db
- `sqlite3 ex_astra.db .dump > dump.sql`
- delete all the `CREATE TABLE` statements from the dump.sql file
3. remove ex_astra.db
4. run the alembic migration - this will create a new ex_astra.db file with the appropriate schema
5. load the backed up data into the db
- `sqlite3 ex_astra.db < dump.sql`

### Setup a discord bot
If you need to add a bot for testing, follow the instructions here:
https://discordpy.readthedocs.io/en/stable/discord.html
