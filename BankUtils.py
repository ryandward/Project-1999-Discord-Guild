from AutoCompletion import AutoCompletion
from Buttons import DMButton, DeleteButton
from RichLogger import RichLogger
from choice_transformer import item_format
from AutoCompletion import AutoCompletion
from DBConnectionManager import DBConnectionManager

from config import pgdata, pghost, pgpass, pguser

import discord
from discord.ext import commands
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.ext.automap import automap_base
from sqlalchemy.orm import sessionmaker
from titlecase import titlecase
import requests
import polars as pl

pl.Config.set_tbl_hide_dataframe_shape(True)
pl.Config.set_tbl_hide_column_data_types(True)
pl.Config.set_tbl_rows(20)

import re
import asyncio
from collections import defaultdict
from discord import Embed, File

# Configure logging
logger = RichLogger(__name__)


def get_image_url(item):
    item = item.replace("Song: ", "").replace("Spell: ", "")
    base_url = "http://localhost/mediawiki/api.php"
    search_params = {
        "action": "query",
        "prop": "revisions",
        "titles": item,
        "rvprop": "content",
        "format": "json",
    }
    search_response = requests.get(base_url, params=search_params).json()
    page_id = list(search_response["query"]["pages"].keys())[0]
    page_data = search_response["query"]["pages"][page_id]

    if "revisions" not in page_data or not page_data["revisions"]:
        logger.info(search_response)
        return None

    content = page_data["revisions"][0]["*"]

    lucy_img_ID = re.search(r"lucy_img_ID\s*=\s*(\d+)", content)
    spellicon = re.search(r"spellicon\s*=\s*(\w+)", content)

    logger.info(f"lucy_img_ID: {lucy_img_ID}")
    logger.info(f"spellicon: {spellicon}")

    if lucy_img_ID:
        image_id = lucy_img_ID.group(1)
        filename = f"item_{image_id}.png"
    elif spellicon:
        image_id = spellicon.group(1)
        filename = f"Spellicon_{image_id}.png"
    else:
        return None

    imageinfo_params = {
        "action": "query",
        "prop": "imageinfo",
        "titles": f"File:{filename}",
        "iiprop": "url",
        "format": "json",
    }
    imageinfo_response = requests.get(base_url, params=imageinfo_params).json()
    image_page_id = list(imageinfo_response["query"]["pages"].keys())[0]
    if "imageinfo" in imageinfo_response["query"]["pages"][image_page_id]:
        image_url = imageinfo_response["query"]["pages"][image_page_id]["imageinfo"][0][
            "url"
        ]
        logger.debug(f"Original image URL: {image_url}")
        image_url = image_url.replace(
            "http://localhost:80/mediawiki/images", "/var/lib/mediawiki"
        )
        logger.debug(f"Modified image URL: {image_url}")
        return image_url

    return None


class BankUtils(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_manager = DBConnectionManager(
            db_url=f"postgresql+asyncpg://{pguser}:{pgpass}@{pghost}:5432/{pgdata}",
            search_column="name",
            format=item_format,
        )
        asyncio.create_task(self.db_manager.prepare_tables())

    def create_cog_view(self, user_id):
        view = discord.ui.View(timeout=None)
        view.add_item(DeleteButton(user_id))
        view.add_item(DMButton(user_id))
        return view

    async def bank_autocomplete(self, interaction: discord.Interaction, current: str):
        auto_completer = await self.db_manager.get_auto_completer("bank")
        if auto_completer:
            return await auto_completer.autocomplete(current)
        else:
            logger.info("AutoCompletion is not yet initialized.")
            return []

    @discord.app_commands.command(name="find", description="Find a guild bank item.")
    @discord.app_commands.describe(item="The item you'd like to find")
    @discord.app_commands.autocomplete(item=bank_autocomplete)
    async def find(self, interaction: discord.Interaction, item: str):
        bank_table = self.db_manager.get_table("bank")
        if not bank_table:
            # Handle error: table not found
            await interaction.response.send_message(
                "Error: Bank table not found.", ephemeral=True
            )
            return

        async with self.db_manager.AsyncSession() as session:
            stmt = select(bank_table).where(bank_table.name == item)
            results = await session.execute(stmt)
            matching_data = results.scalars().all()

            items_list = [
                (item.name, item.banker, item.quantity, item.location)
                for item in matching_data
            ]

            df = pl.DataFrame(
                {
                    "banker": [item[1] for item in items_list],
                    "quantity": [item[2] for item in items_list],
                    "location": [item[3] for item in items_list],
                }
            )

            if df.shape[0] == 0:
                await interaction.response.send_message(
                    f":x: {titlecase(item)} was not found on any bankers.\nWhile using `/find`, check the autocomplete for a list of items.",
                    view=self.create_cog_view(interaction.user.id),
                )
                return

            image_url = get_image_url(item)
            embed = Embed()
            file = None
            if image_url:
                file = File(image_url, filename="image.png")
                embed.set_image(url=f"attachment://image.png")
            embed.add_field(
                name=f":white_check_mark: {titlecase(item)} was found in the guild coffers.",
                value=f"```{df}```",
                inline=False,
            )

            if not image_url:
                await interaction.response.send_message(
                    embed=embed, view=self.create_cog_view(interaction.user.id)
                )

            else:
                await interaction.response.send_message(
                    embed=embed,
                    file=file,
                    view=self.create_cog_view(interaction.user.id),
                )
