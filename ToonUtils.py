from AutoCompletion import AutoCompletion
from Buttons import DMButton, DeleteButton
from DBConnectionManager import DBConnectionManager
from RichLogger import RichLogger
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
logger = RichLogger(__name__)


class ToonUtils(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_manager = DBConnectionManager(
            db_url=f"postgresql+asyncpg://{pguser}:{pgpass}@{pghost}:5432/{pgdata}",
            search_column="name",
        )
        asyncio.create_task(self.db_manager.prepare_tables())

    def create_cog_view(self, user_id):
        view = discord.ui.View(timeout=None)
        view.add_item(DeleteButton(user_id))
        view.add_item(DMButton(user_id))
        return view

    async def toon_autocomplete(self, interaction: discord.Interaction, current: str):
        auto_completer = await self.db_manager.get_auto_completer("census")
        if auto_completer:
            return await auto_completer.autocomplete(current)
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
    async def toons(self, interaction: discord.Interaction, toon: str):
        census_table = self.db_manager.get_table("census")
        if not census_table:
            # Handle error: table not found
            await interaction.response.send_message(
                "Error: Census table not found.", ephemeral=True
            )
            return
        
        async with self.db_manager.AsyncSession() as session:
            stmt = select(census_table.discord_id).where(
                census_table.name == toon
            )
            results = await session.execute(stmt)
            discord_id = results.scalars().one()
            stmt = select(census_table).where(
                census_table.discord_id == discord_id
            )
            results = await session.execute(stmt)
            matching_data = results.scalars().all()

            toons_list = [toon.name for toon in matching_data]

        await interaction.response.send_message(
            f"{toons_list}",
            view=self.create_cog_view(interaction.user.id),
        )
