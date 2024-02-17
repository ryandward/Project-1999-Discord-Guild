#!/usr/bin/env python
# -*- coding: utf-8 -*-
# pgloader sqlite://ex_astra.db pgsql://{pguser}:{pgpass}@localhost/guild

# Imports
from collections import defaultdict
from Buttons import DMButton, DeleteButton
from ToonUtils import ToonUtils
from BankUtils import BankUtils
from embed_assisted_questions import ask_async
from discord.ext import commands
from sqlalchemy.orm import scoped_session, sessionmaker

from collections import defaultdict, OrderedDict
import discord
from discord.ext import commands

import discord
from discord.ext import commands
from sqlalchemy import create_engine, func, update
from sqlalchemy.ext.automap import automap_base
from sqlalchemy.orm import sessionmaker


from RichLogger import RichLogger

from config import (
    pguser,
    pgpass,
    pghost,
    pgdata,
    openai_token,
    prefix,
    discord_token,
    devchannel_id,
)

from BotUtils import BotUtils

logger = RichLogger(__name__)

MY_GUILD = discord.Object(id=838976035575562293)

logger.info(f"Starting bot for guild {MY_GUILD.id}")

# Create engine with PostgreSQL database
engine = create_engine(
    f"postgresql://{pguser}:{pgpass}@{pghost}:5432/{pgdata}",
    echo=False,
)

# Create a session
Session = sessionmaker(bind=engine)
ScopedSession = scoped_session(Session)

# Get the Base class
Base = automap_base()
Base.prepare(autoload_with=engine)

# Create a class for each table
tables = defaultdict()
for table_name in Base.classes.keys():
    tables[table_name] = Base.classes[table_name]

# # Now you can access the table classes through the dictionary
# with Session() as session:
#     for row in session.query(tables["census"]).all():
#         print(row.name)


class PersistentViewBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.all()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix=prefix, intents=intents, case_insensitive=True)
        self.devchannel_id = devchannel_id
        # self.tree = app_commands.CommandTree(self)

    async def setup_hook(self) -> None:
        self.add_dynamic_items(DeleteButton)
        self.add_dynamic_items(DMButton)
        await self.add_cog(BotUtils(self))
        await self.add_cog(ToonUtils(self))
        await self.add_cog(BankUtils(self))
        self.tree.copy_global_to(guild=MY_GUILD)

    async def on_ready(self):
        self.devchannel = self.get_channel(self.devchannel_id)
        logger.info(f"Connected {self.user} (ID: {self.user.id})")
        logger.info(f"Communicating status with channel {self.devchannel_id}")
        await self.tree.sync(guild=MY_GUILD)


bot = PersistentViewBot()
bot.run(discord_token)
