#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Imports
import datetime
import io
import json
import os
import re
import sqlite3
import subprocess
import tempfile
import time
from difflib import get_close_matches as gcm
from pathlib import Path
from urllib.request import Request, urlopen
from embed_assisted_questions import ask_async

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
from sqlalchemy.orm import Session, sessionmaker
from tabulate import tabulate
from titlecase import titlecase

import config


def table_to_file(pandas_table):
    pandas_table.columns = pandas_table.columns.str.title()

    if len(pandas_table) > 20:
        # Create a temporary text file
        with tempfile.NamedTemporaryFile(
            prefix="Table_", suffix=".txt", delete=False
        ) as temp:
            # Use tabulate for DataFrames with more than 20 rows
            table_string = tabulate(
                pandas_table,
                headers=pandas_table.columns,
                tablefmt="simple",
                showindex=False,
            )
            temp.write(table_string.encode())

            # Create a discord file
            file = discord.File(temp.name)

    else:
        # Create a temporary file
        with tempfile.NamedTemporaryFile(
            prefix="Table_", suffix=".png", delete=False
        ) as temp:
            # Define a function to change the background color if all entries are spaces
            def highlight_spaces(data):
                attr = (
                    "background-color: #a3a3a3"  # change 'gray' to your preferred color
                )
                padding_attr = "padding: 3"
                if "".join(str(d) for d in data).isspace():
                    return [f"{attr}; {padding_attr}"] * len(data)
                else:
                    return [""] * len(data)

            def alternating_color(data):
                colors = [
                    "background-color: white",
                    "background-color: whitesmoke",
                ]  # change colors as needed
                default_color = "background-color: default"
                color_index = 0
                color_list = []
                for i in range(len(data)):
                    item = data.iloc[i]
                    if np.isscalar(item):
                        item_str = str(item)
                    else:
                        item_str = "".join(str(d) for d in item)
                    if item_str.isspace():
                        color_list.append(default_color)
                        color_index = 0  # reset color index at section breaks
                    else:
                        color_list.append(colors[color_index])
                        color_index = 1 - color_index  # alternate color index
                return color_list

            mpl_table_styled = (
                pandas_table.style.set_properties(**{"text-align": "left"})
                .set_table_styles(
                    [dict(selector="th", props=[("text-align", "center")])]
                )
                .apply(highlight_spaces, axis=1)
                .apply(alternating_color, axis=0)
            )

            dfi.export(mpl_table_styled.hide(axis="index"), temp.name)

            # Open the image file
            table_image = Image.open(temp.name)
            # Convert the image to grayscale
            table_image = table_image.convert("L")
            # Save the image with reduced quality
            table_image.save(temp.name, optimize=True, quality=20)

            # Create a discord file
            file = discord.File(temp.name)

    return file, temp.name


def has_numbers(inputString):
    return any(char.isdigit() for char in inputString)


def chop_microseconds(delta):
    return delta - datetime.timedelta(microseconds=delta.microseconds)


def list_to_oxford_comma(names):
    if len(names) == 0:
        return ""
    elif len(names) == 1:
        return names[0]
    elif len(names) == 2:
        return f"{names[0]} and {names[1]}"
    else:
        return ", ".join(names[:-1]) + f", and {names[-1]}"


def check_reply(ctx):
    result = ctx.message.reference
    if result is None:
        return False
    else:
        return True


def chunk_strings(s, limit=1900):
    s = s.replace("`", "'")
    lines = s.split("\n")
    chunks, chunk = [], lines[0]
    for line in lines[1:]:
        if len(chunk + "\n" + line) > limit:
            chunks.append(chunk)
            chunk = line
        else:
            chunk += "\n" + line
    chunks.append(chunk)
    return chunks


con = sqlite3.connect("ex_astra.db")
con.execute("PRAGMA foreign_keys = ON")
cur = con.cursor()


def close_connection():
    global con
    if con is not None:
        con.close()


player_classes = pd.read_sql_query("SELECT * FROM class_definitions", con)
raids = pd.read_sql_query("SELECT * FROM raids", con)


class DeleteButton(
    discord.ui.DynamicItem[discord.ui.Button], template=r"delete:user:(?P<id>[0-9]+)"
):
    def __init__(self, user_id: int) -> None:
        super().__init__(
            discord.ui.Button(
                label="Delete Response",
                style=discord.ButtonStyle.danger,
                custom_id=f"delete:user:{user_id}",
            )
        )
        self.user_id: int = user_id

    # This is called when the button is clicked and the custom_id matches the template.
    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match: re.Match[str],
        /,
    ):
        user_id = int(match["id"])
        return cls(user_id)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # Only allow the user who created the button to interact with it.
        return interaction.user.id == self.user_id

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message("Response deleted!", ephemeral=True)
        await interaction.message.delete()


class DMButton(
    discord.ui.DynamicItem[discord.ui.Button], template=r"DM:user:(?P<id>[0-9]+)"
):
    def __init__(self, user_id: int) -> None:
        super().__init__(
            discord.ui.Button(
                label="DM Response",
                style=discord.ButtonStyle.primary,
                custom_id=f"DM:user:{user_id}",
            )
        )
        self.user_id: int = user_id

    # This is called when the button is clicked and the custom_id matches the template.
    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match: re.Match[str],
        /,
    ):
        user_id = int(match["id"])
        return cls(user_id)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # Only allow the user who created the button to interact with it.
        return interaction.user.id == self.user_id

    async def callback(self, interaction: discord.Interaction) -> None:
        # retrieve message contents, attachments, and embeds
        message = interaction.message
        message_content = message.content
        message_attachments = []
        for attachment in message.attachments:
            file = await attachment.to_file()  # Download the attachment
            message_attachments.append(file)
        message_embeds = message.embeds

        await interaction.response.send_message("Sending via DM...", ephemeral=True)
        await interaction.user.send(
            content=message_content, files=message_attachments, embeds=message_embeds
        )
        await interaction.followup.send_message("DM sent!", ephemeral=True)


class PersistentViewBot(commands.Bot):
    def __init__(self):

        intents = discord.Intents.all()
        intents.message_content = True
        intents.members = True

        super().__init__(
            command_prefix=config.prefix, intents=intents, case_insensitive=True
        )

    async def setup_hook(self) -> None:
        # Register the persistent view for listening here.
        # Note that this does not send the view to any message.
        # In order to do this you need to first send a message with the View, which is shown below.
        # If you have the message_id you can also pass it as a keyword argument, but for this example
        # we don't have one.
        # self.add_view(PersistentView())
        # # For dynamic items, we must register the classes instead of the views.
        self.add_dynamic_items(DeleteButton)
        self.add_dynamic_items(DMButton)

    async def on_ready(self):
        print(f"Logged in as {self.user} (ID: {self.user.id})")
        print("------")


client = PersistentViewBot()

openai_client = OpenAI(api_key=config.openai_token)


@client.check
async def globally_block_dms(ctx):
    return ctx.guild is not None or ctx.author.id == 816198379344232488


@client.command(help="Check the bot's latency.", brief="Check the bot's latency.")
async def ping(ctx):
    latency = round(client.latency * 1000)  # latency is in seconds, so we multiply by 1000 to get milliseconds
    await ctx.reply(f":ping_pong: Latency is `{latency} ms`")


@client.command(help="Apply to join Ex Astra.", brief="Apply to join Ex Astra.")
async def apply(ctx):

    # discord_id = ctx.message.guild.get_member_named(format(ctx.author)).id
    discord_id = str(ctx.author.id)
    channel = client.get_channel(988260644056879194)  # census chat
    member = await ctx.guild.fetch_member(discord_id)
    applicant_role = ctx.guild.get_role(990817141831901234)  # come back to this

    await member.add_roles(applicant_role)

    await ctx.reply(
        f"Attention <@&849337092324327454> and <@&906952889287708773>, <@{discord_id}>, has submitted an application."
    )


@client.command(
    help="Deducts a specified amount from a user's total.",
    brief="Deducts a specified amount from a user's total",
)
@commands.has_role("Lootmaster")
async def deduct(
    ctx,
    amount: int = commands.parameter(description="The amount to deduct."),
    name: str = commands.parameter(description="The name of the toon."),
    *,
    args: str = commands.parameter(description="The reason/item for the deduction."),
):
    async with ctx.typing():

        census = pd.read_sql_query("SELECT * FROM census", con)
        dkp = pd.read_sql_query("SELECT * FROM dkp", con)

        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        name = name.capitalize()

        if len(census.loc[census["name"] == name, "discord_id"]) == 0:
            await ctx.reply(f":exclamation:No character named `{name}` was found.")
            # this is an error
            return

        discord_id = census.loc[census["name"] == name, "discord_id"].item()

        earned_dkp = dkp.loc[dkp["discord_id"] == discord_id, "earned_dkp"].item()

        spent_dkp = dkp.loc[dkp["discord_id"] == discord_id, "spent_dkp"].item()

        current_dkp = earned_dkp - spent_dkp

        if current_dkp >= amount:
            cur.execute(
                "INSERT INTO items (name, item, dkp_spent, date, discord_id) VALUES (?, ?, ?, ?, ?);",
                (name.capitalize(), titlecase(args), amount, current_time, discord_id),
            )

            if cur.rowcount == 1:
                cur.execute(
                    "UPDATE dkp SET spent_dkp = spent_dkp + ? WHERE discord_id = ?;",
                    (str(amount), discord_id),
                )

                if cur.rowcount == 1:
                    con.commit()

                    await ctx.reply(
                        f":white_check_mark:<@{discord_id}> spent `{amount}` DKP on `{titlecase(args)}` for `{name.capitalize()}`!"
                    )

                else:
                    con.rollback()

                    await ctx.reply(
                        f":question:Something weird happened, ask Rahmani. `Error -2`"
                    )

            else:
                con.rollback()

                await ctx.reply(
                    f":question:Something weird happened, ask Rahmani. `Error -1`"
                )

        else:
            await ctx.reply(
                f":exclamation:`{amount}` is greater than `{name.capitalize()}`'s current total of `{current_dkp}` DKP\nNo action taken"
            )


