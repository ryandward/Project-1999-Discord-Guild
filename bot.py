#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Imports
import contextlib
from sqlalchemy import create_engine
import config
import datetime
import discord
import gspread
import io
import os
import pandas as pd
import re
import requests
import time
import pytz
import sqlite3
import sqlalchemy
import subprocess

from sqlalchemy.ext.automap import automap_base
from sqlalchemy.orm import Session
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import func

from difflib import get_close_matches as gcm
from discord.ext import commands
from discord.ext.commands import Bot
from discord.ext.commands import CommandNotFound
from tabulate import tabulate
from pathlib import Path
from titlecase import titlecase
from urllib.request import Request, urlopen


class CensusError(Exception):
    def __init__(self, error_code):
        if error_code == "not owner":
            message = "Someone who was not the owner attempted to change a character status."

        else:
            message = "There was an unhandled census exception."

        super().__init__(message)


def has_numbers(inputString):
    return any(char.isdigit() for char in inputString)

def chop_microseconds(delta):
    return delta - datetime.timedelta(microseconds=delta.microseconds)


def check_reply(ctx):
    result = ctx.message.reference
    if result is None:
        return False
    else:
        return True

con = sqlite3.connect('ex_astra.db')
con.execute('PRAGMA foreign_keys = ON')
cur = con.cursor()

player_classes = pd.read_sql_query('SELECT * FROM class_definitions', con)
raids = pd.read_sql_query('SELECT * FROM raids', con)

intents = discord.Intents.default()
intents.members = True

# Create bot
client = commands.Bot(
    command_prefix=config.prefix,
    case_insensitive=True,
    intents=intents)

# Startup Information
@client.event
async def on_ready():
    print('Connected to bot:{}'.format(client.user.name))
    print('Bot ID:{}'.format(client.user.id))

@client.command()
async def ping(ctx):
    pingtime = time.time()
    await ctx.reply("Pinging...")
    ping = time.time() - pingtime
    await ctx.reply(":ping_pong: time is `%.01f seconds`" % ping)

@client.command()
async def apply(ctx):

    discord_id = ctx.message.guild.get_member_named(format(ctx.author)).id
    channel = client.get_channel(988260644056879194)  # census chat
    member = await ctx.guild.fetch_member(discord_id)
    applicant_role = ctx.guild.get_role(990817141831901234)  # come back to this

    await member.add_roles(applicant_role)

    await ctx.reply(f"Attention <@&849337092324327454> and <@&906952889287708773>, <@{discord_id}>, has submitted an application.")

@client.command()
@commands.has_role("Lootmaster")
async def deduct(ctx, amount: int, name, *, args):
    census = pd.read_sql_query('SELECT * FROM census', con)
    dkp = pd.read_sql_query('SELECT * FROM dkp', con)

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
        cur.execute('INSERT INTO items (name, item, dkp_spent, date, discord_id) VALUES (?, ?, ?, ?, ?);',
                    (name.capitalize(), titlecase(args), amount, current_time, discord_id))

        if cur.rowcount == 1:
            cur.execute('UPDATE dkp SET spent_dkp = spent_dkp + ? WHERE discord_id = ?;',
                        (str(amount), discord_id))

            if cur.rowcount == 1:
                con.commit()

                await ctx.reply(f":white_check_mark:<@{discord_id}> spent `{amount}` DKP on `{titlecase(args)}` for `{name.capitalize()}`!")

            else:
                con.rollback()

                await ctx.reply(f":question:Something weird happened, ask Rahmani. `Error -2`")

        else:
            con.rollback()

            await ctx.reply(f":question:Something weird happened, ask Rahmani. `Error -1`")

    else:
        await ctx.reply(f":exclamation:`{amount}` is greater than `{name.capitalize()}`'s current total of `{current_dkp}` DKP\nNo action taken")

################################################################################

@client.command()
@commands.has_any_role('Officer', 'Probationary Officer', 'Lootmaster')
async def award(ctx, amount: int, name, *, args):
    census = pd.read_sql_query('SELECT * FROM census', con)

    dkp = pd.read_sql_query('SELECT * FROM dkp', con)

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

    cur.execute('INSERT INTO attendance (raid, name, date, discord_id, modifier) VALUES (?, ?, ?, ?, ?);',
                (titlecase(args), name.capitalize(), current_time, discord_id, amount))

    if cur.rowcount == 1:
        cur.execute('UPDATE dkp SET earned_dkp = earned_dkp + ? WHERE discord_id = ?;',
                    (str(amount), discord_id))

        if cur.rowcount == 1:
            con.commit()

            await ctx.reply(f":white_check_mark:<@{discord_id}> earned `{amount}` DKP for `{titlecase(args)}` on `{name.capitalize()}`!")

        else:
            con.rollback()

            await ctx.reply(f":question:Something weird happened, ask Rahmani. `Error -2`")

    else:
        con.rollback()

        await ctx.reply(f":question:Something weird happened, ask Rahmani. `Error -1`")

########################################################################################################
# def get_player_class(player_class):
#     player_class = titlecase(player_class)
#     player_class_names = player_classes['class_name'].to_list()
#     player_class_name = gcm(player_class, player_class_names, n=1, cutoff=0.5)

#     if len(player_class_name) == 0:
#         raise CensusError("Error")
#         return

#     else:
#         player_class_name = player_class_name[0]
#         player_class = player_classes.loc[player_classes['class_name']
#                                           == player_class_name, 'character_class'].item()
#         return (player_class)

# def get_level(level):
#     if level < 0 or level > 60:
#         raise CensusError("Error")
#         return
#     else:
#         return (level)
    
# async def declare_toon(ctx, status, toon, level: int = None, player_class: str = None, user_name: str = None, discord_id: str = None):
#     if discord_id is None:
#         discord_id = str(ctx.message.guild.get_member_named(user_name).id)
    
#     allowed_channels = [851549677815070751, 862364645695422514]

#     if ctx.channel.id not in allowed_channels:
#         await ctx.reply("This command can only be performed on <#851549677815070751>.")
#         raise CensusError('Someone tried to declare a toon that was not on the census channel.')


