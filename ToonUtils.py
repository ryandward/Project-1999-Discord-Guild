from AutoCompletion import AutoCompletion
from Buttons import DMButton, DeleteButton
from config import pgdata, pghost, pgpass, pguser
import logging

import discord
from discord.ext import commands
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.ext.automap import automap_base
from sqlalchemy.orm import sessionmaker

import json


import asyncio
from collections import defaultdict

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ToonUtils(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Initialize the async engine
        self.engine = create_async_engine(
            f"postgresql+asyncpg://{pguser}:{pgpass}@{pghost}:5432/{pgdata}",
            echo=False,
        )
        # Store the async session factory
        self.AsyncSession = sessionmaker(
            bind=self.engine, class_=AsyncSession, expire_on_commit=False
        )
        
        # Initialize cache placeholder
        self.auto_completer = None

        # Asynchronously prepare the database reflection
        asyncio.create_task(self.prepare_tables())

    async def prepare_tables(self):
        # Asynchronous table reflection
        async with self.engine.begin() as conn:
            Base = automap_base()
            await conn.run_sync(Base.prepare)
            self.tables = defaultdict()
            for table_name in Base.classes.keys():
                self.tables[table_name] = Base.classes[table_name]
                
            # Initialize AutoCompletion after tables are prepared
            self.initialize_auto_completer()

    def initialize_auto_completer(self):
        # Ensure tables are prepared before initializing
        if self.tables:
            self.auto_completer = AutoCompletion(
                async_session_factory=self.AsyncSession,
                table=self.tables["census"],
                choice_transformer=lambda row: discord.app_commands.Choice(name=row, value=row)
            )

    async def toon_autocomplete(self, interaction: discord.Interaction, current: str):
        # Ensure auto_completer is initialized
        if self.auto_completer:
            return await self.auto_completer.autocomplete(current)
        else:
            logger.info("AutoCompletion is not yet initialized.")
            return []

    def create_cog_view(self, user_id):
        view = discord.ui.View(timeout=None)
        view.add_item(DeleteButton(user_id))
        view.add_item(DMButton(user_id))
        return view

    @discord.app_commands.command(
        name="toons",
        description="Displays information about toons associated with each other.",
    )
    @discord.app_commands.describe(toon="The member to get info about.")
    @discord.app_commands.autocomplete(toon=toon_autocomplete)
    async def toons(
        self,
        interaction: discord.Interaction,
        toon: str,
    ):
        async with self.AsyncSession() as session:
            stmt = select(self.tables["census"].discord_id).where(
                self.tables["census"].name == toon
            )
            results = await session.execute(stmt)
            discord_id = results.scalars().one()
            stmt = select(self.tables["census"]).where(
                self.tables["census"].discord_id == discord_id
            )
            results = await session.execute(stmt)
            matching_data = results.scalars().all()

            toons_list = [toon.name for toon in matching_data]

        await interaction.response.send_message(
            f"{toons_list}",
            view=self.create_cog_view(interaction.user.id),
        )