################################################################################


@client.command(
    help="Awards a specified amount to a user.",
    brief="Awards a specified amount to a user",
)
@commands.has_any_role("Officer", "Probationary Officer", "Lootmaster")
async def award(
    ctx,
    amount: int = commands.parameter(description="The amount to award."),
    name: str = commands.parameter(description="The name of the toon."),
    *,
    args: str = commands.parameter(description="The reason for the award."),
):
    census = pd.read_sql_query("SELECT * FROM census", con)

    dkp = pd.read_sql_query("SELECT * FROM dkp", con)

    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    name = name.capitalize()

    if len(census.loc[census["name"] == name, "discord_id"]) == 0:
        await ctx.reply(f":exclamation:No character named `{name}` was found.")
        # this is an error
        return

    discord_id = census.loc[census["name"] == name, "discord_id"].item()

    earned_dkp = dkp.loc[dkp["discord_id"] == discord_id, "earned_dkp"].item()

    spent_dkp = dkp.loc[dkp["discord_id"] == discord_id, "spent_dkp"].item()

    current_dkp = earned_dkp - spent_dkp

    cur.execute(
        "INSERT INTO attendance (raid, name, date, discord_id, modifier) VALUES (?, ?, ?, ?, ?);",
        (titlecase(args), name.capitalize(), current_time, discord_id, amount),
    )

    if cur.rowcount == 1:
        cur.execute(
            "UPDATE dkp SET earned_dkp = earned_dkp + ? WHERE discord_id = ?;",
            (str(amount), discord_id),
        )

        if cur.rowcount == 1:
            con.commit()

            await ctx.reply(
                f":white_check_mark:<@{discord_id}> earned `{amount}` DKP for `{titlecase(args)}` on `{name.capitalize()}`!"
            )

        else:
            con.rollback()

            await ctx.reply(
                f":question:Something weird happened, ask Rahmani. `Error -2`"
            )

    else:
        con.rollback()

        await ctx.reply(f":question:Something weird happened, ask Rahmani. `Error -1`")


# Helper functions


async def get_discord_id(ctx, user_name, discord_id):
    if discord_id is None:
        # discord_id = str(ctx.message.guild.get_member_named(user_name).id)
        discord_id = str(ctx.author.id)
    return discord_id


async def check_allowed_channels(ctx):
    allowed_channels = [851549677815070751, 862364645695422514]
    if ctx.channel.id not in allowed_channels:
        return False
    return True


def get_census():
    return pd.read_sql_query("SELECT * FROM census", con)


def get_level(level):
    if level < 0 or level > 60:
        raise ValueError("Invalid level. The level must be between 0 and 60.")
    else:
        return level


async def get_player_class(player_class):
    player_class = titlecase(player_class)
    player_class_names = player_classes["class_name"].to_list()
    player_class_name = gcm(player_class, player_class_names, n=1, cutoff=0.5)
    if len(player_class_name) == 0:
        raise ValueError("Invalid player class. Please provide a valid player class.")
    else:
        player_class_name = player_class_name[0]
        player_class = player_classes.loc[
            player_classes["class_name"] == player_class_name, "character_class"
        ].item()
        return player_class


def get_toon_data(toon):
    cur.execute("SELECT * FROM census WHERE name == ?;", (toon.capitalize(),))
    rows = cur.fetchall()
    return rows


def check_discord_exists(discord_id):
    cur.execute("SELECT * FROM dkp WHERE discord_id == ?;", (discord_id,))
    discord_exists = cur.fetchall()
    return len(discord_exists) > 0


def add_user_to_dkp(user_name, discord_id, current_time):
    cur.execute(
        "INSERT INTO dkp (discord_name, earned_dkp, spent_dkp, date_joined, discord_id) VALUES (?, 5, 0, ?, ?);",
        (user_name, current_time, discord_id),
    )
    con.commit()


def update_census(toon, status, level, player_class, current_time):
    if level is None:
        cur.execute(
            "UPDATE census SET status = ?, time = ? WHERE name = ?;",
            (status.capitalize(), current_time, toon.capitalize()),
        )
    elif player_class is None:
        cur.execute(
            "UPDATE census SET status = ?, level = ?, time = ? WHERE name = ?;",
            (status.capitalize(), level, current_time, toon.capitalize()),
        )
    else:
        cur.execute(
            "UPDATE census SET status = ?, level = ?, character_class = ?, time = ? WHERE name = ?,",
            (status.capitalize(), level, player_class, current_time, toon.capitalize()),
        )
    con.commit()


def insert_to_census(toon, level, player_class, discord_id, status, current_time):
    cur.execute(
        "INSERT INTO census (name, level, character_class, discord_id, status, time) VALUES (?, ?, ?, ?, ?, ?);",
        (
            toon.capitalize(),
            level,
            player_class,
            discord_id,
            status.capitalize(),
            current_time,
        ),
    )
    con.commit()


# Main function


async def declare_toon(
    ctx,
    status,
    toon,
    level: int = None,
    player_class: str = None,
    user_name: str = None,
    discord_id: str = None,
):
    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if level is not None:
        if level < 1 or level > 60:
            await ctx.reply(
                f":crossed_swords: Hail, `{toon.capitalize()}`! In the realms of Norrath, levels range from `1` to `60`. Adjust your compass and try again!"
            )
            return

    # capitalize toon name
    toon = toon.capitalize()

    if discord_id is None:
        try:
            discord_id = await get_discord_id(ctx, user_name, discord_id)
        except Exception as e:
            await ctx.reply(f"An error occurred while getting the discord id: {str(e)}")
            return
    if not await check_allowed_channels(ctx):
        await ctx.reply("This action must be performed on <#851549677815070751>.")
        return

    try:
        census = get_census()
    except Exception as e:
        await ctx.reply(f"An error occurred while getting the census: {str(e)}")
        return

    if player_class is not None:
        try:
            player_class = await get_player_class(player_class)
        except Exception as e:
            await ctx.reply(
                f"An error occurred while getting the player class: {str(e)}"
            )
            return

    try:
        toon_data = get_toon_data(toon)
    except Exception as e:
        await ctx.reply(f"An error occurred while getting the toon data: {str(e)}")
        return

    try:
        discord_exists = check_discord_exists(discord_id)
    except Exception as e:
        await ctx.reply(f"An error occurred while checking if discord exists: {str(e)}")
        return

    if not discord_exists:
        try:
            add_user_to_dkp(user_name, discord_id, current_time)
            probationary_role = ctx.guild.get_role(884172643702546473)
            probationary_discussion = client.get_channel(884164383498965042)

            await ctx.message.author.add_roles(probationary_role)
            await probationary_discussion.send(
                f"`{toon}` just joined the server using the discord handle <@{discord_id}> and is now a probationary member."
            )

        except Exception as e:
            await ctx.reply(f"An error occurred while adding user to dkp: {str(e)}")
            return

    if player_class is not None and level is not None:

        try:
            toon_data = get_toon_data(toon)
            if toon_data:
                raise ValueError(
                    f"`{toon.capitalize()}` has previous records, try changing status with `!main`/`!alt` `name`."
                )

        except Exception as e:
            await ctx.reply(f"An error occurred while getting the toon data: {str(e)}")
            return

        try:
            insert_to_census(
                toon, level, player_class, discord_id, status, current_time
            )
            census = get_census()
            toon_rows = census.loc[census["name"] == toon, "discord_id"]
            if len(toon_rows) != 1:
                raise ValueError(
                    f"Expected exactly one row with name {toon}, but found {len(toon_rows)} rows"
                )
            owner = toon_rows.iloc[0]
            await ctx.reply(
                f":white_check_mark:<@{owner}>'s `{toon.capitalize()}` was entered into the census and is now a level `{level}` `{player_class}` `{status}`"
            )
            return

        except Exception as e:
            await ctx.reply(
                f"An error occurred while inserting `{toon.capitalize()}` to census. Probably already exists. Try changing status. {str(e)}"
            )

            return

    if len(toon_data) == 1:
        try:
            update_census(toon, status, level, player_class, current_time)
            census = get_census()
            toon_rows = census.loc[census["name"] == toon, "discord_id"]
            if len(toon_rows) != 1:
                raise ValueError(
                    f"Expected exactly one row with name {toon}, but found {len(toon_rows)} rows"
                )
            owner = toon_rows.iloc[0]
            await ctx.reply(
                f":white_check_mark:<@{owner}>'s `{toon.capitalize()}` is now `{status}`"
            )
            return

        except Exception as e:
            await ctx.reply(f"An error occurred while updating census: {str(e)}")
            return

    if len(toon_data) == 0:
        await ctx.reply(
            f":exclamation:`{toon.capitalize()}` was not found\nSee `!help main/alt/drop`"
        )
        return

    if len(toon_data) > 1:
        await ctx.reply(
            f":exclamation:`{toon.capitalize()}` is ambiguous\nSee `!help main/alt/drop`"
        )
        return