#     census = pd.read_sql_query('SELECT * FROM census', con)
#     current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
#     discord_id = ctx.message.guild.get_member_named(user_name).id

#     if player_class is not None:
#         player_class = get_player_class(player_class)

#     cur.execute('SELECT * FROM census WHERE name == ?;', (toon.capitalize(),))

#     col_names = list(map(lambda x: x[0], cur.description))

#     rows = cur.fetchall()

#     cur.execute('SELECT * FROM dkp WHERE discord_id == ?;', (discord_id,))

#     col_names = list(map(lambda x: x[0], cur.description))

#     discord_exists = cur.fetchall()

#     # if the discord account was not found
#     if len(discord_exists) == 0:

#         discord_id = ctx.message.guild.get_member_named(user_name).id

#         cur.execute('INSERT INTO dkp (discord_name, earned_dkp, spent_dkp, date_joined, discord_id) VALUES (?, 5, 0, ?, ?);',
#                     (user_name, current_time, discord_id))

#         if cur.rowcount == 1:
#             con.commit()

#             channel = client.get_channel(884164383498965042)

#             member = ctx.message.guild.get_member_named(user_name)

#             approved_role = ctx.guild.get_role(1001891874161823884)
#             await member.remove_roles(approved_role)

#             probationary_role = ctx.guild.get_role(884172643702546473)  # come back to this
#             await member.add_roles(probationary_role)

#             formatted_id = f'<@{discord_id}>'

#             # await channel.send(f"<@&849337092324327454> `{toon}` just joined the server using the discord handle {formatted_id} and is now a probationary member.")
#             await channel.send(f"`{toon}` just joined the server using the discord handle {formatted_id} and is now a probationary member.")

#         else:
#             con.rollback()

#             await ctx.reply(f":question:Something weird happened, ask Rahmani. `Error 0`")

#     # if the character was found
#     # if len(rows) > 1:
#     #     await ctx.reply("This is a shared character. Demographics cannot be changed currently.")

#     if len(rows) == 1:

#         if level is None:

#             cur.execute('UPDATE census SET status = ?, time = ? WHERE name = ?;',
#                         (status.capitalize(), current_time, toon.capitalize()))

#             if cur.rowcount == 1:

#                 con.commit()

#                 await ctx.reply(f":white_check_mark:`{toon.capitalize()}` is now `{status}`")

#             else:

#                 con.rollback()

#                 await ctx.reply(f":question:Something weird happened, ask Rahmani. `Error 1`")

#         if level is not None:

#             if player_class is None:

#                 cur.execute('UPDATE census SET status = ?, level = ?, time = ? WHERE name = ?;',
#                             (status.capitalize(), level, current_time, toon.capitalize()))

#                 if cur.rowcount == 1:

#                     con.commit()

#                     await ctx.reply(f":white_check_mark:`{toon.capitalize()}` is now `{status}` and level `{level}`")

#                 else:

#                     con.rollback()

#                     await ctx.reply(f":question:Something weird happened, ask Rahmani. `Error 2`")

#             if player_class is not None:

#                 cur.execute('UPDATE census SET status = ?, level = ?, character_class = ?, time = ? WHERE name = ?;',
#                             (status.capitalize(), level, player_class, current_time, toon.capitalize()))

#                 if cur.rowcount == 1:

#                     con.commit()

#                     await ctx.reply(f":white_check_mark:`{toon.capitalize()}` is now a level `{level}` `{player_class}` `{status}`")

#                 else:
#                     con.rollback()

#                     await ctx.reply(f":question:Something weird happened, ask Rahmani. `Error 3`")

#     if len(rows) == 0:

#         if player_class is None or level is None:

#             await ctx.reply(f":question:`{toon.capitalize()}` was not found\nSee `!help main/alt/drop`")

#         else:

#             cur.execute('INSERT INTO census (name, level, character_class, discord_id, status, time) VALUES (?, ?, ?, ?, ?, ?);',
#                         (toon.capitalize(), level, player_class, discord_id, status.capitalize(), current_time))

#             if cur.rowcount == 1:

#                 con.commit()

#                 await ctx.reply(f":white_check_mark:`{toon.capitalize()}` was created and is now a level `{level}` `{player_class}` `{status}`")

#             else:
#                 con.rollback()
#                 await ctx.reply(f":question:Something weird happened, ask Rahmani. `Error 4`")

#######################################
# Helper functions
async def get_discord_id(ctx, user_name, discord_id):
    if discord_id is None:
        discord_id = str(ctx.message.guild.get_member_named(user_name).id)
    return discord_id

async def check_allowed_channels(ctx):
    allowed_channels = [851549677815070751, 862364645695422514]
    if ctx.channel.id not in allowed_channels:
        return False
    return True

def get_census():
    return pd.read_sql_query('SELECT * FROM census', con)

def get_level(level):
    if level < 0 or level > 60:
        raise ValueError("Invalid level. The level must be between 0 and 60.")
    else:
        return (level)

async def get_player_class(player_class):
    player_class = titlecase(player_class)
    player_class_names = player_classes['class_name'].to_list()
    player_class_name = gcm(player_class, player_class_names, n=1, cutoff=0.5)
    if len(player_class_name) == 0:
        raise ValueError("Invalid player class. Please provide a valid player class.")
    else:
        player_class_name = player_class_name[0]
        player_class = player_classes.loc[player_classes['class_name'] == player_class_name, 'character_class'].item()
        return player_class

def get_toon_data(toon):
    cur.execute('SELECT * FROM census WHERE name == ?;', (toon.capitalize(),))
    rows = cur.fetchall()
    return rows

def check_discord_exists(discord_id):
    cur.execute('SELECT * FROM dkp WHERE discord_id == ?;', (discord_id,))
    discord_exists = cur.fetchall()
    return len(discord_exists) > 0

def add_user_to_dkp(user_name, discord_id, current_time):
    cur.execute('INSERT INTO dkp (discord_name, earned_dkp, spent_dkp, date_joined, discord_id) VALUES (?, 5, 0, ?, ?);',
                (user_name, current_time, discord_id))
    con.commit()

