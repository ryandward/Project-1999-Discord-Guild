#!/usr/bin/env python
# -*- coding: utf-8 -*-
# pgloader sqlite://ex_astra.db pgsql://{pguser}:{pgpass}@localhost/guild

# Imports
from collections import defaultdict
import io
import json
import os
import sqlite3
import subprocess
import tempfile
from difflib import get_close_matches as gcm
from pathlib import Path
from urllib.request import Request, urlopen
from Buttons import DMButton, DeleteButton
from ToonUtils import ToonUtils
from embed_assisted_questions import ask_async
from discord.ext import commands
from discord import Embed
from discord import app_commands
from sqlalchemy.orm import scoped_session


from sqlalchemy.orm import scoped_session
from sqlalchemy.orm import sessionmaker
from collections import defaultdict, OrderedDict
import discord
from discord.ext import commands


import psycopg2
import aiohttp
import dataframe_image as dfi
import discord
import numpy as np
import pandas as pd
import pytz
import sqlalchemy
from discord.ext import commands
from discord.ext.commands import CommandNotFound
from openai import OpenAI
from PIL import Image
from sqlalchemy import create_engine, func, update
from sqlalchemy.ext.automap import automap_base
from sqlalchemy.orm import sessionmaker
from tabulate import tabulate
from titlecase import titlecase

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


MY_GUILD = discord.Object(id=838976035575562293)

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
        await self.add_cog(ApplicationCog(self))
        await self.add_cog(CensusUtils(self))
        await self.add_cog(BotUtils(self))
        await self.add_cog(ToonUtils(self))
        self.tree.copy_global_to(guild=MY_GUILD)

    async def on_ready(self):
        self.devchannel = self.get_channel(self.devchannel_id)
        print(f"Logged in as {self.user} (ID: {self.user.id})")
        print("------")

        await self.tree.sync(guild=MY_GUILD)

        await self.devchannel.send(
            f"<@{self.user.id}> `LOG`: :green_circle: Logged in as {self.user} (ID: {self.user.id})"
        )


class ApplicationCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(help="Apply to join Ex Astra.", brief="Apply to join Ex Astra.")
    async def apply_test(self, ctx):
        discord_id = str(ctx.author.id)
        member = await ctx.guild.fetch_member(discord_id)
        applicant_role = ctx.guild.get_role(990817141831901234)

        await member.add_roles(applicant_role)

        await ctx.reply(
            f"Attention <@816198379344232488>, <@{discord_id}>, has submitted an application."
        )



class CensusUtils(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(
        help="Get information about a toon.", brief="Get information about a toon."
    )
    async def toons_test(self, ctx, toon: str):
        toon = toon.title()
        with Session() as session:
            toon = (
                session.query(tables["census"])
                .filter(tables["census"].name == toon)
                .first()
            )
            if toon:
                all_toons = (
                    session.query(tables["census"])
                    .filter(
                        (tables["census"].discord_id == toon.discord_id)
                        & (tables["census"].status != "Dropped")
                    )
                    .all()
                )
                toon_data = {
                    toon.name: {
                        attr: getattr(toon, attr)
                        for attr in vars(toon)
                        if attr != "_sa_instance_state"
                        and attr != "name"
                        and attr != "discord_id"
                        and attr != "id"
                    }
                    for toon in all_toons
                }
                json_data = json.dumps(toon_data, indent=4, sort_keys=True)
                try:
                    await self.bot.reply_with_view(ctx, f"```{json_data}```")
                except discord.HTTPException:
                    await ctx.reply("That's a lot of toons")
                    await ctx.reply("Remind Rahmani to add a paginator!")
                # toon_dict = toon.__dict__
                # toon_name = toon_dict['name']

                # embed = Embed(title=toon_dict['name'], description="Toon Information", color=0x00ff00)
                # for key, value in toon_dict.items():
                #     if key != '_sa_instance_state':  # Ignore this special SQLAlchemy attribute
                #         embed.add_field(name=key, value=value, inline=False)
                # async with ctx.typing():
                #     await ctx.reply(embed=embed)


bot = PersistentViewBot()
bot.run(discord_token)