#######################################


@client.command(
    help="Promotes a toon's owner to member.",
    brief="Promotes a toon's owner to member.",
)
@commands.has_role("Officer")
async def promote(
    ctx, name: str = commands.parameter(description="The name of the toon to promote.")
):
    try:
        name = name.capitalize()
        census = pd.read_sql_query("SELECT * FROM census", con)
        dkp = pd.read_sql_query("SELECT * FROM dkp", con)
        discord_id = census.loc[census["name"] == name, "discord_id"].item()

        channel = client.get_channel(851549677815070751)  # census chat
        member = await ctx.guild.fetch_member(discord_id)
        probationary_role = ctx.guild.get_role(884172643702546473)  # come back to this
        member_role = ctx.guild.get_role(870669705646587924)

        await member.remove_roles(probationary_role)
        await member.add_roles(member_role)

        await ctx.reply(f"{name} has been promoted to full member.")
        await channel.send(
            f"<@&870669705646587924> Send your congrats to <@{discord_id}>, the newest full member of Ex Astra!"
        )
    except AttributeError:
        await ctx.reply(
            f"Sorry, a user with the name {name} could not be found. Please check the spelling and try again."
        )
    except Exception as e:
        await ctx.reply(f"An error occurred while promoting {name}. Error message: {e}")


@client.command(
    help="Assigns a status, level, and class to a user. Usage: !assign <status> <toon> <level> <player_class> <discord_name>",
    brief="Assigns a status, level, and class to a user",
)
@commands.has_role("Officer")
async def assign(
    ctx,
    status: str = commands.parameter(description="The status to assign."),
    toon: str = commands.parameter(description="The name of the toon."),
    level: int = commands.parameter(description="The level of the toon."),
    player_class: str = commands.parameter(description="The class of the toon."),
    discord_name: str = commands.parameter(
        description="The Discord name of the user. Use quotes."
    ),
):
    # Join all remaining arguments into a single string

    # Get a list of the display names of all members in the server
    member_names = [member.display_name for member in ctx.guild.members]

    # Find the display name that most closely matches discord_name
    close_matches = gcm(discord_name, member_names, n=1, cutoff=0.75)

    if close_matches:
        # Get the member objects for the closest match
        members = [m for m in ctx.guild.members if m.display_name == close_matches[0]]

        if len(members) > 1:
            await ctx.send(
                f"Multiple members found with the name {close_matches[0]}. Please be more specific."
            )
            return

        discord_id = members[0].id
    else:
        await ctx.send(
            f"No member found with a name close to {discord_name}. Click and copy their server nickname."
        )
        return

    try:
        await declare_toon(
            ctx,
            status,
            toon,
            level,
            player_class,
            user_name=discord_name,
            discord_id=str(discord_id),
        )
    except Exception as e:
        await ctx.send(f"An error occurred while declaring the toon: {e}")


@client.command(
    help="Assigns or switches a main character for a user.",
    brief="Assigns or switches a main character for a user",
)
async def main(
    ctx,
    toon: str = commands.parameter(
        description="The name of the character to assign as the main."
    ),
    level: int = commands.parameter(
        description="The level of the character (optional).", default=None
    ),
    player_class: str = commands.parameter(
        description="The class of the character (optional).", default=None
    ),
):
    user_name = format(ctx.author)
    try:
        await declare_toon(ctx, "Main", toon, level, player_class, user_name)
    except ValueError as e:
        await ctx.reply(f"Error: {e}")


@client.command(
    help="Assigns or switches a bot character for a user.",
    brief="Assigns or switches a bot character for a user",
)
async def bot(
    ctx,
    toon: str = commands.parameter(
        description="The name of the character to assign as the bot."
    ),
    level: int = commands.parameter(
        description="The level of the character (optional).", default=None
    ),
    player_class: str = commands.parameter(
        description="The class of the character (optional).", default=None
    ),
):
    user_name = format(ctx.author)
    try:
        await declare_toon(ctx, "Bot", toon, level, player_class, user_name)
    except ValueError as e:
        await ctx.reply(f"Error: {e}")


@client.command(
    help="Assigns or switches an alt character for a user.",
    brief="Assigns or switches an alt character for a user",
)
async def alt(
    ctx,
    toon: str = commands.parameter(
        description="The name of the character to assign as the alt."
    ),
    level: int = commands.parameter(
        description="The level of the character (optional).", default=None
    ),
    player_class: str = commands.parameter(
        description="The class of the character (optional).", default=None
    ),
):
    user_name = format(ctx.author)
    try:
        await declare_toon(ctx, "Alt", toon, level, player_class, user_name)
    except ValueError as e:
        await ctx.reply(f"Error: {e}")


@client.command(
    help="Drops a character for a user. Usage: !drop <toon> [level] [player_class]",
    brief="Drops a character for a user",
)
async def drop(
    ctx,
    toon: str = commands.parameter(description="The name of the character to drop."),
    level: int = commands.parameter(
        description="The level of the character (optional).", default=None
    ),
    player_class: str = commands.parameter(
        description="The class of the character (optional).", default=None
    ),
):
    user_name = format(ctx.author)
    cur.execute(
        "SELECT DISTINCT name from census WHERE status == ? and name == ?;",
        ("Dropped", toon.capitalize()),
    )
    rows = cur.fetchall()

    # determine if the character's toon has already been dropped
    if len(rows) > 0:
        await ctx.reply(
            f":question:`{toon.capitalize()}` was not found\nSee `!help main/alt/drop`"
        )

    else:
        await declare_toon(ctx, "Dropped", toon, level, player_class, user_name)


@client.command(
    help="Purges all characters associated with a given character's name. Usage: !purge <toon>",
    brief="Purges all characters associated with a given character's name",
)
@commands.has_role("Officer")
async def purge(
    ctx,
    toon: str = commands.parameter(description="The name of the character to purge."),
):
    cur.execute("SELECT discord_id FROM census WHERE name = ?;", (toon.capitalize(),))
    rows = cur.fetchall()
    if len(rows) == 0:
        await ctx.reply(
            f":warning: No character named `{toon.capitalize()}` found in the census."
        )
        return
    discord_id = rows[0][0]
    cur.execute("SELECT DISTINCT name FROM census WHERE discord_id = ?;", (discord_id,))
    all_toons = cur.fetchall()
    for row in all_toons:
        toon_name = row[0]
        await drop(ctx, toon_name)
    await ctx.reply(
        f":white_check_mark: All toons associated with `{toon.capitalize()}` have been purged."
    )