def update_census(toon, status, level, player_class, current_time):
    if level is None:
        cur.execute('UPDATE census SET status = ?, time = ? WHERE name = ?;',
                    (status.capitalize(), current_time, toon.capitalize()))
    elif player_class is None:
        cur.execute('UPDATE census SET status = ?, level = ?, time = ? WHERE name = ?;',
                    (status.capitalize(), level, current_time, toon.capitalize()))
    else:
        cur.execute('UPDATE census SET status = ?, level = ?, character_class = ?, time = ? WHERE name = ?,',
                    (status.capitalize(), level, player_class, current_time, toon.capitalize()))
    con.commit()

def insert_to_census(toon, level, player_class, discord_id, status, current_time):
    cur.execute('INSERT INTO census (name, level, character_class, discord_id, status, time) VALUES (?, ?, ?, ?, ?, ?);',
                (toon.capitalize(), level, player_class, discord_id, status.capitalize(), current_time))
    con.commit()

# Main function
async def declare_toon(ctx, status, toon, level: int = None, player_class: str = None, user_name: str = None, discord_id: str = None):
    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
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
            await ctx.reply(f"An error occurred while getting the player class: {str(e)}")
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
        except Exception as e:
            await ctx.reply(f"An error occurred while adding user to dkp: {str(e)}")
            return
    
    if player_class is not None and level is not None:
        try:
            insert_to_census(toon, level, player_class, discord_id, status, current_time)
            await ctx.reply(f":white_check_mark:`{toon.capitalize()}` was created and is now a level `{level}` `{player_class}` `{status}`")
            return
        except Exception as e:
            await ctx.reply(f"An error occurred while inserting toon to census: {str(e)}")
            return

    if len(toon_data) == 1:
        try:
            update_census(toon, status, level, player_class, current_time)
            await ctx.reply(f":white_check_mark:`{toon.capitalize()}` is now `{status}`")
            return
        except Exception as e:
            await ctx.reply(f"An error occurred while updating census: {str(e)}")
            return

    await ctx.reply(f":question:`{toon.capitalize()}` was not found\nSee `!help main/alt/drop`")



#######################################
@client.command()
@commands.has_role("Officer")
async def promote(ctx, name):

    name = name.capitalize()
    census = pd.read_sql_query('SELECT * FROM census', con)
    dkp = pd.read_sql_query('SELECT * FROM dkp', con)
    discord_id = census.loc[census["name"] == name, "discord_id"].item()

    channel = client.get_channel(851549677815070751)  # census chat
    member = await ctx.guild.fetch_member(discord_id)
    probationary_role = ctx.guild.get_role(884172643702546473)  # come back to this
    member_role = ctx.guild.get_role(870669705646587924)

    await member.remove_roles(probationary_role)
    await member.add_roles(member_role)

    # await ctx.reply(f"<@&849337092324327454> Send your congrats to <@{discord_id}>, the newest full member of Ex Astra!")
    # await channel.send(f"<@&870669705646587924> Send your congrats to <@{discord_id}>, the newest full member of Ex Astra!")

    await ctx.reply(f"<@{discord_id}>, has been promoted to full member.")
    await channel.send(f"<@&870669705646587924> Send your congrats to <@{discord_id}>, the newest full member of Ex Astra!")

@client.command()
@commands.has_role("Officer")
async def assign(ctx, status, toon, level: int = None, player_class: str = None, user_id: int = None):
    if user_id is None:
        user_id = ctx.author.id

    user_name = ctx.guild.get_member(user_id).display_name

    await declare_toon(ctx, status, toon, level, player_class, user_name=user_name, discord_id=str(user_id))



@client.command()
async def main(ctx, toon, level: int = None, player_class: str = None):

    toon = toon.capitalize()

    census = pd.read_sql_query('SELECT * FROM census', con)

    toon_discord_id = census.loc[census["name"] == toon, "discord_id"]

    if len(toon_discord_id) > 0:
        toon_discord_id = toon_discord_id.item()
        toon_mains = census.loc[(census['discord_id'] == toon_discord_id) & (
            census['status'] == "Main") & (census['name'] != toon), 'name'].to_list()

        for i in toon_mains:
            await alt(ctx, i)

    else:
        user_discord_id = str(
            ctx.message.guild.get_member_named(format(ctx.author)).id)
        user_mains = census.loc[(census['discord_id'] == user_discord_id) & (
            census['status'] == "Main") & (census['name'] != toon), 'name'].to_list()

        for i in user_mains:
            await alt(ctx, i)

    user_name = format(ctx.author)
    await declare_toon(ctx, "Main", toon, level, player_class, user_name)


@client.command()
async def bot(ctx, toon, level: int = None, player_class: str = None):

    user_name = format(ctx.author)
    await declare_toon(ctx, "Bot", toon, level, player_class, user_name)


@client.command()
async def alt(ctx, toon, level: int = None, player_class: str = None):

    user_name = format(ctx.author)
    await declare_toon(ctx, "Alt", toon, level, player_class, user_name)


@client.command()
async def drop(ctx, toon, level: int = None, player_class: str = None):

    user_name = format(ctx.author)
    cur.execute("SELECT DISTINCT name from census WHERE status == ? and name == ?;",
                ('Dropped', toon.capitalize()))
    rows = cur.fetchall()

    # determine if the character's toon has already been dropped
    if len(rows) > 0:
        await ctx.reply(f":question:`{toon.capitalize()}` was not found\nSee `!help main/alt/drop`")

    else:
        await declare_toon(ctx, "Dropped", toon, level, player_class, user_name)

@client.command()
@commands.has_role("Officer")
async def purge(ctx, toon):
    cur.execute("SELECT discord_id FROM census WHERE name = ?;", (toon.capitalize(),))
    rows = cur.fetchall()
    if len(rows) == 0:
        await ctx.reply(f":warning: No character named `{toon.capitalize()}` found in the census.")
        return
    discord_id = rows[0][0]
    cur.execute("SELECT DISTINCT name FROM census WHERE discord_id = ?;", (discord_id,))
    all_toons = cur.fetchall()
    for row in all_toons:
        toon_name = row[0]
        await drop(ctx, toon_name)
    await ctx.reply(f":white_check_mark: All toons associated with `{toon.capitalize()}` have been purged.")


