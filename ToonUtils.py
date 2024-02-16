from Buttons import DMButton, DeleteButton
from config import pgdata, pghost, pgpass, pguser


import discord
from discord.ext import commands
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.ext.automap import automap_base
from sqlalchemy.orm import sessionmaker


import asyncio
import time
from collections import defaultdict


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
        cache_entry = self.cache.get(current)

        # Check if cache entry exists and is fresh
        if cache_entry and now - cache_entry['timestamp'] < 60:  # 60 seconds freshness threshold
            return cache_entry['choices']

        # Fetch fresh data and update cache
        async with self.AsyncSession() as session:
            stmt = select(self.tables['census'].name).where(
                self.tables['census'].name.ilike(f"%{current}%")
            ).limit(25)
            results = await session.execute(stmt)
            choices = [
                discord.app_commands.Choice(name=row, value=row) for row in results.scalars().all()
            ]

            # Update cache with new data and timestamp
            self.cache[current] = {'choices': choices, 'timestamp': now}

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