@client.command(
    aliases=["level"],
    help="Updates the level of a character. If new level is not provided, the character's current level is incremented by 1.]",
    brief="Updates the level of a character",
)
async def ding(
    ctx,
    toon: str = commands.parameter(
        description="The name of the character whose level is to be updated."
    ),
    new_level: int = commands.parameter(
        description="The new level of the character. Defaults to level +1.",
        default=None,
    ),
):
    try:
        engine = create_engine(config.db_url, echo=False)
        Session = sessionmaker(bind=engine)
        session = Session()

        # Reflect the tables
        Base = automap_base()
        Base.prepare(autoload_with=engine)

        # Mapped classes are now created with names by default
        # matching that of the table name.
        Census = Base.classes.census
        Attendance = Base.classes.attendance
        Class_definitions = Base.classes.class_definitions
        DKP = Base.classes.dkp
        Class_lore = Base.classes.class_lore

        # See what the rank of the user is by the earned_dkp column in DKp
        from sqlalchemy import desc

        # Assuming `session` is your SQLAlchemy session and `user_id` is the ID of the user

        toon_data = session.query(Census).filter_by(name=toon.capitalize()).first()
        toon_owner = toon_data.discord_id
        hours_raided = (
            session.query(Attendance).filter_by(discord_id=toon_owner).count()
        )

        user_dkp = session.query(DKP).filter_by(discord_id=toon_owner).first()
        user_rank = (
            session.query(DKP)
            .order_by(desc(DKP.earned_dkp))
            .filter(DKP.earned_dkp >= user_dkp.earned_dkp)
            .count()
        )
        total_users = session.query(DKP).count()

        if toon_data is None:
            await ctx.reply(
                f":x: <@{toon_owner}>'s `{toon.capitalize()}` was not found."
            )
            return

        current_level = toon_data.level

        if new_level is None:
            # If new_level is not provided, increment the toon's current level by 1
            new_level = current_level + 1

        player_class = toon_data.character_class

        # Query the Class_definitions table for the records where level_attained is less than or equal to current_level and new_level
        current_title_record = (
            session.query(Class_definitions)
            .filter(
                Class_definitions.character_class == player_class,
                Class_definitions.level_attained <= current_level,
            )
            .order_by(Class_definitions.level_attained.desc())
            .first()
        )
        new_title_record = (
            session.query(Class_definitions)
            .filter(
                Class_definitions.character_class == player_class,
                Class_definitions.level_attained <= new_level,
            )
            .order_by(Class_definitions.level_attained.desc())
            .first()
        )

        # Extract the titles from the records
        current_title = (
            current_title_record.class_name.lower()
            if current_title_record
            else player_class
        )
        new_title = (
            new_title_record.class_name.lower() if new_title_record else player_class
        )

        # Query the Class_lore table and store the result in a new variable
        class_lore_record = (
            session.query(Class_lore).filter_by(character_class=player_class).first()
        )
        player_class_lore = class_lore_record.description if class_lore_record else ""

        player_class = player_class.lower()

        # Check that the new level is valid
        if new_level == current_level:
            await ctx.reply(
                f":level_slider: `{toon.capitalize()}` is already at level `{new_level}`"
            )
            return

        if new_level < 1 or new_level > 60:
            await ctx.reply(
                f":compass: Hail, `{toon.capitalize()}`! In the realms of Norrath, levels range from `1` to `60`. Adjust your compass and try again!"
            )
            return

        # Update the level in the database
        stmt = (
            update(Census)
            .where(Census.name == toon.capitalize())
            .values(level=new_level)
        )
        session.execute(stmt)
        session.commit()
        session.close()

        # Choose the symbol based on whether the new level is higher or lower than the current level
        symbol = (
            ":arrow_double_up:" if new_level > current_level else ":arrow_double_down:"
        )
        await ctx.reply(
            f"{symbol}<@{toon_owner}>'s `{toon.capitalize()}` is now level `{new_level}`"
        )

        question = f"My name is {toon.capitalize()} and I've just advanced from level {current_level} to level {new_level} as a {player_class}. Could you provide some specific tips or strategies that are relevant to my class at this new level? --required_keywords={player_class}"
        command = client.get_command("ask")
        await ctx.invoke(command, question=question)

    except Exception as e:
        # pass
        await ctx.reply(content=f":x: An error occurred: {str(e)}")

    finally:
        pass

    # await ctx.reply(message_content)


@client.command(
    help="Decreases the level of a character by 1. Usage: !dong <toon>",
    brief="Decreases the level of a character",
)
async def dong(
    ctx,
    toon: str = commands.parameter(
        description="The name of the character whose level is to be decreased."
    ),
):
    try:
        engine = create_engine(config.db_url, echo=False)
        Session = sessionmaker(bind=engine)
        session = Session()

        # Reflect the tables
        Base = automap_base()
        Base.prepare(autoload_with=engine)

        # Mapped classes are now created with names by default
        # matching that of the table name.
        Census = Base.classes.census

        toon_data = session.query(Census).filter_by(name=toon.capitalize()).first()
        toon_owner = toon_data.discord_id

        if toon_data is None:
            await ctx.reply(f":x: `{toon.capitalize()}` was not found.")
            return

        current_level = toon_data.level

        if current_level == 1:
            await ctx.reply(
                f":level_slider: <@{toon_owner}>'s `{toon.capitalize()}` is already at the lowest level `{current_level}`!"
            )
            return

        new_level = current_level - 1

        # Invoke the ding command with the new level
        await ctx.invoke(client.get_command("ding"), toon=toon, new_level=new_level)

    except Exception as e:
        await ctx.reply(content=f":x: An error occurred: {str(e)}")
    finally:
        session.close()


def create_toons_embed(owner, toons):
    main_toons = toons[toons["status"] == "Main"]
    alt_toons = toons[toons["status"] == "Alt"]
    bot_toons = toons[toons["status"] == "Bot"]

    # Get the current time and convert it to a Unix timestamp
    current_time = datetime.datetime.now()
    unix_timestamp = int(current_time.timestamp())

    toons_list = discord.Embed(
        title=f":book: Record of Toons in the Ex Astra Census",
        # get the owners discord id
        description=f"<@{owner.id}>\n<t:{unix_timestamp}:R>",
        colour=discord.Colour.from_rgb(241, 196, 15),
    )

    def add_toons_to_embed(embed, toons, status):
        if len(toons) > 0:
            embed.add_field(
                name=status,
                value=f"{len(toons)} character(s) declared as {status.lower()}s",
                inline=False,
            )

            embed.add_field(
                name=":bust_in_silhouette: Name",
                value="```\n" + "\n".join(toons.name.tolist()) + "\n```",
                inline=True,
            )

            embed.add_field(
                name=":crossed_swords:️ Class",
                value="```\n" + "\n".join(toons.character_class.tolist()) + "\n```",
                inline=True,
            )

            embed.add_field(
                name=":arrow_double_up: Level",
                value="```\n" + "\n".join(map(str, toons.level.tolist())) + "\n```",
                inline=True,
            )

    add_toons_to_embed(toons_list, main_toons, "Main")
    add_toons_to_embed(toons_list, alt_toons, "Alt")
    add_toons_to_embed(toons_list, bot_toons, "Bot")

    return toons_list


@client.command(
    help="Displays information about a character or all characters if no character is specified. Usage: !toons [toon]",
    brief="Displays information about a character or all characters",
)
async def toons(
    ctx,
    toon: str = commands.parameter(
        description="The toon you want to know more about. Defaults to you.",
        default=None,
    ),
):
    try:
        engine = sqlalchemy.create_engine(config.db_url, echo=False)
        Session = sessionmaker(bind=engine)
        session = Session()

        # Reflect the tables
        Base = automap_base()
        Base.prepare(autoload_with=engine)

        # Mapped classes are now created with names by default
        # matching that of the table name.
        Census = Base.classes.census

        if toon is None:
            toon_owner = str(ctx.author.id)

        else:
            try:
                toon_data = (
                    session.query(Census).filter_by(name=toon.capitalize()).first()
                )
                toon_owner = toon_data.discord_id
            except Exception as e:
                await ctx.reply(f":x: No toon named `{toon.capitalize()}` was found.")
                return

        query = session.query(Census).filter_by(discord_id=str(toon_owner))
        toons = pd.read_sql(query.statement, query.session.bind)

        unique_discord_ids = toons["discord_id"].unique()

        if len(unique_discord_ids) != 1:
            raise ValueError(
                f"Expected exactly one unique discord_id, but found {len(unique_discord_ids)} unique discord_ids"
            )
        discord_id = unique_discord_ids[0]

        toons_list = create_toons_embed(ctx.guild.get_member(int(toon_owner)), toons)
        await ctx.reply(embed=toons_list)

    except Exception as e:
        await ctx.reply(content=f":x: An error occurred: {str(e)}")

    finally:
        session.close()

    return discord_id, toons


async def get_dkp_data(discord_id, toon=None):
    engine = sqlalchemy.create_engine(config.db_url, echo=False)
    dkp = pd.read_sql_table("dkp", con=engine)
    census = pd.read_sql_table("census", con=engine)

    if toon is not None:
        toon = toon.capitalize()
        toon_owner = census[census.name == toon][["discord_id"]]
        discord_id = toon_owner["discord_id"].iloc[0] if not toon_owner.empty else None

    # Fetch the DKP data associated with the found discord_id
    # make an explicit copy
    dkp_dict = dkp[dkp.discord_id == discord_id].copy()
    dkp_dict["current_dkp"] = dkp_dict["earned_dkp"] - dkp_dict["spent_dkp"]

    # Get a list of names that have a level of 46 and greater
    high_level_names_list = census[
        (census["level"] >= 46)
        & (census["discord_id"] == discord_id)
        & (census["status"] != "Dropped")
    ]["name"].tolist()

    if not high_level_names_list:
        high_level_names = None

    else:
        high_level_names_list = sorted([f"`{name}`" for name in high_level_names_list])

        high_level_names = list_to_oxford_comma(high_level_names_list)

    return discord_id, dkp_dict, high_level_names


def create_dkp_embed(user, dkp_dict, high_level_names):
    # Get the current time and convert it to a Unix timestamp
    current_time = datetime.datetime.now()
    unix_timestamp = int(current_time.timestamp())

    if high_level_names is None:
        description = f"<@{user}> cannot earn DKP without a character 46 or higher."
    else:
        description = f"<@{user}> can earn DKP using:\n {high_level_names}."

    embed = discord.Embed(
        title=f":dragon: Ex Astra DKP as of <t:{unix_timestamp}:R>",
        description=description,
        colour=discord.Colour.from_rgb(241, 196, 15),
    )

    embed.add_field(
        name=":arrow_up:️ Current DKP",
        value=f"```\n{dkp_dict['current_dkp'].to_string(index=False).strip()}\n```",
        inline=True,
    )

    embed.add_field(
        name=":moneybag: Total Earned",
        value=f"```\n{dkp_dict['earned_dkp'].to_string(index=False).strip()}\n```",
        inline=True,
    )

    return embed


