#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Imports
import datetime
import io
import json
import os
import re
import subprocess
import tempfile
from difflib import get_close_matches as gcm
from pathlib import Path
from urllib.request import Request, urlopen

import psycopg2
from embed_assisted_questions import ask_async
import config

import aiohttp
import dataframe_image as dfi
import discord
import numpy as np
import pandas as pd
import pytz
import sqlalchemy
from sqlalchemy import Column, Integer, String, DateTime, create_engine
from sqlalchemy.orm import Session, declarative_base

from discord.ext import commands
from discord.ext.commands import CommandNotFound
from openai import OpenAI
from PIL import Image
from sqlalchemy import Column, create_engine, func, update, desc
from sqlalchemy.ext.automap import automap_base
from sqlalchemy.orm import Session, sessionmaker
from tabulate import tabulate
from titlecase import titlecase


from config import PGUSER, PGPASS, PGHOST, PGDATA

POSTGRES_URL = f"postgresql://{PGUSER}:{PGPASS}@{PGHOST}:5432/{PGDATA}"


def table_to_file(pandas_table):
    pandas_table.columns = pandas_table.columns.str.title()

    if len(pandas_table) > 10:
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


def check_send(ctx):
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


con = psycopg2.connect(dbname=PGDATA, user=PGUSER, password=PGPASS, host=PGHOST)
cur = con.cursor()


def close_connection():
    global con
    if con is not None:
        con.close()


player_classes = pd.read_sql_query("SELECT * FROM class_definitions", POSTGRES_URL)
raids = pd.read_sql_query("SELECT * FROM raids", POSTGRES_URL)


class DeleteButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"delete:user:(?P<id>[0-9]+):original:(?P<original_id>[0-9]+)",
):
    def __init__(self, user_id: int, original_message_id: int):
        super().__init__(
            discord.ui.Button(
                label="Delete",
                style=discord.ButtonStyle.danger,
                custom_id=f"delete:user:{user_id}:original:{original_message_id}",
            )
        )
        self.user_id = user_id
        self.original_message_id = original_message_id

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match: re.Match[str],
    ):
        user_id = int(match["id"])
        original_message_id = int(match["original_id"])
        return cls(user_id, original_message_id)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "You do not have permission to delete this message.", ephemeral=True
            )
            return

        original_message = await interaction.channel.fetch_message(
            self.original_message_id
        )
        await original_message.delete()
        await interaction.message.delete()
        await interaction.response.send_message(
            ":wastebasket: Interaction has been deleted!", ephemeral=True
        )


class DMButton(
    discord.ui.DynamicItem[discord.ui.Button], template=r"DM:user:(?P<id>[0-9]+)"
):
    def __init__(self, user_id: int) -> None:
        super().__init__(
            discord.ui.Button(
                label="DM",
                style=discord.ButtonStyle.primary,
                custom_id=f"DM:user:{user_id}",
            )
        )
        self.user_id: int = user_id

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

    # Removed the interaction_check method to handle permission check within callback

    async def callback(self, interaction: discord.Interaction) -> None:
        # Check if the user is authorized to use the DM button
        if interaction.user.id != self.user_id:
            # If not authorized, send a customized error message
            await interaction.response.send_message(
                "This doesn't seem to be your message to DM... :thinking:",
                ephemeral=True,
            )
            return

        # Proceed with the intended action if the user is authorized
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
        await interaction.followup.send("DM sent!", ephemeral=True)


class PersistentViewBot(commands.Bot):
    def __init__(self):

        intents = discord.Intents.all()
        intents.message_content = True
        intents.members = True

        super().__init__(
            command_prefix=config.PREFIX, intents=intents, case_insensitive=True
        )

    async def setup_hook(self) -> None:
        self.add_dynamic_items(DeleteButton)
        self.add_dynamic_items(DMButton)

    async def on_ready(self):
        print(f"Logged in as {self.user} (ID: {self.user.id})")
        print("------")


client = PersistentViewBot()

openai_client = OpenAI(api_key=config.OPENAI_API_KEY)


@client.check
async def globally_block_dms(ctx):
    return ctx.guild is not None or ctx.author.id == 816198379344232488


@client.command(
    help="Pings the bot to check if it's online and respond with round-trip latency.",
    brief="Pings the bot to check if it's online.",
)
async def ping(ctx):
    # Send a message and store the sent message object
    sent = await ctx.send(":arrow_right: Pinging...")
    # Calculate the roundtrip latency
    latency = round((sent.created_at - ctx.message.created_at).total_seconds() * 1000)
    # Edit the sent message with the latency
    await sent.edit(content=f":arrows_clockwise: Roundtrip latency: {latency}ms")


@client.command(help="Apply to join Ex Astra.", brief="Apply to join Ex Astra.")
async def apply(ctx):

    # discord_id = ctx.message.guild.get_member_named(format(ctx.author)).id
    discord_id = str(ctx.author.id)
    channel = client.get_channel(988260644056879194)  # census chat
    member = await ctx.guild.fetch_member(discord_id)
    applicant_role = ctx.guild.get_role(990817141831901234)  # come back to this

    await member.add_roles(applicant_role)

    await ctx.send(
        f"Attention <@&849337092324327454> and <@&906952889287708773>, <@{discord_id}>, has submitted an application."
    )