@client.command()
async def level(ctx, toon, level):

    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if (has_numbers(toon) == True) or (has_numbers(level) == False):
        await ctx.reply(f"Try `!level <toon> <level>`. Also make sure {toon} has been registered with `!main` or `!alt`.")
        return

    cur.execute('UPDATE census SET level = ?, time = ? WHERE name = ?;',
                (level, current_time, toon.capitalize()))
    if cur.rowcount == 1:
        con.commit()
        await ctx.reply(f":arrow_double_up:`{toon.capitalize()}` is now level `{level}`")

    if cur.rowcount == 0:
        con.rollback()
        await ctx.reply(f":question:`{toon.capitalize()}` was not found\nSee `!help main/alt/drop`")

    if cur.rowcount > 1:
        con.rollback()
        await ctx.reply(f":question:`{toon.capitalize()}` corresponds to more than one character. Please ask Rahmani for help. `Error 5`")
        

@client.command()
async def ding(ctx, toon):
    try:
        engine = sqlalchemy.create_engine(config.db_url, echo=False)
        census = pd.read_sql_table("census", con=engine)
        engine.dispose()

        toon_data = census.loc[census["name"] == toon.capitalize()]

        if toon_data.empty:
            await ctx.reply(content=":x: The specified toon was not found.")
            return

        current_level = toon_data['level'].iloc[0]
        new_level = current_level + 1

        # Invoke the level command with the new level
        await ctx.invoke(client.get_command('level'), toon=toon, level=str(new_level))

    except Exception as e:
        await ctx.reply(content=f":x: An error occurred: {str(e)}")


async def get_toons_data(discord_id, toon=None):
    engine = sqlalchemy.create_engine(config.db_url, echo=False)
    try:
        dkp = pd.read_sql_table("dkp", con=engine)
        census = pd.read_sql_table("census", con=engine)
    except sqlalchemy.exc.NoSuchTableError:
        return None, ":x: The required tables are not present in the database."
    finally:
        engine.dispose()

    if toon is None:
        toons = census.loc[census["discord_id"] == str(discord_id)]
    else:
        toon_ids = census.loc[census["name"] == toon.capitalize()]
        toons = census.loc[census["discord_id"].isin((toon_ids['discord_id']))]
        discord_id = toons['discord_id'].iloc[0] if not toons.empty else None

    return discord_id, toons

def create_toons_embed(owner, toons):
    main_toons = toons[toons['status'] == "Main"]
    alt_toons = toons[toons['status'] == "Alt"]
    bot_toons = toons[toons['status'] == "Bot"]

    toons_list = discord.Embed(
        title=f":book:Census data entry for {owner.display_name if owner else 'Unknown User'}",
        description="DKP can be spent on all toons,\nbut only earned on toons over 45.",
        colour=discord.Colour.from_rgb(241, 196, 15))

    def add_toons_to_embed(embed, toons, status):
        if len(toons) > 0:
            embed.add_field(
                name=status,
                value=f"{len(toons)} character(s) declared as {status.lower()}s",
                inline=False)

            embed.add_field(
                name=":bust_in_silhouette: Name",
                value="```\n" + "\n".join(toons.name.tolist()) + "\n```",
                inline=True)

            embed.add_field(
                name=":crossed_swords:️ Class",
                value="```\n" + "\n".join(toons.character_class.tolist()) + "\n```",
                inline=True)

            embed.add_field(
                name=":arrow_double_up: Level",
                value="```\n" + "\n".join(map(str, toons.level.tolist())) + "\n```",
                inline=True)


    add_toons_to_embed(toons_list, main_toons, "Main")
    add_toons_to_embed(toons_list, alt_toons, "Alt")
    add_toons_to_embed(toons_list, bot_toons, "Bot")

    toons_list.set_footer(text="Fetched at local time")
    toons_list.timestamp = datetime.datetime.now(pytz.timezone('US/Pacific'))

    return toons_list

@client.command()
async def toons(ctx, toon=None):
    try:
        discord_id, toons = await get_toons_data(ctx.author.id, toon)

        if toons is None:
            await ctx.reply(content=":x: The required tables are not present in the database.")
            return

        owner = ctx.guild.get_member(int(discord_id)) if discord_id is not None else None
        toons_list = create_toons_embed(owner, toons)

        if owner is not None:
            await ctx.reply(content=f":mag: {owner.mention}'s toons include:", embed=toons_list)
        else:
            await ctx.reply(content=":warning: User not found. Please check the toon name and try again.", embed=toons_list)
    except Exception as e:
        await ctx.reply(content=f":x: An error occurred: {str(e)}")


async def get_dkp_data(discord_id, toon=None):
    engine = sqlalchemy.create_engine(config.db_url, echo=False)
    dkp = pd.read_sql_table("dkp", con=engine)
    census = pd.read_sql_table("census", con=engine)

    if toon is not None:
        toon = toon.capitalize()
        toon_owner = census[census.name == toon][['discord_id']]
        discord_id = toon_owner['discord_id'].iloc[0] if not toon_owner.empty else None

    # Fetch the DKP data associated with the found discord_id
    dkp_dict = dkp[dkp.discord_id == discord_id].copy()  # make an explicit copy
    dkp_dict["current_dkp"] = dkp_dict["earned_dkp"] - dkp_dict["spent_dkp"]

    return discord_id, dkp_dict




def create_dkp_embed(user, dkp_dict):
    embed = discord.Embed(
        title=f":dragon: DKP for `{user.display_name if user else 'Unknown User'}`",
        description="DKP can be spent on all toons, but only earned on toons over 45.",
        colour=discord.Colour.from_rgb(241, 196, 15))

    embed.add_field(
        name=":arrow_up:️ Current DKP",
        value=f"```\n{dkp_dict['current_dkp'].to_string(index=False).strip()}\n```",
        inline=True)

    embed.add_field(
        name=":moneybag: Total Earned",
        value=f"```\n{dkp_dict['earned_dkp'].to_string(index=False).strip()}\n```",
        inline=True)

    embed.set_footer(
        text="Fetched at local time")

    embed.timestamp = datetime.datetime.now(pytz.timezone("US/Pacific"))

    return embed