@client.command(
    help="Displays the DKP of a character or the user if no character is specified. Usage: !dkp [toon]",
    brief="Displays the DKP of a character or the user",
)
async def dkp(
    ctx,
    toon: str = commands.parameter(
        description="Toon to display DKP for. Defaults to you.", default=None
    ),
):
    # ... (rest of your code)
    discord_id, dkp_dict, high_level_names = await get_dkp_data(
        str(ctx.author.id), toon
    )
    if not dkp_dict.empty:
        user = ctx.guild.get_member(int(discord_id)) if discord_id is not None else None
        dkp_embed = create_dkp_embed(discord_id, dkp_dict, high_level_names)
        await ctx.reply(embed=dkp_embed)
    else:
        await ctx.reply(content=":question: No census entry was found. Check `!toons`.")


@client.command(
    help='Processes raid logs and updates DKP. Can be a reply to posted logs. Usage: !logs <description> followed by logs or a reply to logs. \n\
        Example 1: "!logs raid" followed by pasted logs from /who. \n\
        Example 2: "!logs on time" in a reply to a message containing logs.',
    brief="Processes raid logs and updates DKP",
)
@commands.has_role("Officer")
async def logs(
    ctx,
    *,
    args: str = commands.parameter(
        description="The raid logs to process. Can be a reply to posted logs."
    ),
):

    census = pd.read_sql_query("SELECT * FROM census", con)
    dkp = pd.read_sql_query("SELECT * FROM dkp", con)
    raids = pd.read_sql_query("SELECT * FROM raids", con)

    # timestamp
    re1 = "(?<=^\[).*?(?=])"
    # level class
    re2 = "(?<=(?<!^)\[).*?(?=\])"
    # name
    re3 = "(?<=] )[^[]+?(?=[ <(])"
    # guild
    re4 = "(?<=<).*?(?=>)"

    raid = titlecase(args.splitlines()[0])

    # retrieve entire tables from SQLite
    # query how much this raid is worth
    modifier = raids.loc[raids["raid"] == raid, "modifier"]

    # is there a raid modifier and is it unique?
    if len(modifier.index) == 1:
        modifier = modifier.item()

    else:
        await ctx.reply(f"`{raid}` entry not found.\nAsk Rahmani")
        return

    # create empty lists of rejected players and seen players to prevent double counting
    seen_players = []
    rejected = []

    # if this is a reply to a message
    is_reply = check_reply(ctx)
    if is_reply == True:
        message = await ctx.channel.fetch_message(ctx.message.reference.message_id)
        args = message.content

    # records = args.splitlines()[1:]
    records = args.splitlines()

    for record in records:
        # if the record doesn't contain the line "<Ex Astra>", move on
        # very important in case the line is blank
        # if "<Ex Astra>" not in record:
        #     continue

        if len(record.strip()) == 0:
            continue

        if ("<" not in record or ">" not in record) and "ANONYMOUS" not in record:
            continue

        record = re.sub(" AFK ", "", record)
        record = re.sub(" LFG", "", record)
        record = re.sub(" <LINKDEAD>", "", record)

        line = re.compile("(%s|%s|%s|%s)" % (re1, re2, re3, re4)).findall(record)

        timestamp = line[0]

        timestamp = datetime.datetime.strptime(timestamp, "%a %b %d %H:%M:%S %Y")

        timestamp = datetime.datetime.strftime(timestamp, "%Y-%m-%d %H:%M:%S")

        level_class = line[1].split(" ")

        name = line[2]

        # guild = line[3]

        discord_id = census.loc[census["name"] == name, "discord_id"]

        if len(discord_id.index) == 1:
            discord_id = discord_id.item()

        # don't bother if the character isn't in the database linked to a discord
        else:
            rejected.append(record)
            continue

        # skip this round if the person is already here, prevent doubling
        if f"<@{discord_id}>" in seen_players:
            continue

        else:
            seen_players.append(f"<@{discord_id}>")

        if len(level_class) == 1:
            level = ""
            player_class = ""

        elif len(level_class) == 2:
            level = level_class[0]
            player_class = player_classes.loc[
                player_classes["class_name"] == level_class[1], "character_class"
            ].item()

        elif len(level_class) == 3:
            level = level_class[0]
            player_class = player_classes.loc[
                player_classes["class_name"] == f"{level_class[1]} {level_class[2]}",
                "character_class",
            ].item()

        sql_response = "INSERT INTO attendance (date, raid, name, discord_id, modifier) VALUES (?, ?, ?, ?, ?);"

        cur.execute(sql_response, (timestamp, raid, name, discord_id, modifier))

        if cur.rowcount == 1:
            con.commit()

        else:
            await ctx.reply(f"Something is wrong with the record: {record}")
            con.rollback()

        sql_response = (
            "UPDATE dkp SET earned_dkp = earned_dkp + ? WHERE discord_id == ?;"
        )
        cur.execute(sql_response, (modifier, discord_id))
        # await ctx.reply(sql_response)

        if cur.rowcount == 1:
            con.commit()

        else:
            await ctx.reply(
                f":exclamation:Something is wrong with the record: `{record}`"
            )
            con.rollback()

    if len(seen_players) > 0:
        await ctx.reply(
            f":dragon:{', '.join(seen_players)} earned `{modifier}` DKP for `{raid}` this hour."
        )
        await ctx.message.add_reaction("✅")

        if is_reply:
            await message.add_reaction("✅")

    if len(rejected) > 0:
        sep = "\n"

        rejected = sep.join(rejected)
        rejected = re.sub("```", "", rejected)
        # get rid of the extra triple backticks

        await ctx.reply(
            f":question:Some logs got rejected, since these players are not registered. ```\n{rejected}\n```"
        )
        await ctx.message.add_reaction("❌")

        if is_reply:
            await message.add_reaction("❌")


@client.command(
    help="Retrieves the sanctum DKP for a character or the user if no character is specified. Usage: !sanctum [toon]",
    brief="Retrieves the sanctum DKP",
)
async def sanctum(
    ctx,
    toon: str = commands.parameter(
        description="The character to retrieve the sanctum DKP for. Defaults to the user.",
        default=None,
    ),
):

    view = discord.ui.View(timeout=None)
    view.add_item(DeleteButton(ctx.author.id))
    view.add_item(DMButton(ctx.author.id))

    async with ctx.typing():

        st = os.stat("rap.html")
        mtime = st.st_mtime

        current_time = datetime.datetime.now()

        elapsed = current_time - datetime.datetime.fromtimestamp(mtime)
        elapsed = chop_microseconds(elapsed)

        # Convert the elapsed time to a Unix timestamp
        elapsed_timestamp = int((current_time - elapsed).timestamp())

        if elapsed >= datetime.timedelta(minutes=5):
            subprocess.call(["sh", "./aegis_readme.sh"])
            st = os.stat("rap.html")
            mtime = st.st_mtime
            current_time = datetime.datetime.now()
            elapsed = current_time - datetime.datetime.fromtimestamp(mtime)

        # Convert the elapsed time to a Unix timestamp
        elapsed_timestamp = int((current_time - elapsed).timestamp())

        # Use Discord's timestamp formatting syntax
        RAP_age = f"<t:{elapsed_timestamp}:R>."

        census = pd.read_sql_query("SELECT * FROM census", con)

        rap_totals = pd.read_html("rap.html")

        # Iterate over all tables
        for table in rap_totals:
            # Check if the table has the required columns
            if set(["Name", "Default"]).issubset(table.columns):
                # This is the table we want, so we break the loop
                rap_totals = table
                break
        else:
            # If no table was found, send a message and return
            await ctx.reply(
                "Unfortunatelly, no table with the required columns was found. Please alert an officer."
            )
            return

        # Now you can use rap_totals as before
        rap_totals = rap_totals[["Name", "Default"]]
        rap_totals["Name"] = rap_totals["Name"].str.capitalize()
        rap_totals.columns = ["Name", "RAP"]
        print(rap_totals.to_string())

        if toon == None:
            user_name = format(ctx.author.display_name)
            # discord_id = str(ctx.message.guild.get_member_named(user_name).id)
            discord_id = str(ctx.author.id)

        if toon != None:
            toon = toon.capitalize()
            user_name = format(toon)
            discord_id = census.loc[census["name"] == toon, "discord_id"].item()

        inner_merged = pd.merge(
            rap_totals, census, left_on="Name", right_on="name", how="inner"
        )

        inner_merged = inner_merged[["discord_id", "name", "RAP"]]

        inner_merged = inner_merged.sort_values(by=["name"])

        rap_totals = inner_merged.loc[inner_merged["discord_id"] == discord_id]

        rap_list = discord.Embed(
            # if username is the author, mention the author
            # if username is not the author, mention the username
            # title=f":shield: Sanctum DKP for "
            title=f":shield: Sanctum DKP as of {RAP_age}",
            description=f"<@{format(discord_id)}> has `{len(rap_totals)}` linked main{'s' if len(rap_totals) != 1 else ''} with DKP in [Sanctum](https://p99sanctum.com).",
            colour=discord.Colour.from_rgb(241, 196, 15),
        )

        # rap_list.add_field(
        #     name=f"Main Character{'s' if len(rap_totals) != 1 else ''}",
        #     value=f"`{len(rap_totals)}` linked main character{'s' if len(rap_totals) != 1 else ''} with DKP in [Sanctum](https://p99sanctum.com).",
        #     inline=False)

        if len(rap_totals) > 0:
            rap_list.add_field(
                name=":bust_in_silhouette: Name",
                value="```\n" + "\n".join(rap_totals.name.tolist()) + "\n```",
                inline=True,
            )

            rap_list.add_field(
                name=":arrow_up:️ DKP",
                value="```\n" + "\n".join(map(str, rap_totals.RAP.tolist())) + "\n```",
                inline=True,
            )

        await ctx.reply(embed=rap_list, view=view)