@client.command(
    help="Deducts a specified amount from a user's total.",
    brief="Deducts a specified amount from a user's total",
)
@commands.has_any_role("Officer", "Probationary Officer", "Lootmaster")
async def deduct(
    ctx,
    amount: int = commands.parameter(description="The amount to deduct."),
    name: str = commands.parameter(description="The name of the toon."),
    *,
    args: str = commands.parameter(description="The reason/item for the deduction."),
):

    # # Initialize engine and session as before
    # engine = create_engine(POSTGRES_URL, echo=False)
    # session = Session(bind=engine)

    engine = create_engine(POSTGRES_URL, echo=False)
    Session = sessionmaker(bind=engine)
    session = Session()
    DBase = declarative_base()

    class Items(DBase):
        __tablename__ = "items"
        id = Column(Integer, primary_key=True)
        name = Column(String)
        date = Column(DateTime)
        item = Column(String)
        dkp_spent = Column(Integer)
        discord_id = Column(String)

    class Dkp(DBase):
        __tablename__ = "dkp"
        id = Column(Integer, primary_key=True)
        discord_name = Column(String)
        earned_dkp = Column(Integer)
        spent_dkp = Column(Integer)
        date_joined = Column(DateTime)
        discord_id = Column(String)

    class Census(DBase):
        __tablename__ = "census"
        id = Column(Integer, primary_key=True)
        name = Column(String)
        level = Column(Integer)
        character_class = Column(String)
        discord_id = Column(String)
        status = Column(String)
        time = Column(DateTime)

    async with ctx.typing():

        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        name = name.capitalize()

        try:
            # Query for the discord_id from the census table where the name matches
            discord_id_result = (
                session.query(Census.discord_id)
                .filter(Census.name == name)
                .one_or_none()
            )

            if discord_id_result is None:
                return await ctx.send(
                    f":exclamation:No character named `{name}` was found."
                )

            discord_id = discord_id_result[0]

            # Query for earned_dkp and spent_dkp from the dkp table where the discord_id matches
            dkp_record = session.query(Dkp).filter(Dkp.discord_id == discord_id).one()
            current_dkp = dkp_record.earned_dkp - dkp_record.spent_dkp

            if current_dkp >= amount:
                # Insert into items
                new_item = Items(
                    name=name,
                    date=current_time,
                    item=titlecase(args),
                    dkp_spent=amount,
                    discord_id=discord_id,
                )
                session.add(new_item)

                # Update dkp
                dkp_record.spent_dkp += amount

                # Commit the transaction
                session.commit()
                await ctx.send(
                    f":white_check_mark:<@{discord_id}> spent `{amount}` DKP on `{titlecase(args)}` for `{name.capitalize()}`!"
                )
            else:
                await ctx.send(
                    f":exclamation:`{amount}` is greater than `{name.capitalize()}`'s current total of `{current_dkp}` DKP. No action taken."
                )

        except Exception as e:
            # Rollback the transaction in case of error
            session.rollback()
            await ctx.send(
                f":question: <@816198379344232488> Something weird happened. `Error: {e}`"
            )
        finally:
            # Close the session
            session.close()


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
    engine = create_engine(POSTGRES_URL, echo=False)
    Session = sessionmaker(bind=engine)
    session = Session()
    Base = automap_base()
    Base.prepare(autoload_with=engine)
    Attendance = Base.classes.attendance
    Dkp = Base.classes.dkp
    Census = Base.classes.census

    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    name = name.capitalize()

    try:
        # Query for the discord_id from the census table where the name matches
        discord_id_result = (
            session.query(Census.discord_id).filter(Census.name == name).one_or_none()
        )

        if discord_id_result is None:
            return await ctx.send(
                f":exclamation:No character named `{name}` was found."
            )

    except Exception as e:
        return await ctx.send(
            f"An error occurred while getting the discord id: {str(e)}"
        )

    discord_id = discord_id_result[0]

    # Query for earned_dkp and spent_dkp from the dkp table where the discord_id matches
    dkp_result = (
        session.query(Dkp.earned_dkp, Dkp.spent_dkp)
        .filter(Dkp.discord_id == discord_id)
        .one()
    )
    earned_dkp, spent_dkp = dkp_result
    current_dkp = earned_dkp - spent_dkp

    # Start a new transaction
    try:
        # Insert into attendance
        new_attendance = Attendance(
            raid=titlecase(args),
            name=name,
            date=current_time,
            discord_id=discord_id,
            modifier=amount,
        )
        session.add(new_attendance)

        # Update dkp
        dkp_record = session.query(Dkp).filter_by(discord_id=discord_id).one()
        dkp_record.earned_dkp += amount

        # Commit the transaction
        session.commit()
        await ctx.send(
            f":white_check_mark:<@{discord_id}> earned `{amount}` DKP for `{titlecase(args)}` on `{name}`!"
        )
    except Exception as e:
        # Rollback the transaction in case of error
        session.rollback()
        await ctx.send(
            f":question: <@816198379344232488> Something weird happened. `Error: {e}`"
        )
    finally:
        # Close the session
        session.close()


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
    return pd.read_sql_query("SELECT * FROM census", POSTGRES_URL)


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
    cur.execute("SELECT * FROM census WHERE name = %s;", (toon.capitalize(),))
    rows = cur.fetchall()
    return rows