@client.command()
async def dkp(ctx, toon=None):
    discord_id, dkp_dict = await get_dkp_data(str(ctx.message.guild.get_member_named(str(ctx.author)).id), toon)

    if not dkp_dict.empty:
        user = ctx.guild.get_member(int(discord_id)) if discord_id is not None else None
        dkp_embed = create_dkp_embed(user, dkp_dict)
        await ctx.reply(content=f":mag: {user.mention}'s DKP:", embed=dkp_embed)
    else:
        await ctx.reply(content=":question: No census entry was found. Check `!toons`.")



@client.command()
@commands.has_role("Officer")
async def logs(ctx, *, args):

    census = pd.read_sql_query('SELECT * FROM census', con)
    dkp = pd.read_sql_query('SELECT * FROM dkp', con)
    raids = pd.read_sql_query('SELECT * FROM raids', con)

    # timestamp
    re1 = '(?<=^\[).*?(?=])'
    # level class
    re2 = '(?<=(?<!^)\[).*?(?=\])'
    # name
    re3 = '(?<=] )[^[]+?(?=[ <(])'
    # guild
    re4 = '(?<=<).*?(?=>)'

    raid = titlecase(args.splitlines()[0])

    # retrieve entire tables from SQLite
    # query how much this raid is worth
    modifier = raids.loc[raids['raid'] == raid, 'modifier']

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


        line = re.compile("(%s|%s|%s|%s)" %
                          (re1, re2, re3, re4)).findall(record)

        timestamp = line[0]

        timestamp = datetime.datetime.strptime(
            timestamp, '%a %b %d %H:%M:%S %Y')

        timestamp = datetime.datetime.strftime(timestamp, '%Y-%m-%d %H:%M:%S')

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
            player_class = player_classes.loc[player_classes["class_name"]
                                              == level_class[1], "character_class"].item()

        elif len(level_class) == 3:
            level = level_class[0]
            player_class = player_classes.loc[player_classes["class_name"]
                                              == f"{level_class[1]} {level_class[2]}", "character_class"].item()

        sql_response = "INSERT INTO attendance (date, raid, name, discord_id, modifier) VALUES (?, ?, ?, ?, ?);"

        cur.execute(sql_response, (timestamp, raid, name, discord_id, modifier))

        if cur.rowcount == 1:
            con.commit()

        else:
            await ctx.reply(f"Something is wrong with the record: {record}")
            con.rollback()

        sql_response = "UPDATE dkp SET earned_dkp = earned_dkp + ? WHERE discord_id == ?;"
        cur.execute(sql_response, (modifier, discord_id))
        # await ctx.reply(sql_response)

        if cur.rowcount == 1:
            con.commit()

        else:
            await ctx.reply(f":exclamation:Something is wrong with the record: `{record}`")
            con.rollback()

    if len(seen_players) > 0:
        await ctx.reply(f":dragon:{', '.join(seen_players)} earned `{modifier}` DKP for `{raid}` this hour.")
        await ctx.message.add_reaction("✅")

        if is_reply:
            await message.add_reaction("✅")


    if len(rejected) > 0:
        sep = "\n"

        rejected = sep.join(rejected)
        rejected = re.sub("```", "", rejected)
        # get rid of the extra triple backticks

        await ctx.reply(f":question:Some logs got rejected, since these players are not registered. ```\n{rejected}\n```")
        await ctx.message.add_reaction("❌")

        if is_reply:
            await message.add_reaction("❌")


@client.command()
@commands.has_role("Officer")
async def welcome(ctx):

    embed = discord.Embed(
        title="Welcome to the guild! ",
        description=":wave:We’re glad to have you. ")

    embed.add_field(
        name=":one: Fill out a guild application",
        value="<#988260644056879194>\nAfter filling out an application ([click here](https://discord.com/channels/838976035575562293/988260644056879194/988260816144973835), type `!apply` (and nothing else) in a new message to formally submit your application.\n Once and if you are approved, you may move onto the next steps.",
        inline=False)

    embed.add_field(
        name=":two: Declare your main",
        value="<#851549677815070751>\n Some useful commands include: `!main <character name> <level> <class>`, `!toons`, `!dkp`",
        inline=False)

    embed.add_field(
        name=":three: Join the Aegis Alliance Server",
        value="[Aegis Discord](https://discord.gg/CS2j2KJYPC)",
        inline=False)

    embed.add_field(
        name=":four: Register on Aegis Webiste",
        value="[Aegis Website](https://aegisrap.com).\nThis is how you'll be able to keep track of your RAP (Raid Attendance Points) for Aegis Alliance Raids.",
        inline=False)

    embed.add_field(
        name=":five: Have a question?",
        value=":man_raising_hand:Write it in the <#864599563204296724> channel!",
        inline=False)

    embed.add_field(
        name=":six: Need to talk to an officer?",
        value="Tag an officer using <@&849337092324327454> in the <#838976036167090247> or other text channels.",
        inline=False)

    embed.add_field(
        name=":seven: Events",
        value="<#870938136472088586>, <#851872447057100840>, and <#856424309026979870> channels for upcoming events",
        inline=False)

    embed.add_field(
        name=":eight: Epics",
        value="Check our <#851834766302249020> channel if you need assistance with your epic",
        inline=False)

    await ctx.send(embed=embed)