@client.command(
    help='Keep track of your inventory using the EverQuest Inventory Manager. Usage: !inventory while uploading up to ten inventory files at a time. These files can be retrieved using the output of the "/outputfile inventory" command in-game.',
    brief="Uploads inventory files to the database",
)
@commands.has_role("Member")
async def inventory(ctx):

    async with ctx.typing():

        # check if the message has attachments
        if len(ctx.message.attachments) < 1:
            await ctx.reply(
                ":x: Please attach at least one inventory file to your message. Inventory update failed."
            )
            return

        await ctx.message.delete()

        engine = create_engine(config.db_url)
        Base = automap_base()
        Base.prepare(autoload_with=engine)
        Census = Base.classes.census
        Inventory = Base.classes.inventory

        session = Session(engine)

        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        unix_timestamp = int(datetime.datetime.now().timestamp())

        toon_names = []  # List to store toon names
        response_messages = []  # List to store error messages
        response_messages.append(
            f"<@{str(ctx.author.id)}>  updated using inventory using `!inventory` <t:{unix_timestamp}:R> ago."
        )

        try:
            for attachment in ctx.message.attachments:
                try:
                    assert Path(attachment.filename).suffix == ".txt"
                    toon_name = Path(attachment.url).stem.split("-")[0]
                    inventory_keyword = Path(attachment.url).stem.split("-")[1]
                    assert inventory_keyword == "Inventory"

                except Exception as e:
                    response_messages.append(
                        f":x: `{attachment.filename}` is not a valid inventory file. Inventory update failed."
                    )
                    continue

                # check if the toon_name is in the census
                try:
                    toon_data = (
                        session.query(Census)
                        .filter_by(name=toon_name.capitalize())
                        .one()
                    )
                except Exception as e:
                    response_messages.append(
                        f":x: `{toon_name.capitalize()}` has not been registered. Inventory update failed."
                    )
                    continue

                # check if the toon_name is owned by the user
                try:
                    assert toon_data.discord_id == str(ctx.author.id)
                except Exception as e:
                    response_messages.append(
                        f":x: `{toon_name.capitalize()}` is not owned by author. Inventory update not allowed."
                    )
                    continue

                # parse the inventory file
                req = Request(attachment.url, headers={"User-Agent": "Mozilla/5.0"})
                stream = urlopen(req).read()
                inventory_list = pd.read_csv(
                    io.StringIO(stream.decode("utf-8")), sep="\t"
                )

                inventory_list = inventory_list.rename(
                    columns={
                        "Location": "location",
                        "Name": "name",
                        "ID": "eq_item_id",
                        "Count": "quantity",
                        "Slots": "slots",
                    }
                )

                inventory_list["toon"] = toon_name
                inventory_list["time"] = current_time

                session.query(Inventory).filter(Inventory.toon == toon_name).delete()
                session.commit()

                inventory_data = inventory_list.to_dict(orient="records")

                session.bulk_insert_mappings(Inventory, inventory_data)
                session.commit()

                toon_names.append(toon_name)

        except:
            await ctx.send(f":x: An error occurred. Inventory update failed.")

        finally:
            toon_names_list = sorted([f"`{name}`" for name in toon_names])
            toon_names_pretty = list_to_oxford_comma(toon_names_list)

            response_messages.append(
                f":white_check_mark: {toon_names_pretty} had updated inventories."
            )

            # send all messages at once
            await ctx.send("\n".join(response_messages))
            session.close()


@client.command(
    help="Helps you find your stuff. Usage: !wheresmy [stuff]",
    brief="Where's my stuff?",
)
@commands.has_role("Member")
async def wheresmy(ctx, *, stuff):

    view = discord.ui.View(timeout=None)
    view.add_item(DeleteButton(ctx.author.id))
    view.add_item(DMButton(ctx.author.id))

    async with ctx.typing():

        engine = create_engine(config.db_url)
        Base = automap_base()
        Base.prepare(autoload_with=engine)
        Census = Base.classes.census
        Inventory = Base.classes.inventory
        Trash = Base.classes.trash

        session = Session(engine)

        # retrieve list of names from Census where discord_id matches the user
        try:
            toon_names = (
                session.query(Census.name)
                .filter_by(discord_id=str(ctx.author.id))
                .all()
            )
            toon_names = [name[0] for name in toon_names]  # Extract names from tuples
            trash_items = session.query(Trash.name).all()
            trash_items = [name[0] for name in trash_items]  # Extract names from tuples

        except Exception as e:
            await ctx.reply(f":x: An error occurred. {e}")
            return

        # retrieve list of items from Inventory where toon matches the user
        try:
            query = session.query(
                Inventory.name, Inventory.toon, Inventory.location, Inventory.quantity
            ).filter(
                sqlalchemy.and_(
                    Inventory.toon.in_(toon_names),
                    ~Inventory.name.in_(trash_items),
                    Inventory.name.ilike(f"%{stuff}%"),
                )
            )
            items = pd.read_sql(query.statement, query.session.bind)
            items = items.sort_values("name")

        except Exception as e:
            await ctx.reply(f":x: An error occurred. {e}")
            return

        # check if the search term is in the items
        if items.empty:
            await ctx.reply(
                f":x: `{titlecase(stuff)}` was not found in inventory for <@{ctx.author.id}>",
                view=view,
            )

            session.close()
            return

        # Send the embed with the image

        file, path = table_to_file(items)

        view.response_message = await ctx.reply(
            f":mag: Found `{len(items)}` item(s) matching `{titlecase(stuff)}` in inventory for <@{ctx.author.id}>.",
            file=file,
            view=view,
        )

        # Close the session
        session.close()

        os.remove(path)


@client.command(
    help="Helps you find stuff on bankers. Usage: !find [stuff]",
    brief="Looking for something on a banker?",
)
@commands.has_role("Member")
async def find(ctx, *, stuff):

    view = discord.ui.View(timeout=None)
    view.add_item(DeleteButton(ctx.author.id))
    view.add_item(DMButton(ctx.author.id))

    async with ctx.typing():

        engine = create_engine(config.db_url)
        Base = automap_base()
        Base.prepare(autoload_with=engine)
        Bank = Base.classes.bank
        Trash = Base.classes.trash

        session = Session(engine)

        # retrieve list of names from Census where discord_id matches the user
        try:
            trash_items = session.query(Trash.name).all()
            trash_items = [name[0] for name in trash_items]  # Extract names from tuples

        except Exception as e:
            await ctx.reply(f":x: An error occurred. {e}")
            return

        # retrieve list of items from Inventory where toon matches the user
        try:
            query = session.query(
                Bank.name, Bank.banker, Bank.location, Bank.quantity
            ).filter(
                sqlalchemy.and_(
                    ~Bank.name.in_(trash_items), Bank.name.ilike(f"%{stuff}%")
                )
            )
            items = pd.read_sql(query.statement, query.session.bind)
            items = items.sort_values("name")

            # arrange items by banker, then name, location
            items = items.sort_values(
                ["banker", "name", "location"], ascending=[True, True, True]
            )

            # convert quantity to string
            items["quantity"] = items["quantity"].astype(str)

            # get unique bankers
            unique_bankers = items["banker"].unique()

            # create a new DataFrame to hold the items with section breaks
            new_items = pd.DataFrame()

            # iterate over unique bankers
            for i, banker in enumerate(unique_bankers):
                # get the items for this banker
                banker_items = items[items["banker"] == banker]

                # append the items to the new DataFrame
                new_items = pd.concat([new_items, banker_items], ignore_index=True)

                # if this is not the last banker, add a section break
                if i < len(unique_bankers) - 1:
                    # calculate the maximum length of each column
                    max_length_banker = banker_items["banker"].str.len().max()
                    max_length_name = banker_items["name"].str.len().max()
                    max_length_location = banker_items["location"].str.len().max()
                    max_length_quantity = banker_items["quantity"].str.len().max()

                    # create a DataFrame for the section break
                    section_break = pd.DataFrame(
                        [
                            [
                                (" " * max_length_banker),
                                (" " * max_length_name),
                                (" " * max_length_location),
                                (" " * max_length_quantity),
                            ]
                        ],
                        columns=["banker", "name", "location", "quantity"],
                    )

                    # append the section break to the new DataFrame
                    new_items = pd.concat([new_items, section_break], ignore_index=True)

            # replace the original items DataFrame with the new one
            items = new_items
        except Exception as e:
            await ctx.reply(f":x: An error occurred. {e}")
            return

        # check if the search term is in the items
        if items.empty:
            view.response_message = await ctx.reply(
                f":x: `{titlecase(stuff)}` was not found on any banker.\nSearch performed by <@{ctx.author.id}>",
                view=view,
            )
            return

        # Send the embed with the image

        try:
            file, path = table_to_file(items)
        except Exception as e:
            await ctx.reply(f":x: An error occurred. {e}")
            return

        view.response_message = await ctx.reply(
            f":mag: Found `{len(items)}` item(s) matching `{titlecase(stuff)}` in bankers inventory.\n Search performed by <@{ctx.author.id}>.",
            file=file,
            view=view,
        )

        # Close the session
        session.close()

        os.remove(path)


