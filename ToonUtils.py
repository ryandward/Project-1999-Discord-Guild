from Buttons import DMButton, DeleteButton
from config import pgdata, pghost, pgpass, pguser
import logging

import discord
from discord.ext import commands
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.ext.automap import automap_base
from sqlalchemy.orm import sessionmaker


import asyncio
import time
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
        # Initialize cache
        self.cache = {}  # Added this line to initialize the cache

        # Asynchronously prepare the database reflection
        asyncio.create_task(self.prepare_tables())

    async def prepare_tables(self):
        # Asynchronous table reflection
        async with self.engine.begin() as conn:
            Base = automap_base()
            await conn.run_sync(Base.prepare)  # Removed the explicit `autoload_with`
            self.tables = defaultdict()
            for table_name in Base.classes.keys():
                self.tables[table_name] = Base.classes[table_name]

    def create_cog_view(self, user_id):
        view = discord.ui.View(timeout=None)
        view.add_item(DeleteButton(user_id))
        view.add_item(DMButton(user_id))
        return view

    async def toon_autocomplete(self, interaction: discord.Interaction, current: str):
        now = time.time()

        if not current:
            logger.info("Empty query received; skipping cache and database query.")
            return []

        logger.info(f"Autocomplete requested for '{current}'.")

        # Check cache first
        for cache_key in self.cache.keys():
            if current.startswith(cache_key):
                cache_entry = self.cache[cache_key]
                if now - cache_entry["timestamp"] < 60:  # Cache freshness check
                    filtered_choices = [
                        choice
                        for choice in cache_entry["choices"]
                        if current.lower() in choice.name.lower()
                    ][
                        :25
                    ]  # Ensure no more than 25 choices are returned
                    logger.info(
                        f"Cache hit for '{current}' using cache key '{cache_key}'. {len(filtered_choices)} choices returned after filtering."
                    )
                    return filtered_choices
                else:
                    logger.info(f"Cache entry for key '{cache_key}' is stale.")

        # If not found in cache, fetch from database
        logger.info(f"No suitable cache found for '{current}'. Querying database.")
        async with self.AsyncSession() as session:
            stmt = select(self.tables["census"].name, self.tables["census"].discord_id).where(
                self.tables["census"].name.ilike(f"%{current}%")
            )
            
            results = await session.execute(stmt)
            choices = [
                discord.app_commands.Choice(name=row, value=row)
                for row in results.scalars().all()
            ][
                :25
            ]  # Ensure no more than 25 choices are returned
            logger.info(
                f"Database query completed for '{current}'. {len(choices)} choices fetched and cached."
            )

            # Update cache with new data and timestamp
            self.cache[current] = {"choices": choices, "timestamp": now}
            logger.info(f"Cache updated for '{current}'.")

            return choices

    @discord.app_commands.command(
        name="toons",
        description="Displays information about toons associated with each other.",
    )
    @discord.app_commands.describe(
        toon="The member to get info about. Leave empty for yourself."
    )
    @discord.app_commands.autocomplete(toon=toon_autocomplete)
    async def toons(
        self,
        interaction: discord.Interaction,
        toon: str,
    ):
        await interaction.response.send_message(
            f"Thank you for your interest in {toon}! Rahmani is working on this feature.",
            view=self.create_cog_view(interaction.user.id),
        )