@client.command()
async def sanctum(ctx, toon=None):

    import os
    st = os.stat('rap.html')
    mtime = st.st_mtime

    current_time = datetime.datetime.now()

    elapsed = current_time - datetime.datetime.fromtimestamp(mtime)
    elapsed = chop_microseconds(elapsed)

    if elapsed < datetime.timedelta(minutes = 60):
        RAP_age = f"RAP synced {str((elapsed))} ago."

    elif elapsed >= datetime.timedelta(minutes = 1):
        subprocess.call(['sh', './aegis_readme.sh'])
        current_time = datetime.datetime.now()
        st = os.stat('rap.html')
        mtime = st.st_mtime
        elapsed = current_time - datetime.datetime.fromtimestamp(mtime)
        elapsed = chop_microseconds(elapsed)
        RAP_age = f"RAP synced {str((elapsed))} ago."

    census = pd.read_sql_query('SELECT * FROM census', con)

    rap_totals = pd.read_html('rap.html')

    rap_totals = rap_totals[16][['Name', 'Unnamed: 6']]
    print(rap_totals.to_string())
    rap_totals['Name'] = rap_totals['Name'].str.capitalize()
    rap_totals.columns = ['Name', 'RAP']

    if toon == None:
        user_name = format(ctx.author)
        discord_id = str(ctx.message.guild.get_member_named(user_name).id)

    if toon != None:
        toon = toon.capitalize()
        user_name = format(toon)
        discord_id = census.loc[census['name'] == toon, 'discord_id'].item()

    inner_merged = pd.merge(
        rap_totals, census, left_on="Name", right_on="name", how="inner")

    inner_merged = inner_merged[['discord_id', 'name', 'RAP']]

    inner_merged = inner_merged.sort_values(by=['name'])

    rap_totals = inner_merged.loc[inner_merged['discord_id'] == discord_id]

    rap_list = discord.Embed(
        title=f":dragon:Sanctum DKP for `{user_name}`",
        description="Consult the [Sanctum Website](https://p99sanctum.com) for rules and declarations. Sanctum DKP may be inconsistent between, depending on your character declarations. Ex Astra does not have control over Sanctum DKP.",
        colour=discord.Colour.from_rgb(241, 196, 15))

    rap_list.add_field(
        name="Character Declaration",
        value=f"{len(rap_totals)} linked main character(s) with DKP are declared in Sanctum.",
        inline=False)

    if len(rap_totals) > 0:
        rap_list.add_field(
            name=":bust_in_silhouette: Name",
            value="```\n" + "\n".join(rap_totals.name.tolist()) + "\n```",
            inline=True)

        rap_list.add_field(
            name=":arrow_up:️ Current Sanctum DKP",
            value="```\n" + "\n".join(map(str, rap_totals.RAP.tolist())) + "\n```",
            inline=True)

    rap_list.set_footer(text=RAP_age)

    await ctx.reply(embed=rap_list)


@client.command()
@commands.has_role("Treasurer")
async def bank(ctx):

    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    engine = sqlalchemy.create_engine(config.db_url, echo=False)

    attachment = ctx.message.attachments[0]
    banker_name = Path(attachment.url).stem.split("-")[0]
    inventory_keyword = Path(attachment.url).stem.split("-")[1]

    await ctx.reply(f"Parsing `{inventory_keyword}` for `{banker_name}`")

    req = Request(attachment.url, headers={'User-Agent': 'Mozilla/5.0'})
    stream = urlopen(req).read()
    inventory = pd.read_csv(io.StringIO(stream.decode('utf-8')), sep="\t")

    inventory = inventory.rename(
        columns={
            'Location': 'location',
            'Name': 'name',
            'ID': 'eq_item_id',
            'Count': 'quantity',
            'Slots': 'slots'})


    inventory.insert(0, "Banker", banker_name)

    inventory.insert(0, "Time", current_time)

    sql_response = "DELETE FROM bank WHERE banker == ?"

    cur.execute(sql_response, (banker_name, ))
    con.commit()

    inventory.to_sql("bank", engine, if_exists="append", index=False)

async def fetch_bank_items(name):
    engine = sqlalchemy.create_engine(config.db_url, echo=False)
    bank = pd.read_sql_table("bank", con=engine)
    trash = pd.read_sql_table("trash", con=engine)
    bank = bank[~bank['name'].isin(trash['name'])]

    bank["name"] = bank["name"].apply(titlecase)
    bank["name"] = bank["name"].str.replace("`", "'")

    return bank[bank["name"].str.contains(name)][["id", "banker", "name", "location", "quantity", "time"]]

def build_search_embed(name, banker, banker_results):
    search_embed = discord.Embed(
        title=f":gem: Treasury Query for `{name}`",
        description=f"Found on `{banker}`",
        colour=discord.Colour.from_rgb(241, 196, 15))

    search_embed.add_field(
        name="Item Characteristics",
        value=f"{len(banker_results)} matching item(s) found.",
        inline=False)

    search_embed.add_field(
        name=":bust_in_silhouette: Item",
        value="```\n" + "\n".join(banker_results.name.tolist()) + "\n```",
        inline=True)

    search_embed.add_field(
        name=":question: Location",
        value="```\n" + "\n".join(banker_results.location.tolist()) + "\n```",
        inline=True)

    search_embed.add_field(
        name=":arrow_up:️ Quantity",
        value="```\n" + "\n".join(map(str, banker_results.quantity.tolist())) + "\n```",
        inline=True)

    search_embed.set_footer(text="Fetched at local time")
    search_embed.timestamp = datetime.datetime.now(pytz.timezone('US/Pacific'))

    return search_embed

@client.command()
async def find(ctx, *, name):
    try:
        original_name = titlecase(name)
        search_results = await fetch_bank_items(original_name)

        if search_results.empty:
            await ctx.reply(f"None of the bankers currently have `{original_name}`.")
        else:
            unique_bankers = search_results["banker"].unique()
            for i in unique_bankers:
                banker_results = search_results.loc[search_results["banker"] == i]
                search_embed = build_search_embed(original_name, i, banker_results)
                await ctx.reply(embed=search_embed)
    except Exception as e:
        await ctx.reply(content=f":x: An error occurred: {str(e)}")