@client.command()
@commands.has_role("Treasurer")
async def bank(ctx):

    if ctx.message.attachments:
        attachment = ctx.message.attachments[0]
    else:
        await ctx.reply(
            "No attachment found in the message. Try attaching a banker's inventory with `!bank`."
        )
        return

    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    engine = sqlalchemy.create_engine(config.db_url, echo=False)

    attachment = ctx.message.attachments[0]
    banker_name = Path(attachment.url).stem.split("-")[0]
    inventory_keyword = Path(attachment.url).stem.split("-")[1]

    await ctx.reply(f"Parsing `{inventory_keyword}` for `{banker_name}`")

    old_data = pd.read_sql(
        "SELECT name, quantity FROM bank WHERE Banker = ?",
        engine,
        params=[(banker_name,)],
    )

    req = Request(attachment.url, headers={"User-Agent": "Mozilla/5.0"})
    stream = urlopen(req).read()
    inventory = pd.read_csv(io.StringIO(stream.decode("utf-8")), sep="\t")

    inventory = inventory.rename(
        columns={
            "Location": "location",
            "Name": "name",
            "ID": "eq_item_id",
            "Count": "quantity",
            "Slots": "slots",
        }
    )

    inventory.insert(0, "Banker", banker_name)

    inventory.insert(0, "Time", current_time)

    # Sum up the quantities for each item in the old data
    old_data = old_data.groupby("name")["quantity"].sum().reset_index()

    # Sum up the quantities for each item in the new data
    new_data = inventory.groupby("name")["quantity"].sum().reset_index()

    # Merge the old and new data on the item name, keeping all items
    merged_data = pd.merge(
        old_data, new_data, on="name", how="outer", suffixes=("_old", "_new")
    )

    # Calculate the difference in quantity for each item
    merged_data["quantity_diff"] = (
        merged_data["quantity_new"] - merged_data["quantity_old"]
    )

    # Replace NaN values with 0 in 'quantity_old' and 'quantity_new' columns and convert to integer
    merged_data["quantity_old"] = merged_data["quantity_old"].fillna(0)
    merged_data["quantity_new"] = merged_data["quantity_new"].fillna(0)

    # Downcast the data
    merged_data = merged_data.convert_dtypes()

    # Calculate the difference in quantity for each item
    merged_data["quantity_diff"] = (
        merged_data["quantity_new"] - merged_data["quantity_old"]
    )

    merged_data["quantity_diff"] = merged_data["quantity_diff"]

    merged_data = merged_data[["name", "quantity_old", "quantity_new", "quantity_diff"]]

    # filter where the difference is not zero
    merged_data = merged_data[merged_data["quantity_diff"] != 0]

    sql_response = "DELETE FROM bank WHERE banker == ?"

    cur.execute(sql_response, (banker_name,))
    con.commit()

    inventory.to_sql("bank", engine, if_exists="append", index=False)

    if merged_data.empty:
        await ctx.reply(
            f"No changes detected for `{banker_name}`. But thanks for the update!"
        )

    else:
        await ctx.reply(f"Changes detected for `{banker_name}`. Here's the summary.")

        # rename to "Item", "Old Quantity", "New Quantity", "Difference"
        merged_data.columns = ["Item", "Old Quantity", "New Quantity", "Difference"]

        # Convert the differences to a string
        diff_string = merged_data.to_string(index=False)

        # Split the string into lines
        lines = diff_string.split("\n")

        # Add a line separator after the header
        lines.insert(1, "-" * len(lines[0]))

        # Join the lines back into a string
        diff_string = "\n".join(lines)

        diff_strings = chunk_strings(diff_string)

        for diff_string in diff_strings:
            await ctx.reply(f"```{diff_string}```")


@client.command()
async def banktotals(ctx, stuff=None):

    view = discord.ui.View(timeout=None)
    view.add_item(DeleteButton(ctx.author.id))
    view.add_item(DMButton(ctx.author.id))

    engine = sqlalchemy.create_engine(config.db_url, echo=False)
    bank = pd.read_sql_table("bank", con=engine)
    trash = pd.read_sql_table("trash", con=engine)

    # if stuff is None, then show everything
    if stuff is None:
        bank = bank[~bank["name"].isin(trash["name"])]
        banktotals = (
            bank.groupby(["name"])["quantity"].sum().reset_index()[["quantity", "name"]]
        )

    # this query should be case insensitive
    elif stuff is not None:
        if stuff.lower() == "empty":
            banktotals = (
                bank[
                    (bank["name"].str.contains(stuff, case=False))
                    & (bank["location"].str.contains("-", na=False))
                ]
                .groupby(["banker"])["name"]
                .count()
                .reset_index()[["name", "banker"]]
            )
            banktotals.columns = ["space in bags", "banker"]
        else:
            banktotals = (
                bank[bank["name"].str.contains(stuff, case=False)]
                .groupby(["name"])["quantity"]
                .sum()
                .reset_index()[["quantity", "name"]]
            )
            # arrange by quantity descending, then name ascending
            banktotals = banktotals.sort_values(
                ["quantity", "name"], ascending=[False, True]
            )

            # check if the user's search is the keyword "empty", case insensitive
            # return a list of how many times the name == "empty" for each banker on the bank table, ignoring quantity
    try:
        file, path = table_to_file(banktotals)
    except Exception as e:
        await ctx.reply(f":x: An error occurred. {e}")
        return

    view.response_message = await ctx.reply(
        f":moneybag:Here's the bank totals.\nRequested by <@{ctx.author.id}>.",
        file=file,
        view=view,
    )

    os.remove(path)


@client.command()
async def bidhistory(ctx):

    view = discord.ui.View(timeout=None)
    view.add_item(DeleteButton(ctx.author.id))
    view.add_item(DMButton(ctx.author.id))

    engine = sqlalchemy.create_engine(config.db_url, echo=False)
    # discord_id = str(ctx.message.guild.get_member_named(format(ctx.author)).id)
    discord_id = str(ctx.author.id)
    items = pd.read_sql_table("items", con=engine)
    items = items.loc[items["discord_id"] == discord_id]
    items = items[["name", "date", "item", "dkp_spent"]]

    # wherever dkp_spent is nan, conver to 0
    items["dkp_spent"] = items["dkp_spent"].fillna(0)

    items["dkp_spent"] = items["dkp_spent"].astype(int)
    # items = items.groupby(['name'])['quantity'].sum().reset_index()[['quantity', 'name']]

    try:
        file, path = table_to_file(items)
    except Exception as e:
        await ctx.reply(f":x: An error occurred. {e}")
        return

    view.response_message = await ctx.reply(
        f":moneybag: Here's your bid history.\nRequested by <@{ctx.author.id}>.",
        file=file,
        view=view,
    )

    os.remove(path)


@client.command()
async def dkphistory(ctx):

    view = discord.ui.View(timeout=None)
    view.add_item(DeleteButton(ctx.author.id))
    view.add_item(DMButton(ctx.author.id))

    engine = sqlalchemy.create_engine(config.db_url, echo=False)
    # discord_id = str(ctx.message.guild.get_member_named(format(ctx.author)).id)
    discord_id = str(ctx.author.id)
    attendance = pd.read_sql_table("attendance", con=engine)
    attendance = attendance.loc[attendance["discord_id"] == discord_id]
    attendance = attendance[["name", "date", "raid", "modifier"]]
    # wherever dkp_spent is nan, conver to 0
    attendance["modifier"] = attendance["modifier"].fillna(0)

    attendance["modifier"] = attendance["modifier"].astype(int)
    # items = items.groupby(['name'])['quantity'].sum().reset_index()[['quantity', 'name']]

    try:
        file, path = table_to_file(attendance)
    except Exception as e:
        await ctx.reply(f":x: An error occurred. {e}")
        return

    view.response_message = await ctx.reply(
        f":moneybag: Here's your DKP earnings history.\nRequested by <@{ctx.author.id}>.",
        file=file,
        view=view,
    )

    os.remove(path)