def check_discord_exists(discord_id):
    cur.execute("SELECT * FROM dkp WHERE discord_id = %s;", (discord_id,))
    discord_exists = cur.fetchall()
    return len(discord_exists) > 0


def add_user_to_dkp(user_name, discord_id, current_time):
    cur.execute(
        "INSERT INTO dkp (discord_name, earned_dkp, spent_dkp, date_joined, discord_id) VALUES (%s, 5, 0, %s, %s);",
        (user_name, current_time, discord_id),
    )
    con.commit()


def update_census(toon, status, level, player_class, current_time):
    if level is None:
        cur.execute(
            "UPDATE census SET status = %s, time = %s WHERE name = %s;",
            (status.capitalize(), current_time, toon.capitalize()),
        )
    elif player_class is None:
        cur.execute(
            "UPDATE census SET status = %s, level = %s, time = %s WHERE name = %s;",
            (status.capitalize(), level, current_time, toon.capitalize()),
        )
    else:
        cur.execute(
            "UPDATE census SET status = %s, level = %s, character_class = %s, time = %s WHERE name = %s,",
            (status.capitalize(), level, player_class, current_time, toon.capitalize()),
        )
    con.commit()


def insert_to_census(toon, level, player_class, discord_id, status, current_time):
    cur.execute(
        "INSERT INTO census (name, level, character_class, discord_id, status, time) VALUES (%s, %s, %s, %s, %s, %s);",
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
            await ctx.send(
                f":crossed_swords: Hail, `{toon.capitalize()}`! "
                f"In the realms of Norrath, levels range from `1` to `60`. "
                f"Adjust your compass and try again!"
            )
            return

    # capitalize toon name
    toon = toon.capitalize()

    if discord_id is None:
        try:
            discord_id = await get_discord_id(ctx, user_name, discord_id)
        except Exception as e:
            await ctx.send(f"An error occurred while getting the discord id: {str(e)}")
            return
    if not await check_allowed_channels(ctx):
        await ctx.send("This action must be performed on <#851549677815070751>.")
        return

    try:
        census = get_census()
    except Exception as e:
        await ctx.send(f"An error occurred while getting the census: {str(e)}")
        return

    if player_class is not None:
        try:
            player_class = await get_player_class(player_class)
        except Exception as e:
            await ctx.send(
                f"An error occurred while getting the player class: {str(e)}"
            )
            return

    try:
        toon_data = get_toon_data(toon)
    except Exception as e:
        await ctx.send(f"An error occurred while getting the toon data: {str(e)}")
        return

    try:
        discord_exists = check_discord_exists(discord_id)
    except Exception as e:
        await ctx.send(f"An error occurred while checking if discord exists: {str(e)}")
        return

    if not discord_exists:
        try:
            add_user_to_dkp(user_name, discord_id, current_time)
            probationary_role = ctx.guild.get_role(884172643702546473)
            probationary_discussion = client.get_channel(884164383498965042)

            await ctx.message.author.add_roles(probationary_role)
            await probationary_discussion.send(
                f"`{toon}` just joined the server using the discord handle <@{discord_id}> "
                f"and is now a probationary member."
            )

        except Exception as e:
            await ctx.send(f"An error occurred while adding user to dkp: {str(e)}")
            return

    if player_class is not None and level is not None:

        try:
            toon_data = get_toon_data(toon)
            if toon_data:
                raise ValueError(
                    f"`{toon.capitalize()}` has previous records, "
                    f"try changing status with `!main`/`!alt` `name`."
                )

        except Exception as e:
            await ctx.send(f"An error occurred while getting the toon data: {str(e)}")
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
            await ctx.send(
                f":white_check_mark:<@{owner}>'s `{toon.capitalize()}` was entered into the census "
                f"and is now a level `{level}` `{status}` `{player_class}`"
            )
            return

        except Exception as e:
            await ctx.send(
                f"An error occurred while inserting `{toon.capitalize()}` to census. "
                f"`{toon.capitalize()}` probably already exists. "
                f"Try changing status. {str(e)}"
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
            await ctx.send(
                f":white_check_mark:<@{owner}>'s `{toon.capitalize()}` is now `{status}`"
            )
            return

        except Exception as e:
            await ctx.send(f"An error occurred while updating census: {str(e)}")
            return

    if len(toon_data) == 0:
        await ctx.send(
            f":exclamation:`{toon.capitalize()}` was not found\nSee `!help main/alt/drop`"
        )
        return

    if len(toon_data) > 1:
        await ctx.send(
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
        census = pd.read_sql_query("SELECT * FROM census", POSTGRES_URL)
        dkp = pd.read_sql_query("SELECT * FROM dkp", POSTGRES_URL)
        discord_id = census.loc[census["name"] == name, "discord_id"].item()

        channel = client.get_channel(851549677815070751)  # census chat
        member = await ctx.guild.fetch_member(discord_id)
        probationary_role = ctx.guild.get_role(884172643702546473)  # come back to this
        member_role = ctx.guild.get_role(870669705646587924)

        await member.remove_roles(probationary_role)
        await member.add_roles(member_role)

        await ctx.send(f"{name} has been promoted to full member.")
        await channel.send(
            f"<@&870669705646587924> Send your congrats to <@{discord_id}>, the newest full member of Ex Astra!"
        )
    except AttributeError:
        await ctx.send(
            f"Sorry, a user with the name {name} could not be found. Please check the spelling and try again."
        )
    except Exception as e:
        await ctx.send(f"An error occurred while promoting {name}. Error message: {e}")


# @client.command(
#     help="Assign someone's discord. Use /assign instead.",
#     brief="Assign someone's discord. Use /assign instead.",
# )
# @commands.has_role("Officer")
# async def assign(ctx):
#     await ctx.send(
#         f"This command is now a slash command. "
#         f"Please use `/assign` instead. "
#         f"Pay careful attention to check if the toon already exists in the `toon` command build autocomplete. "
#         f"Also note hitting the `Tab` key will autocomplete fields in a way that will greatly reduce errors. "
#     )


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
        await ctx.send(f"Error: {e}")


@client.command(
    help="Sets or changes a bot character for a user. Usage: !bot <character> [level] [class]",
    brief="Sets or changes your bot character",
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
        await ctx.send(f"Error: {e}")


@client.command(
    help="Sets or changes an alternate character for a user. Usage: !alt <character> [level] [class]",
    brief="Sets or changes your alternate character",
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
        await ctx.send(f"Error: {e}")


@client.command(
    help="Removes a character from a user's list. Usage: !drop <character> [level] [class]",
    brief="Removes a character from your list",
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
        "SELECT DISTINCT name from census WHERE status = %s and name = %s;",
        ("Dropped", toon.capitalize()),
    )
    rows = cur.fetchall()

    # determine if the character's toon has already been dropped
    if len(rows) > 0:
        await ctx.send(
            f":question:`{toon.capitalize()}` was not found\nSee `!help main/alt/drop`"
        )

    else:
        await declare_toon(ctx, "Dropped", toon, level, player_class, user_name)


@client.command(
    help="Removes all characters associated with a specified character's name. Usage: !purge <character>",
    brief="Removes all characters linked to a name",
)
@commands.has_role("Officer")
async def purge(
    ctx,
    toon: str = commands.parameter(description="The name of the character to purge."),
):
    cur.execute("SELECT discord_id FROM census WHERE name = %s;", (toon.capitalize(),))
    rows = cur.fetchall()
    if len(rows) == 0:
        await ctx.send(
            f":warning: No character named `{toon.capitalize()}` found in the census."
        )
        return
    discord_id = rows[0][0]
    cur.execute(
        "SELECT DISTINCT name FROM census WHERE discord_id = %s;", (discord_id,)
    )
    all_toons = cur.fetchall()
    for row in all_toons:
        toon_name = row[0]
        await drop(ctx, toon_name)
    await ctx.send(
        f":white_check_mark: All toons associated with `{toon.capitalize()}` have been purged."
    )


@client.command(
    aliases=["level"],
    help="Updates the level of a character. If new level is not provided, the character's current level is incremented by 1.",
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
        engine = create_engine(POSTGRES_URL, echo=False)
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
        Dkp = Base.classes.dkp
        Class_lore = Base.classes.class_lore

        # See what the rank of the user is by the earned_dkp column in DKp

        # Assuming `session` is your SQLAlchemy session and `user_id` is the ID of the user

        toon_data = session.query(Census).filter_by(name=toon.capitalize()).first()
        toon_owner = toon_data.discord_id
        hours_raided = (
            session.query(Attendance).filter_by(discord_id=toon_owner).count()
        )

        user_dkp = session.query(Dkp).filter_by(discord_id=toon_owner).first()
        user_rank = (
            session.query(Dkp)
            .order_by(desc(Dkp.earned_dkp))
            .filter(Dkp.earned_dkp >= user_dkp.earned_dkp)
            .count()
        )
        total_users = session.query(Dkp).count()

        if toon_data is None:
            await ctx.send(
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
        player_class = player_class.lower()

        # Check that the new level is valid
        if new_level == current_level:
            await ctx.send(
                f":level_slider: `{toon.capitalize()}` is already at level `{new_level}`"
            )
            return

        if new_level < 1 or new_level > 60:
            await ctx.send(
                f":compass: Hail, `{toon.capitalize()}`! In the realms of Norrath, levels range from `1` to `60`."
                f"Adjust your compass and try again!",
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
        await ctx.send(
            f"{symbol}<@{toon_owner}>'s `{toon.capitalize()}` is now level `{new_level}`"
        )

    finally:
        pass


# @client.command(
#     help="Decreases the level of a character by 1. Usage: !dong <toon>",
#     brief="Decreases the level of a character",
# )
# async def dong(
#     ctx,
#     toon: str = commands.parameter(
#         description="The name of the character whose level is to be decreased."
#     ),
# ):
#     try:
#         engine = create_engine(POSTGRES_URL, echo=False)
#         Session = sessionmaker(bind=engine)
#         session = Session()

#         # Reflect the tables
#         Base = automap_base()
#         Base.prepare(autoload_with=engine)

#         # Mapped classes are now created with names by default
#         # matching that of the table name.
#         Census = Base.classes.census

#         toon_data = session.query(Census).filter_by(
#             name=toon.capitalize()).first()
#         toon_owner = toon_data.discord_id

#         if toon_data is None:
#             await ctx.send(f":x: `{toon.capitalize()}` was not found.")
#             return

#         current_level = toon_data.level

#         if current_level == 1:
#             await ctx.send(
#                 f":level_slider: <@{toon_owner}>'s `{toon.capitalize()}` is already at the lowest level `{current_level}`!"
#             )
#             return

#         new_level = current_level - 1

#         # Invoke the ding command with the new level
#         await ctx.invoke(client.get_command("ding"), toon=toon, new_level=new_level)

#     except Exception as e:
#         await ctx.send(content=f":x: An error occurred: {str(e)}")
#     finally:
#         session.close()


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
                value="\n" + "\n".join(toons.name.tolist()) + "\n",
                inline=True,
            )

            embed.add_field(
                name=":crossed_swords:️ Class",
                value="\n" + "\n".join(toons.character_class.tolist()) + "\n",
                inline=True,
            )

            embed.add_field(
                name=":arrow_double_up: Level",
                value="\n" + "\n".join(map(str, toons.level.tolist())) + "\n",
                inline=True,
            )

    add_toons_to_embed(toons_list, main_toons, "Main")
    add_toons_to_embed(toons_list, alt_toons, "Alt")
    add_toons_to_embed(toons_list, bot_toons, "Bot")

    return toons_list


@client.command(
    help="Shows details about a specified character or all of a user's characters. Usage: !toons [character]",
    brief="Shows character details",
)
async def toons(
    ctx,
    toon: str = commands.parameter(
        description="The toon you want to know more about. Defaults to you.",
        default=None,
    ),
):
    try:
        engine = sqlalchemy.create_engine(POSTGRES_URL, echo=False)
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
                await ctx.send(f":x: No toon named `{toon.capitalize()}` was found.")
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
        await ctx.send(embed=toons_list)

    except Exception as e:
        await ctx.send(content=f":x: An error occurred: {str(e)}")

    finally:
        session.close()

    return discord_id, toons


async def get_dkp_data(discord_id, toon=None):
    engine = sqlalchemy.create_engine(POSTGRES_URL, echo=False)
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
        await ctx.send(embed=dkp_embed)
    else:
        await ctx.send(content=":question: No census entry was found. Check `!toons`.")


@client.command(
    help="Updates DKP based on raid logs. Usage: !logs <description> with logs or as a send to logs.",
    brief="Updates DKP from raid logs",
)
@commands.has_role("Officer")
async def logs(
    ctx,
    *,
    args: str = commands.parameter(
        description="The raid logs to process. Can be a send to posted logs."
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
        await ctx.send(f"`{raid}` entry not found.\nAsk Rahmani")
        return

    # create empty lists of rejected players and seen players to prevent double counting
    seen_players = []
    rejected = []

    # if this is a send to a message
    is_send = check_send(ctx)
    if is_send == True:
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

        sql_response = "INSERT INTO attendance (date, raid, name, discord_id, modifier) VALUES (%s, %s, %s, %s, %s);"

        cur.execute(sql_response, (timestamp, raid, name, discord_id, modifier))

        if cur.rowcount == 1:
            con.commit()

        else:
            await ctx.send(f"Something is wrong with the record: {record}")
            con.rollback()

        sql_response = (
            "UPDATE dkp SET earned_dkp = earned_dkp + %s WHERE discord_id = %s;"
        )
        cur.execute(sql_response, (modifier, discord_id))
        # await ctx.send(sql_response)

        if cur.rowcount == 1:
            con.commit()

        else:
            await ctx.send(
                f":exclamation:Something is wrong with the record: `{record}`"
            )
            con.rollback()

    if len(seen_players) > 0:
        await ctx.send(
            f":dragon:{', '.join(seen_players)} earned `{modifier}` DKP for `{raid}` this hour."
        )
        await ctx.message.add_reaction("✅")

        if is_send:
            await message.add_reaction("✅")

    if len(rejected) > 0:
        sep = "\n"

        rejected = sep.join(rejected)
        rejected = re.sub("```", "", rejected)
        # get rid of the extra triple backticks

        await ctx.send(
            f":question:Some logs got rejected, since these players are not registered. ```\n{rejected}\n```"
        )
        await ctx.message.add_reaction("❌")

        if is_send:
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
    view.add_item(
        DeleteButton(user_id=ctx.author.id, original_message_id=ctx.message.id)
    )
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

        census = pd.read_sql_query("SELECT * FROM census", POSTGRES_URL)

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
            await ctx.send(
                "Unfortunately, no table with the required columns was found. Please alert an officer."
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

        await ctx.send(embed=rap_list, view=view)


@client.command(
    help='Keep track of your inventory using the EverQuest Inventory Manager. Usage: !inventory while uploading up to ten inventory files at a time. These files can be retrieved using the output of the "/outputfile inventory" command in-game.',
    brief="Uploads inventory files to the database",
)
@commands.has_role("Member")
async def inventory(ctx):

    async with ctx.typing():

        # check if the message has attachments
        if len(ctx.message.attachments) < 1:
            await ctx.send(
                ":x: Please attach at least one inventory file to your message. Inventory update failed."
            )
            return

        await ctx.message.delete()

        engine = create_engine(POSTGRES_URL)
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
    help="Keep track of shared bot's inventory. Usage 'wheresmy [item]'",
    brief="Find an item on a shared bot",
)
@commands.has_role("Member")
async def wheresmy(ctx, *, stuff):

    view = discord.ui.View(timeout=None)
    view.add_item(
        DeleteButton(user_id=ctx.author.id, original_message_id=ctx.message.id)
    )
    view.add_item(DMButton(ctx.author.id))

    async with ctx.typing():

        engine = create_engine(POSTGRES_URL)
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
            await ctx.send(f":x: An error occurred. {e}")
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
            await ctx.send(f":x: An error occurred. {e}")
            return

        # check if the search term is in the items
        if items.empty:
            await ctx.send(
                f":x: `{titlecase(stuff)}` was not found in inventory for <@{ctx.author.id}>",
                view=view,
            )

            session.close()
            return

        # Send the embed with the image

        file, path = table_to_file(items)

        view.response_message = await ctx.send(
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
@commands.has_any_role("Member", "Probationary Member", "Officer")
async def find(ctx, *, stuff):

    view = discord.ui.View(timeout=None)
    view.add_item(
        DeleteButton(user_id=ctx.author.id, original_message_id=ctx.message.id)
    )
    view.add_item(DMButton(ctx.author.id))

    async with ctx.typing():

        engine = create_engine(POSTGRES_URL)
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
            await ctx.send(f":x: An error occurred. {e}")
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
            await ctx.send(f":x: An error occurred. {e}")
            return

        # check if the search term is in the items
        if items.empty:
            view.response_message = await ctx.send(
                f"No matches found for `{titlecase(stuff)}`.",
                view=view,
            )
            return

        # Send the embed with the image

        try:
            file, path = table_to_file(items)
        except Exception as e:
            await ctx.send(f":x: An error occurred. {e}")
            return

        view.response_message = await ctx.send(
            f":mag: Results for `{titlecase(stuff)}` in bankers inventory.",
            file=file,
            view=view,
        )

        # Close the session
        session.close()

        os.remove(path)


@client.command(
    help="Update the guild bank with a new inventory. Usage: !bank while uploading an inventory file.",
    brief="Update the guild bank.",
)
@commands.has_role("Treasurer")
async def bank(ctx):

    if ctx.message.attachments:
        attachment = ctx.message.attachments[0]
    else:
        await ctx.send(
            "No attachment found in the message. "
            "Try attaching a banker's inventory with `!bank`."
        )
        return

    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    engine = sqlalchemy.create_engine(POSTGRES_URL, echo=False)

    attachment = ctx.message.attachments[0]
    banker_name = Path(attachment.url).stem.split("-")[0]
    inventory_keyword = Path(attachment.url).stem.split("-")[1]

    await ctx.send(f"Parsing `{inventory_keyword}` for `{banker_name}`")

    old_data = pd.read_sql(
        "SELECT name, quantity FROM bank WHERE Banker = %s",
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

    inventory.insert(0, "banker", banker_name)

    inventory.insert(0, "time", current_time)

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

    sql_response = "DELETE FROM bank WHERE banker = %s"

    cur.execute(sql_response, (banker_name,))
    con.commit()

    inventory.to_sql("bank", engine, if_exists="append", index=False)

    treasury_channel_id = 875884763305631754
    treasury_channel = client.get_channel(treasury_channel_id)

    if ctx.channel.id != treasury_channel_id:
        await ctx.send("The response has been recorded in the Treasury channel.")
        file = await attachment.to_file()
        await treasury_channel.send(
            content=f"<@{ctx.author.id}> has updated the guild bank", file=file
        )

    if merged_data.empty:
        treasury_channel = client.get_channel(treasury_channel_id)
        await treasury_channel.send(
            f"No changes detected for `{banker_name}` ." f"But thanks for the update!"
        )

    else:
        treasury_channel = client.get_channel(treasury_channel_id)
        await treasury_channel.send(
            f"Changes detected for `{banker_name}`. Here's the summary."
        )

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
            await treasury_channel.send(f"```{diff_string}```")

    await ctx.message.delete()  # Delete the original message


@client.command(
    help="Complete data dump of every inventory item on the guild bankers",
    brief="Single-file output of banker inventory",
)
async def banktotals(ctx, stuff=None):

    view = discord.ui.View(timeout=None)
    view.add_item(
        DeleteButton(user_id=ctx.author.id, original_message_id=ctx.message.id)
    )
    view.add_item(DMButton(ctx.author.id))

    engine = sqlalchemy.create_engine(POSTGRES_URL, echo=False)
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
        await ctx.send(f":x: An error occurred. {e}")
        return

    view.response_message = await ctx.send(
        f":moneybag:Here's the bank totals.\nRequested by <@{ctx.author.id}>.",
        file=file,
        view=view,
    )

    os.remove(path)


@client.command(
    help="Complete data dump of every inventory item on the guild bankers",
    brief="Single-file output of banker inventory",
)
async def banker(ctx, banker_name=None):
    view = discord.ui.View(timeout=None)
    view.add_item(
        DeleteButton(user_id=ctx.author.id, original_message_id=ctx.message.id)
    )
    view.add_item(DMButton(ctx.author.id))

    view = discord.ui.View(timeout=None)
    view.add_item(
        DeleteButton(user_id=ctx.author.id, original_message_id=ctx.message.id)
    )
    view.add_item(DMButton(ctx.author.id))

    engine = sqlalchemy.create_engine(POSTGRES_URL, echo=False)
    bank = pd.read_sql_table("bank", con=engine)
    trash = pd.read_sql_table("trash", con=engine)
    if banker_name is not None:
        banker_name = banker_name.capitalize()
    banker_names = bank["banker"].unique()

    # if stuff is None, then show everything
    if banker_name is None or banker_name not in banker_names:

        bankers = bank["banker"].unique()
        bankers = sorted(bankers)
        await ctx.send(
            f":x: Please specify a banker. Available bankers are: {list_to_oxford_comma(bankers)}"
        )

    else:
        bank = bank[~bank["name"].isin(trash["name"])]
        bank = bank[bank["banker"] == banker_name]
        bank = bank.sort_values(["name", "location"], ascending=[True, True])

        try:
            file, path = table_to_file(bank)
        except Exception as e:
            await ctx.send(f":x: An error occurred. {e}")
            return

        view.response_message = await ctx.send(
            f":moneybag:Here's the bank totals for `{banker_name}`.\nRequested by <@{ctx.author.id}>.",
            file=file,
            view=view,
        )

        os.remove(path)


@client.command()
async def bidhistory(ctx):

    view = discord.ui.View(timeout=None)
    view.add_item(
        DeleteButton(user_id=ctx.author.id, original_message_id=ctx.message.id)
    )
    view.add_item(DMButton(ctx.author.id))

    engine = sqlalchemy.create_engine(POSTGRES_URL, echo=False)
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
        await ctx.send(f":x: An error occurred. {e}")
        return

    view.response_message = await ctx.send(
        f":moneybag: Here's your bid history.\nRequested by <@{ctx.author.id}>.",
        file=file,
        view=view,
    )

    os.remove(path)


@client.command()
async def dkphistory(ctx):

    view = discord.ui.View(timeout=None)
    view.add_item(
        DeleteButton(user_id=ctx.author.id, original_message_id=ctx.message.id)
    )
    view.add_item(DMButton(ctx.author.id))

    engine = sqlalchemy.create_engine(POSTGRES_URL, echo=False)
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
        await ctx.send(f":x: An error occurred. {e}")
        return

    view.response_message = await ctx.send(
        f":moneybag: Here's your DKP earnings history.",
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
        await send_no_matching_toon(ctx, level, max_level, player_class)
    else:
        await send_matching_toons(ctx, matching_toons, level, max_level, player_class)


async def send_split_message(ctx, message):
    max_length = 2000
    messages = [message[i : i + max_length] for i in range(0, len(message), max_length)]
    for msg in messages:
        await ctx.send(msg)


async def validate_and_process_input(ctx, level, optional_max_level, player_class):
    try:
        level = int(level)
    except ValueError:
        ctx.send(f"{level} is not a valid level.")
        return None, None, None

    if player_class is None:  # Exact mode
        max_level = level
        player_class = optional_max_level
    else:  # Range mode
        try:
            max_level = int(optional_max_level)
        except ValueError:
            ctx.send(f"{optional_max_level} is not a valid level.")
            return None, None, None

        if level > max_level:
            ctx.send("Invalid level range.")
            return None, None, None

    if not 1 <= level <= 60:
        ctx.send("You think you're funny, huh?")
        return None, None, None

    return (
        level,
        max_level,
        await get_player_class(player_class) if player_class is not None else None,
    )


# def fetch_matching_toons(level, max_level, player_class):
#     Base = automap_base()
#     engine = create_engine(POSTGRES_URL)
#     Base.prepare(autoload_with=engine)

#     Attendance = Base.classes.attendance
#     Census = Base.classes.census

#     session = Session(engine)

#     toon_q = (
#         session.query(Census)
#         .filter(Census.character_class == player_class)
#         .filter(Census.level >= level)
#         .filter(Census.level <= max_level)
#         .filter(Census.status != "Dropped")
#         .join(Attendance, Attendance.discord_id == Census.discord_id)
#         .having(func.max(Attendance.date))
#         .group_by(Attendance.discord_id)
#         .order_by(Attendance.date.desc())
#     )

#     return pd.read_sql(toon_q.statement, toon_q.session.bind)[
#         ["name", "discord_id", "level"]
#     ]


# async def send_no_matching_toon(ctx, level, max_level, player_class):
#     if max_level == level:
#         await ctx.send(f"There were no level {level} {player_class}s found.")
#     else:
#         await ctx.send(
#             f"There were no level {level} to {max_level} {player_class}s found."
#         )


# async def send_matching_toons(ctx, matching_toons, level, max_level, player_class):
#     guild = ctx.guild
#     names = []
#     mentions = []
#     left_server_names = []

#     for _, row in matching_toons.iterrows():
#         name = row["name"]
#         discord_id = row["discord_id"]
#         toon_level = row["level"]
#         member = guild.get_member(int(discord_id))

#         if member is not None:
#             names.append(name)
#             if toon_level == max_level or toon_level == level:
#                 mentions.append((discord_id, toon_level))
#             else:
#                 mentions.append((discord_id, f"{toon_level}-{max_level}"))
#         else:
#             left_server_names.append(name)

#     embed = discord.Embed(
#         title=f":white_check_mark: Registered level {level} to {max_level} {player_class}s",
#         description="Sorted by most recently earned DKP on any character.",
#         colour=discord.Colour.from_rgb(241, 196, 15),
#     )

#     embed.add_field(
#         name=":bust_in_silhouette: Name",
#         value="".join([f"`{name}`\n" for name in names]),
#         inline=True,
#     )

#     embed.add_field(
#         name=":busts_in_silhouette: Discord",
#         value="".join(
#             [
#                 f"`{' ' if toon_level < 10 else ''}{mention[1]}`<@{mention[0]}>\n"
#                 for mention in mentions
#             ]
#         ),
#         inline=True,
#     )

#     if left_server_names:
#         left_server_names_str = ", ".join(left_server_names)
#         embed.set_footer(
#             text=f"The following characters appear not to belong to this server anymore:\n{left_server_names_str}"
#         )

#     await ctx.send(embed=embed)


@client.command(
    help="Takes control of a toon that is currently marked as a 'Bot'. Usage: !claim <toon_name>",
    brief="Claim a toon.",
)
async def claim(ctx, toon):

    toon = toon.capitalize()
    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    discord_id = str(ctx.author.id)

    Base = automap_base()
    engine = create_engine(POSTGRES_URL)
    Base.prepare(autoload_with=engine)
    Census = Base.classes.census
    session = Session(engine)

    claimed_toon = session.query(Census).filter(Census.name == toon).one()

    old_owner = claimed_toon.discord_id

    if claimed_toon.status == "Bot" or claimed_toon.status == "Dropped":

        claimed_toon.discord_id = discord_id

        claimed_toon.time = current_time

        session.commit()

        await ctx.send(
            f":white_check_mark:<@{discord_id}> has taken control of `{toon}` from <@{old_owner}>."
        )

    if claimed_toon.status != "Bot" and claimed_toon.status != "Dropped":

        await ctx.send(
            f":exclamation:`{toon}` can only change ownership if <@{old_owner}> changes status using `!bot` or `!drop`.",
            f"Try `!drop {toon}` or `!bot {toon}`.",
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
        await ctx.send(f":question: Command not found \nSee `!help`")
        return

    if isinstance(error, commands.NoPrivateMessage):
        await ctx.send(f":question: This command must be used in a public channel")
        return

    if isinstance(error, commands.MissingRequiredArgument) or isinstance(
        error, commands.BadArgument
    ):
        command = ctx.message.content.split()[0]
        await ctx.send(
            f":question: Missing some information. \nSee `!help {command[1:]}`"
        )
        return

    if isinstance(error, commands.MissingRole):
        await ctx.send(
            f":question: Command reserved for a different role \nSee `!help`"
        )
        return

    raise error


###########


@client.command(
    help="Asks a question and provides a response. Usage: !ask <question> [--required_keyword=<value1,value2,...>]",
    brief="Ask a question and get an answer.",
)
async def ask(ctx, *, question):
    """
    This command allows users to ask a question and get an answer.
    The question can include an optional 'required_keyword' argument
    to pass specific keywords to the downstream function.

    Usage:
    !ask What is the weather today? --required_keyword=sunny,rainy

    Parameters:
    - question: The main question being asked.
    - required_keyword (optional): A comma-separated list of keywords that are required for the response.

    The 'required_keyword' argument is passed as a keyword argument to the downstream function.
    """
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
                if len(key_value) == 2 and key_value[0].strip() == "required_keyword":
                    # Split the values by comma and store them in a list
                    values = [value.strip() for value in key_value[1].split(",")]
                    # Store the values as a list under 'required_keyword'
                    kwargs["required_keyword"] = values

        # Call ask_async with parsed kwargs
        response = await ask_async(question, **kwargs)
        chunks = chunk_strings(response)

        for chunk in chunks:
            await ctx.send(chunk)


async def async_openai_call(messages):
    async with aiohttp.ClientSession() as session:
        headers = {
            "Authorization": f"Bearer {config.OPENAI_API_KEY}",
            "Content-Type": "application/json",
        }
        data = json.dumps(
            {
                "model": "gpt-4-turbo-preview",  # Specify the model here
                "messages": messages,  # List of messages
                # No need for max_tokens or temperature here
            }
        )
        async with session.post(
            "https://api.openai.com/v1/chat/completions", headers=headers, data=data
        ) as resp:
            return await resp.json()


client.run(config.DISCORD_TOKEN)