@client.command()
@commands.has_role("Treasurer")
async def banktotals(ctx):

    engine = sqlalchemy.create_engine(config.db_url, echo=False)
    bank = pd.read_sql_table("bank", con=engine)
    trash = pd.read_sql_table("trash", con=engine)
    bank = bank[~bank['name'].isin(trash['name'])]

    current_time = datetime.datetime.now().strftime("%Y-%m-%d-%H-%M-%S")

    banktotals_file = "banktotals-" + current_time + ".txt"

    banktotals = bank.groupby(['name'])['quantity'].sum().to_frame()

    banktotals = tabulate(banktotals, headers="keys", tablefmt="psql")

    f = open(banktotals_file, "w")
    f.write(banktotals)
    f.close()

    await ctx.reply(f':moneybag:Here is a text file with all the bank totals.', file=discord.File(banktotals_file))
    os.remove(banktotals_file)
    return

@client.command()
async def bidhistory(ctx):

    engine = sqlalchemy.create_engine(config.db_url, echo=False)
    discord_id = str(ctx.message.guild.get_member_named(format(ctx.author)).id)
    items = pd.read_sql_table("items", con=engine)
    items = items.loc[items['discord_id'] == discord_id]
    items = items[["name", "date", "item", "dkp_spent"]]
    items = items.reset_index(drop=True)

    current_time = datetime.datetime.now().strftime("%Y-%m-%d-%H-%M-%S")

    items_file = "bids-" + current_time + discord_id +".txt"

    bidtotals = tabulate(items, headers="keys", tablefmt="psql")

    f = open(items_file, "w")
    f.write(bidtotals)
    f.close()

    await ctx.reply(f':moneybag:Here is a text file with your bid history.', file=discord.File(items_file))
    os.remove(items_file)
    return

@client.command()
async def dkphistory(ctx):

    engine = sqlalchemy.create_engine(config.db_url, echo=False)
    discord_id = str(ctx.message.guild.get_member_named(format(ctx.author)).id)
    attendance = pd.read_sql_table("attendance", con=engine)
    attendance = attendance.loc[attendance['discord_id'] == discord_id]
    attendance = attendance[["name", "date", "raid", "modifier"]]
    items = attendance.reset_index(drop=True)

    current_time = datetime.datetime.now().strftime("%Y-%m-%d-%H-%M-%S")

    dkp_file = "earnings-" + current_time + discord_id +".txt"

    earntotals = tabulate(items, headers="keys", tablefmt="psql")

    f = open(dkp_file, "w")
    f.write(earntotals)
    f.close()

    await ctx.reply(f':moneybag:Here is a text file with your earnings history.', file=discord.File(dkp_file))
    os.remove(dkp_file)
    return

@client.command()
async def who(ctx, level, optional_max_level=None, player_class=None):
    level, max_level, player_class = validate_and_process_input(ctx, level, optional_max_level, player_class)
    if level is None:
        return
    matching_toons = fetch_matching_toons(level, max_level, player_class)
    if len(matching_toons) == 0:
        await reply_no_matching_toon(ctx, level, max_level, player_class)
    else:
        await reply_matching_toons(ctx, matching_toons, level, max_level, player_class)

def validate_and_process_input(ctx, level, optional_max_level, player_class):
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

    return level, max_level, get_player_class(player_class) if player_class is not None else None

def fetch_matching_toons(level, max_level, player_class):
    Base = automap_base()
    engine = create_engine(config.db_url)
    Base.prepare(engine, reflect=True)

    Attendance = Base.classes.attendance
    Census = Base.classes.census

    session = Session(engine)

    toon_q = session.query(Census).\
        filter(Census.character_class == player_class).\
        filter(Census.level >= level).\
        filter(Census.level <= max_level).\
        filter(Census.status != "Dropped").\
        join(Attendance, Attendance.discord_id == Census.discord_id).\
        having(func.max(Attendance.date)).group_by(Attendance.discord_id).\
        order_by(Attendance.date.desc())

    return pd.read_sql(toon_q.statement, toon_q.session.bind)[['name', 'discord_id', 'level']]

async def reply_no_matching_toon(ctx, level, max_level, player_class):
    if max_level == level:
        await ctx.reply(f"There were no level {level} {player_class}s found.")
    else:
        await ctx.reply(f"There were no level {level} to {max_level} {player_class}s found.")

async def reply_matching_toons(ctx, matching_toons, level, max_level, player_class):
    guild = ctx.guild
    names = []
    mentions = []
    left_server_names = []

    for _, row in matching_toons.iterrows():
        name = row["name"]
        discord_id = row["discord_id"]
        level = row["level"]
        member = guild.get_member(int(discord_id))

        if member is not None:
            names.append(name)
            if level == max_level or level == level:
                mentions.append((discord_id, level))
            else:
                mentions.append((discord_id, f"{level}-{max_level}"))
        else:
            left_server_names.append(name)

    embed = discord.Embed(
        title=f":white_check_mark: Registered level {level} to {max_level} {player_class}s",
        description="Sorted by most recently earned DKP on any character.",
        colour=discord.Colour.from_rgb(241, 196, 15))

    embed.add_field(
        name=":bust_in_silhouette: Name",
        value="".join([f"`{name}`\n" for name in names]),
        inline=True)

    embed.add_field(
        name=":busts_in_silhouette: Discord",
        value="".join([f"`{' ' if level < 10 else ''}{mention[1]}`<@{mention[0]}>\n" for mention in mentions]),
        inline=True)

    if left_server_names:
        left_server_names_str = ", ".join(left_server_names)
        embed.set_footer(text=f"The following characters appear not to belong to this server anymore:\n{left_server_names_str}")

    await ctx.reply(embed=embed)


@client.command()
async def claim(ctx, toon):

    toon = toon.capitalize()
    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    discord_id = ctx.message.guild.get_member_named(format(ctx.author)).id

    Base = automap_base()
    engine = create_engine(config.db_url)
    Base.prepare(engine, reflect=True)
    Census = Base.classes.census
    session = Session(engine)

    claimed_toon = session.query(Census).filter(Census.name == toon).one()

    old_owner = claimed_toon.discord_id

    if claimed_toon.status == "Bot":

        claimed_toon.discord_id = discord_id

        claimed_toon.time = current_time

        session.commit()

        await ctx.reply(f":white_check_mark:<@{discord_id}> has taken control of `{toon}` from <@{old_owner}>." )

    if claimed_toon.status != "Bot":

        await ctx.reply(f":exclamation:`{toon}` can only change ownership if <@{old_owner}> declares the toon as a `!bot`." )