@client.command()
async def who(ctx, level, optional_max_level=None, player_class=None):
    level, max_level, player_class = await validate_and_process_input(
        ctx, level, optional_max_level, player_class
    )
    if level is None:
        return
    matching_toons = fetch_matching_toons(level, max_level, player_class)
    if len(matching_toons) == 0:
        await reply_no_matching_toon(ctx, level, max_level, player_class)
    else:
        await reply_matching_toons(ctx, matching_toons, level, max_level, player_class)


async def send_split_message(ctx, message):
    max_length = 2000
    messages = [message[i : i + max_length] for i in range(0, len(message), max_length)]
    for msg in messages:
        await ctx.send(msg)


async def validate_and_process_input(ctx, level, optional_max_level, player_class):
    try:
        level = int(level)
    except ValueError:
        ctx.reply(f"{level} is not a valid level.")
        return None, None, None

    if player_class is None:  # Exact mode
        max_level = level
        player_class = optional_max_level
    else:  # Range mode
        try:
            max_level = int(optional_max_level)
        except ValueError:
            ctx.reply(f"{optional_max_level} is not a valid level.")
            return None, None, None

        if level > max_level:
            ctx.reply("Invalid level range.")
            return None, None, None

    if not 1 <= level <= 60:
        ctx.reply("You think you're funny, huh?")
        return None, None, None

    return (
        level,
        max_level,
        await get_player_class(player_class) if player_class is not None else None,
    )


def fetch_matching_toons(level, max_level, player_class):
    Base = automap_base()
    engine = create_engine(config.db_url)
    Base.prepare(autoload_with=engine)

    Attendance = Base.classes.attendance
    Census = Base.classes.census

    session = Session(engine)

    toon_q = (
        session.query(Census)
        .filter(Census.character_class == player_class)
        .filter(Census.level >= level)
        .filter(Census.level <= max_level)
        .filter(Census.status != "Dropped")
        .join(Attendance, Attendance.discord_id == Census.discord_id)
        .having(func.max(Attendance.date))
        .group_by(Attendance.discord_id)
        .order_by(Attendance.date.desc())
    )

    return pd.read_sql(toon_q.statement, toon_q.session.bind)[
        ["name", "discord_id", "level"]
    ]


async def reply_no_matching_toon(ctx, level, max_level, player_class):
    if max_level == level:
        await ctx.reply(f"There were no level {level} {player_class}s found.")
    else:
        await ctx.reply(
            f"There were no level {level} to {max_level} {player_class}s found."
        )


async def reply_matching_toons(ctx, matching_toons, level, max_level, player_class):
    guild = ctx.guild
    names = []
    mentions = []
    left_server_names = []

    for _, row in matching_toons.iterrows():
        name = row["name"]
        discord_id = row["discord_id"]
        toon_level = row["level"]
        member = guild.get_member(int(discord_id))

        if member is not None:
            names.append(name)
            if toon_level == max_level or toon_level == level:
                mentions.append((discord_id, toon_level))
            else:
                mentions.append((discord_id, f"{toon_level}-{max_level}"))
        else:
            left_server_names.append(name)

    embed = discord.Embed(
        title=f":white_check_mark: Registered level {level} to {max_level} {player_class}s",
        description="Sorted by most recently earned DKP on any character.",
        colour=discord.Colour.from_rgb(241, 196, 15),
    )

    embed.add_field(
        name=":bust_in_silhouette: Name",
        value="".join([f"`{name}`\n" for name in names]),
        inline=True,
    )

    embed.add_field(
        name=":busts_in_silhouette: Discord",
        value="".join(
            [
                f"`{' ' if toon_level < 10 else ''}{mention[1]}`<@{mention[0]}>\n"
                for mention in mentions
            ]
        ),
        inline=True,
    )

    if left_server_names:
        left_server_names_str = ", ".join(left_server_names)
        embed.set_footer(
            text=f"The following characters appear not to belong to this server anymore:\n{left_server_names_str}"
        )

    await ctx.reply(embed=embed)


@client.command()
async def claim(ctx, toon):

    toon = toon.capitalize()
    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    discord_id = str(ctx.author.id)

    Base = automap_base()
    engine = create_engine(config.db_url)
    Base.prepare(autoload_with=engine)
    Census = Base.classes.census
    session = Session(engine)

    claimed_toon = session.query(Census).filter(Census.name == toon).one()

    old_owner = claimed_toon.discord_id

    if claimed_toon.status == "Bot" or claimed_toon.status == "Dropped":

        claimed_toon.discord_id = discord_id

        claimed_toon.time = current_time

        session.commit()

        await ctx.reply(
            f":white_check_mark:<@{discord_id}> has taken control of `{toon}` from <@{old_owner}>."
        )

    if claimed_toon.status != "Bot" and claimed_toon.status != "Dropped":

        await ctx.reply(
            f":exclamation:`{toon}` can only change ownership if <@{old_owner}> changes status using `!bot` or `!drop`.\nTry `!drop {toon}` or `!bot {toon}`."
        )


@client.command()
@commands.has_role("DUMMY")
async def event(ctx):
    return


@client.event
async def on_command_error(ctx, error):

    print(f"Error author:  {ctx.author}")
    print(f"Error message: {ctx.message.content}")

    if isinstance(error, CommandNotFound):
        await ctx.reply(f":question: Command not found \nSee `!help`")
        return

    if isinstance(error, commands.NoPrivateMessage):
        await ctx.reply(f":question: This command must be used in a public channel")
        return

    if isinstance(error, commands.MissingRequiredArgument) or isinstance(
        error, commands.BadArgument
    ):
        command = ctx.message.content.split()[0]
        await ctx.reply(
            f":question: Missing some information. \nSee `!help {command[1:]}`"
        )
        return

    if isinstance(error, commands.MissingRole):
        await ctx.reply(
            f":question: Command reserved for a different role \nSee `!help`"
        )
        return

    raise error


###########


async def remove_item_from_bank(id):
    Base = automap_base()
    engine = create_engine(config.db_url)
    Base.prepare(autoload_with=engine)
    Bank = Base.classes.bank
    session = Session(engine)

    try:
        item_to_delete = session.query(Bank).filter(Bank.id == int(id)).one()
        session.delete(item_to_delete)
        session.commit()
        return True
    except Exception as e:
        print(f"Error removing item from bank: {e}")
        return False


def build_sell_embed(name, banker, banker_results):
    search_embed = discord.Embed(
        title=f":gem: Treasury Query for `{name}`",
        description=f"Found on `{banker}`",
        colour=discord.Colour.from_rgb(241, 196, 15),
    )

    search_embed.add_field(
        name="Item Characteristics",
        value=f"{len(banker_results)} matching item(s) found.",
        inline=False,
    )

    search_embed.add_field(
        name=":1234: ID",
        value="```\n" + "\n".join(banker_results.id.astype(str).tolist()) + "\n```",
        inline=True,
    )

    search_embed.add_field(
        name=":bust_in_silhouette: Item",
        value="```\n" + "\n".join(banker_results.name.tolist()) + "\n```",
        inline=True,
    )

    search_embed.add_field(
        name=":arrow_up:️ Quantity",
        value="```\n" + "\n".join(map(str, banker_results.quantity.tolist())) + "\n```",
        inline=True,
    )

    search_embed.set_footer(text="Fetched at local time")
    search_embed.timestamp = datetime.datetime.now(pytz.timezone("US/Pacific"))

    return search_embed


@client.command()
async def ask(ctx, *, question):
    print(f"question: {question}")
    async with ctx.typing():
        # Splitting the input text into question and additional arguments
        parts = question.split("--")  # Using '--' as an arbitrary delimiter
        question = parts[0].strip()

        kwargs = {}
        if len(parts) > 1:
            # Assuming additional arguments are formatted as 'key=value'
            for arg in parts[1:]:
                key_value = arg.split("=")
                if len(key_value) == 2:
                    # Split the values by comma and store them in a list
                    values = [value.strip() for value in key_value[1].split(",")]
                    # Always store the values as a list
                    kwargs[key_value[0].strip()] = values

        # Call ask_async with parsed kwargs
        response = await ask_async(question, **kwargs)
        chunks = chunk_strings(response)

        for chunk in chunks:
            await ctx.reply(chunk)


async def async_openai_call(messages):
    async with aiohttp.ClientSession() as session:
        headers = {
            "Authorization": f"Bearer {config.openai_token}",
            "Content-Type": "application/json",
        }
        data = json.dumps(
            {
                "model": "gpt-3.5-turbo",  # Specify the model here
                "messages": messages,  # List of messages
                # No need for max_tokens or temperature here
            }
        )
        async with session.post(
            "https://api.openai.com/v1/chat/completions", headers=headers, data=data
        ) as resp:
            return await resp.json()


client.run(config.discord_token)