@client.command()
@commands.has_role("DUMMY")
async def event(ctx):
    return


@client.event
async def on_command_error(ctx, error):

    print(f"Error author:  {ctx.author}")
    print(f"Error message: {ctx.message.content}")

    if isinstance(error, CommandNotFound):
        await ctx.reply(f':question:Command not found \nSee `!help`')
        return

    if isinstance(error, commands.NoPrivateMessage):
        await ctx.reply(f':question:This command must be used in a public channel')
        return

    if isinstance(error, commands.MissingRequiredArgument) or isinstance(error, commands.BadArgument):
        command = ctx.message.content.split()[0]
        await ctx.reply(f':question:Missing some information. \nSee `!help {command[1:]}`')
        return

    if isinstance(error, commands.MissingRole):
        await ctx.reply(f':question:Command reserved for a different role \nSee `!help`')
        return

    raise error

@client.command()
async def raid_roles(ctx, toon=None):

    engine      = sqlalchemy.create_engine(config.db_url, echo=False)
    census      = pd.read_sql_table("census", con=engine)
    class_roles = pd.read_sql_table("class_roles", con=engine)
    census      = pd.merge(census, class_roles, on = "character_class")


    if toon == None:
        discord_id = ctx.message.guild.get_member_named(format(ctx.author)).id
        toons = census.loc[census["discord_id"] == str(discord_id)]

    else:
        toon_ids = census.loc[census["name"] == toon.capitalize()]
        discord_id = toon_ids['discord_id'].item()
        toons    = census.loc[census["discord_id"].isin((toon_ids['discord_id']))]

    member = await ctx.guild.fetch_member(discord_id)


    raid_toons = toons[toons['level'] > 45]
    raid_roles = raid_toons["role_id"].to_list()
    raid_roles = list(set(raid_roles))

    for role in raid_roles:

        this_role = ctx.guild.get_role(role)
        await member.add_roles(this_role)

    await ctx.reply(f":white_check_mark:<@{discord_id}> now has `{len(raid_roles)}` raid roles.")


###########

async def remove_item_from_bank(id):
    Base = automap_base()
    engine = create_engine(config.db_url)
    Base.prepare(engine, reflect=True)
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


import asyncio

def build_sell_embed(name, banker, banker_results):
    search_embed = discord.Embed(
        title=f":gem: Treasury Query for `{name}`",
        description=f"Found on `{banker}`",
        colour=discord.Colour.from_rgb(241, 196, 15))

    search_embed.add_field(
        name="Item Characteristics",
        value=f"{len(banker_results)} matching item(s) found.",
        inline=False)

  
    search_embed.add_field(
        name=":1234: ID",
        value="```\n" + "\n".join(banker_results.id.astype(str).tolist()) + "\n```",
        inline=True)

    search_embed.add_field(
        name=":bust_in_silhouette: Item",
        value="```\n" + "\n".join(banker_results.name.tolist()) + "\n```",
        inline=True)

    search_embed.add_field(
        name=":arrow_up:️ Quantity",
        value="```\n" + "\n".join(map(str, banker_results.quantity.tolist())) + "\n```",
        inline=True)

    search_embed.set_footer(text="Fetched at local time")
    search_embed.timestamp = datetime.datetime.now(pytz.timezone('US/Pacific'))

    return search_embed

@client.command()
async def sell2(ctx, *, name):
    try:
        original_name = titlecase(name)
        search_results = await fetch_bank_items(original_name)

        if search_results.empty:
            await ctx.reply(f"None of the bankers currently have `{original_name}`.")
        else:
            unique_bankers = search_results["banker"].unique()
            for i in unique_bankers:
                banker_results = search_results.loc[search_results["banker"] == i]
                search_embed = build_sell_embed(original_name, i, banker_results)
                await ctx.reply(embed=search_embed)
    except Exception as e:
        await ctx.reply(content=f":x: An error occurred: {str(e)}")

import re

@client.command()
@commands.has_role("Officer")
async def sell(ctx, *, item_name):
    global pending_sell

    original_name = titlecase(item_name)
    search_results = await fetch_bank_items(original_name)

    if search_results.empty:
        await ctx.reply(f"🚫 None of the bankers currently have `{original_name}`.")
    else:
        await ctx.reply("🔢 Please select the item IDs you've sold by entering the numbers.\nEnter `0` to cancel the operation.")
        try:
            if search_results.empty:
                await ctx.reply(f"🚫 None of the bankers currently have `{original_name}`.")
            else:
                unique_bankers = search_results["banker"].unique()
                for i in unique_bankers:
                    banker_results = search_results.loc[search_results["banker"] == i]
                    search_embed = build_sell_embed(original_name, i, banker_results)
                    await ctx.reply(embed=search_embed)

        except Exception as e:
            await ctx.reply(content=f":x: An error occurred: {str(e)}")

        def check(m):
            return m.author == ctx.author and all(part.isdigit() for part in re.split('\W+', m.content))

        try:
            msg = await client.wait_for('message', check=check, timeout=60)
            numbers = [int(part) for part in re.split('\W+', msg.content) if part.isdigit()]
            if 0 in numbers:
                await ctx.reply("❌ Operation canceled.")
                return
            successful_ids, failed_ids = [], []
            for number in numbers:
                remove_success = await remove_item_from_bank(number)
                if remove_success:
                    successful_ids.append("`" + str(number) + "`")
                else:
                    failed_ids.append("`" + str(number) + "`")
            responses = []
            if successful_ids:
                responses.append(f"🔨 Item number(s) {', '.join(successful_ids)} sold!")
            if failed_ids:
                responses.append(f"🚫 There was a problem removing product ID(s): `{', '.join(failed_ids)}` from the bank.")
            await ctx.reply("\n".join(responses))
        except asyncio.TimeoutError:
            await ctx.reply("❌ Sell operation canceled due to inactivity.")



client.run(config.token)
