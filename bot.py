#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Imports
from sqlalchemy import create_engine
import config
import datetime
import discord
import gspread
import io
import pandas as pd
import re
import requests
import time
import pytz
import sqlite3
import sqlalchemy
import subprocess

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from config import token, prefix, ownerid
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

con = sqlite3.connect('ex_astra.db')
con.execute('PRAGMA foreign_keys = ON')
cur = con.cursor()

player_classes = pd.read_sql_query('SELECT * FROM class_definitions', con)
raids = pd.read_sql_query('SELECT * FROM raids', con)

DISCORD_TOKEN = token

intents = discord.Intents.default()
intents.members = True

# Create bot
client = commands.Bot(
    command_prefix=prefix,
    case_insensitive=True,
    intents=intents)

def get_player_class(player_class):
    player_class = titlecase(player_class)
    player_class_names = player_classes['Class_name'].to_list()
    player_class_name = gcm(player_class, player_class_names, n=1, cutoff=0.5)

    if len(player_class_name) == 0:
        raise CensusError("Error")
        return

    else:
        player_class_name = player_class_name[0]
        player_class = player_classes.loc[player_classes['Class_name']
                                          == player_class_name, 'Class'].item()
        return (player_class)

def get_level(level):
    if level < 0 or level > 60:
        raise CensusError("Error")
        return
    else:
        return (level)

# Startup Information
@client.event
async def on_ready():
    print('Connected to bot:{}'.format(client.user.name))

    print('Bot ID:{}'.format(client.user.id))

@client.command()
async def ping(ctx):
    pingtime = time.time()

    pingms = await ctx.reply("Pinging...")

    ping = time.time() - pingtime

    await ctx.reply(":ping_pong: time is `%.01f seconds`" % ping)

@client.command()
@commands.has_role("lootmaster")
async def deduct(ctx, amount: int, name, *, args):
    census = pd.read_sql_query('SELECT * FROM census', con)
    dkp = pd.read_sql_query('SELECT * FROM dkp', con)

    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    name = titlecase(name)

    if len(census.loc[census["Name"] == name, "ID"]) == 0:
        await ctx.reply(f":exclamation:No character named `{name}` was found.")
        # this is an error
        return

    discord_ID = census.loc[census["Name"] == name, "ID"].item()

    earned_dkp = dkp.loc[dkp["ID"] == discord_ID, "Earned_DKP"].item()

    spent_dkp = dkp.loc[dkp["ID"] == discord_ID, "Spent_DKP"].item()

    current_dkp = earned_dkp - spent_dkp

    if current_dkp >= amount:
        cur.execute('INSERT INTO items (Name, Item, DKP, Date, ID) VALUES (?, ?, ?, ?, ?);',
                    (name.capitalize(), titlecase(args), amount, current_time, discord_ID))

        if cur.rowcount == 1:
            cur.execute('UPDATE dkp SET Spent_DKP = Spent_DKP + ? WHERE ID = ?;',
                        (str(amount), discord_ID))

            if cur.rowcount == 1:
                con.commit()

                await ctx.reply(f":white_check_mark:<@{discord_ID}> spent `{amount}` DKP on `{titlecase(args)}` for `{name.capitalize()}`!")

            else:
                con.rollback()

                await ctx.reply(f":question:Something weird happened, ask Rahmani. `Error -2`")

        else:
            con.rollback()

            await ctx.reply(f":question:Something weird happened, ask Rahmani. `Error -1`")

    else:
        await ctx.reply(f":exclamation:`{amount}` is greater than `{name.capitalize()}`'s current total of `{current_dkp}` DKP\nNo action taken")

########################################################################################################
async def declare_toon(ctx, status, toon, level: int = None, player_class: str = None, user_name: str = None):
    census = pd.read_sql_query('SELECT * FROM census', con)
    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    discord_id = ctx.message.guild.get_member_named(user_name).id

    if player_class is not None:
        player_class = get_player_class(player_class)

    cur.execute('SELECT * FROM census WHERE Name == ?;', (toon.capitalize(),))

    col_names = list(map(lambda x: x[0], cur.description))

    rows = cur.fetchall()

    cur.execute('SELECT * FROM dkp WHERE ID == ?;', (discord_id,))

    col_names = list(map(lambda x: x[0], cur.description))

    discord_exists = cur.fetchall()

    # if the discord account was not found
    if len(discord_exists) == 0:

        discord_id = ctx.message.guild.get_member_named(user_name).id

        cur.execute('INSERT INTO dkp (Discord, Earned_DKP, Spent_DKP, Date_Joined, ID) VALUES (?, 5, 0, ?, ?);',
                    (user_name, current_time, discord_id))

        if cur.rowcount == 1:
            con.commit()

            channel = client.get_channel(884164383498965042)

            member = ctx.message.guild.get_member_named(user_name)

            role = ctx.guild.get_role(884172643702546473)  # come back to this

            await member.add_roles(role)

            formatted_id = f'<@{discord_id}>'

            await channel.send(f"<@&849337092324327454> `{toon}` just joined the server using the discord handle {formatted_id} and is now a probationary member.")

        else:
            con.rollback()

            await ctx.reply(f":question:Something weird happened, ask Rahmani. `Error 0`")

    # if the character was found
    # if len(rows) > 1:
    #     await ctx.reply("This is a shared character. Demographics cannot be changed currently.")

    if len(rows) == 1:

        if level is None:

            cur.execute('UPDATE Census SET Status = ?, Time = ? WHERE Name = ?;',
                        (status.capitalize(), current_time, toon.capitalize()))

            if cur.rowcount == 1:

                con.commit()

                await ctx.reply(f":white_check_mark:`{toon.capitalize()}` is now `{status}`")

            else:

                con.rollback()

                await ctx.reply(f":question:Something weird happened, ask Rahmani. `Error 1`")

        if level is not None:

            if player_class is None:

                cur.execute('UPDATE Census SET Status = ?, Level = ?, Time = ? WHERE Name = ?;',
                            (status.capitalize(), level, current_time, toon.capitalize()))

                if cur.rowcount == 1:

                    con.commit()

                    await ctx.reply(f":white_check_mark:`{toon.capitalize()}` is now `{status}` and level `{level}`")

                else:

                    con.rollback()

                    await ctx.reply(f":question:Something weird happened, ask Rahmani. `Error 2`")

            if player_class is not None:

                cur.execute('UPDATE Census SET Status = ?, Level = ?, Class = ?, Time = ? WHERE Name = ?;',
                            (status.capitalize(), level, player_class, current_time, toon.capitalize()))

                if cur.rowcount == 1:

                    con.commit()

                    await ctx.reply(f":white_check_mark:`{toon.capitalize()}` is now a level `{level}` `{player_class}` `{status}`")

                else:
                    con.rollback()

                    await ctx.reply(f":question:Something weird happened, ask Rahmani. `Error 3`")

    if len(rows) == 0:

        if player_class is None or level is None:

            await ctx.reply(f":question:`{toon.capitalize()}` was not found\nSee `!help main/alt/drop`")

        else:

            cur.execute('INSERT INTO census (Name, Level, Class, ID, Status, Time) VALUES (?, ?, ?, ?, ?, ?);',
                        (toon.capitalize(), level, player_class, discord_id, status.capitalize(), current_time))

            if cur.rowcount == 1:

                con.commit()

                await ctx.reply(f":white_check_mark:`{toon.capitalize()}` was created and is now a level `{level}` `{player_class}` `{status}`")

            else:
                con.rollback()
                await ctx.reply(f":question:Something weird happened, ask Rahmani. `Error 4`")


@client.command()
@commands.has_role("officer")
async def promote(ctx, name):

    name = titlecase(name)
    census = pd.read_sql_query('SELECT * FROM census', con)
    dkp = pd.read_sql_query('SELECT * FROM dkp', con)
    discord_ID = census.loc[census["Name"] == name, "ID"].item()

    channel = client.get_channel(851549677815070751)  # census chat
    member = await ctx.guild.fetch_member(discord_ID)
    probationary_role = ctx.guild.get_role(
        884172643702546473)  # come back to this
    member_role = ctx.guild.get_role(870669705646587924)

    await member.remove_roles(probationary_role)
    await member.add_roles(member_role)

    await ctx.reply(f"<@&849337092324327454> Send your congrats to <@{discord_ID}>, the newest full member of Ex Astra!")
    await channel.send(f"<@&870669705646587924> Send your congrats to <@{discord_ID}>, the newest full member of Ex Astra!")


@client.command()
@commands.has_role("officer")
async def assign(ctx, toon, level: int, player_class, user_name):

    await declare_toon(ctx, "None", toon, level, player_class, user_name)


@client.command()
async def main(ctx, toon, level: int = None, player_class: str = None):

    toon = titlecase(toon)

    census = pd.read_sql_query('SELECT * FROM census', con)

    toon_discord_ID = census.loc[census["Name"] == toon, "ID"]

    if len(toon_discord_ID) > 0:
        toon_discord_ID = toon_discord_ID.item()
        toon_mains = census.loc[(census['ID'] == toon_discord_ID) & (
            census['Status'] == "Main") & (census['Name'] != toon), 'Name'].to_list()

        for i in toon_mains:
            await alt(ctx, i)

    else:
        user_discord_ID = str(
            ctx.message.guild.get_member_named(format(ctx.author)).id)
        user_mains = census.loc[(census['ID'] == user_discord_ID) & (
            census['Status'] == "Main") & (census['Name'] != toon), 'Name'].to_list()

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
    cur.execute("SELECT DISTINCT Name from census WHERE Status == ? and Name == ?;",
                ('Dropped', toon.capitalize()))
    rows = cur.fetchall()

    # determine if the character's toon has already been dropped
    if len(rows) > 0:
        await ctx.reply(f":question:`{toon.capitalize()}` was not found\nSee `!help main/alt/drop`")

    else:
        await declare_toon(ctx, "Dropped", toon, level, player_class, user_name)


@client.command()
async def level(ctx, toon, level):

    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if (has_numbers(toon) == True) or (has_numbers(level) == False):
        await ctx.reply(f"Try `!level <toon> <level>`. Also make sure {toon} has been registered with `!main` or `!alt`.")
        return

    cur.execute('UPDATE Census SET Level = ?, Time = ? WHERE Name = ?;',
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
async def toons(ctx, toon=None):

    engine     = sqlalchemy.create_engine('sqlite:///ex_astra.db', echo=False)
    discord_id = ctx.message.guild.get_member_named(format(ctx.author)).id
    dkp        = pd.read_sql_table("dkp", con=engine)
    census     = pd.read_sql_table("census", con=engine)

    if toon == None:
        toons = census.loc[census["ID"] == str(discord_id)]

    else:
        toon_ids = census.loc[census["Name"] == toon.capitalize()]
        toons    = census.loc[census["ID"].isin((toon_ids['ID']))]

    col_names  = toons.columns
    main_toons = toons[toons['Status'] == "Main"]
    alt_toons  = toons[toons['Status'] == "Alt"]
    bot_toons  = toons[toons['Status'] == "Bot"]

    toons_list = discord.Embed(
        title=f":book:Census data entry",
        description="DKP can be spent on all toons,\nbut only earned on toons over 45.",
        colour=discord.Colour.from_rgb(241, 196, 15))

    if len(main_toons) > 0:
        toons_list.add_field(
            name="Main",
            # value=f"{len(main_toons)} character(s) declared as mains",
            value=f"Character declared as main",
            inline=False)

        toons_list.add_field(
            name=":bust_in_silhouette: Name",
            value=main_toons.Name.to_string(index=False),
            inline=True)

        toons_list.add_field(
            name=":crossed_swords:️ Class",
            value=main_toons.Class.to_string(index=False),
            inline=True)

        toons_list.add_field(
            name=":arrow_double_up: Level",
            value=main_toons.Level.to_string(
                index=False),
            inline=True)

    if len(alt_toons) > 0:

        toons_list.add_field(
            name="Alts",
            value=f"{len(alt_toons)} character(s) declared as alts",
            inline=False)

        toons_list.add_field(
            name=":bust_in_silhouette: Name",
            value=alt_toons.Name.to_string(index=False), inline=True)

        toons_list.add_field(
            name=":crossed_swords:️ Class",
            value=alt_toons.Class.to_string(index=False), inline=True)

        toons_list.add_field(
            name=":arrow_double_up: Level",
            value=alt_toons.Level.to_string(index=False),
            inline=True)

    if len(bot_toons) > 0:

        toons_list.add_field(
            name="Bots",
            value=f"{len(bot_toons)} character(s) declared as bots",
            inline=False)

        toons_list.add_field(
            name=":bust_in_silhouette: Name",
            value=bot_toons.Name.to_string(index=False), inline=True)

        toons_list.add_field(
            name=":crossed_swords:️ Class",
            value=bot_toons.Class.to_string(index=False), inline=True)

        toons_list.add_field(
            name=":arrow_double_up: Level",
            value=bot_toons.Level.to_string(index=False),
            inline=True)

    toons_list.set_footer(text="Fetched at local time")

    toons_list.timestamp = datetime.datetime.now(pytz.timezone('US/Pacific'))

    await ctx.reply(embed=toons_list)


@client.command()
async def dkp(ctx, toon=None):

    engine     = sqlalchemy.create_engine('sqlite:///ex_astra.db', echo=False)
    discord_id = format(ctx.message.guild.get_member_named(format(ctx.author)).id)
    dkp        = pd.read_sql_table("dkp", con=engine)
    census     = pd.read_sql_table("census", con=engine)

    if toon == None:
        user = format(ctx.author)

        dkp_mains = census[('Main' == census.Status) & (census.ID.isin(census[census.ID == discord_id]['ID']))][['ID', 'Name']]

    else:
        user = toon.capitalize()

        dkp_mains = census[('Main' == census.Status) & (census.ID.isin(census[census.Name == toon.capitalize()]['ID']))][['ID', 'Name']]

    dkp_dict = dkp.merge(dkp_mains, how = 'inner', on = 'ID')

    dkp_dict["Current_DKP"] = dkp_dict["Earned_DKP"] - dkp_dict["Spent_DKP"]

    rows = len(dkp_dict)

    if rows == 1:

        embed = discord.Embed(
            title=f":dragon:DKP for `{user}`",
            description="DKP can be spent on all toons, but only earned on toons over 45.",
            colour=discord.Colour.from_rgb(241, 196, 15))

        embed.add_field(
            name=":bust_in_silhouette:️ Main Toon",
            value=dkp_dict["Name"].to_string(index=False),
            inline=True)

        embed.add_field(
            name=":arrow_up:️ Current DKP",
            value=dkp_dict["Current_DKP"].to_string(index=False),
            inline=True)

        embed.add_field(
            name=":moneybag: Total Earned",
            value=dkp_dict["Earned_DKP"].to_string(index=False),
            inline=True)

        embed.set_footer(
            text="Fetched at local time")

        embed.timestamp = datetime.datetime.now(pytz.timezone("US/Pacific"))

        await ctx.reply(embed=embed)

    else:
        # await ctx.reply(f":question:{format(ctx.author.mention)}, No DKP found for `{user}`. Ensure the character is created and over level 45. \nSee `!help toons`, `!help main`, and `!help level`")
        await ctx.reply(f":question:No census entry was not found. Check `!toons` and ensure one toon is declared as main, using `!main`.")






@client.command()
@commands.has_role("officer")
async def logs(ctx, *, args):

    census = pd.read_sql_query('SELECT * FROM census', con)
    dkp = pd.read_sql_query('SELECT * FROM dkp', con)
    raids = pd.read_sql_query('SELECT * FROM raids', con)
    manned_bots = pd.read_sql_query('SELECT * FROM manned_bots', con)

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
    modifier = raids.loc[raids['Raid'] == raid, 'Modifier']

    # is there a raid modifier and is it unique?
    if len(modifier.index) == 1:
        modifier = modifier.item()

    else:
        await ctx.reply(f"`{raid}` entry not found.\nAsk Rahmani")
        return

    # create empty lists of rejected players and seen players to prevent double counting
    seen_players = []
    rejected = []

    records = args.splitlines()[1:]
    for record in records:
        # if the record doesn't contain the line "<Ex Astra>", move on
        # very important in case the line is blank
        if "<Ex Astra>" not in record:
            continue

        line = re.compile("(%s|%s|%s|%s)" %
                          (re1, re2, re3, re4)).findall(record)

        timestamp = line[0]

        timestamp = datetime.datetime.strptime(
            timestamp, '%a %b %d %H:%M:%S %Y')

        timestamp = datetime.datetime.strftime(timestamp, '%Y-%m-%d %H:%M:%S')

        level_class = line[1].split(" ")

        name = line[2]

        # guild = line[3]

        discord_ID = census.loc[census["Name"] == name, "ID"]

        if len(discord_ID.index) == 1:
            discord_ID = discord_ID.item()

        # don't bother if the character isn't in the database linked to a discord
        else:
            rejected.append(record)
            continue

        # skip this round if the person is already here, prevent doubling
        if f"<@{discord_ID}>" in seen_players:
            continue

        else:
            seen_players.append(f"<@{discord_ID}>")

        if len(level_class) == 1:
            level = ""
            player_class = ""

        elif len(level_class) == 2:
            level = level_class[0]
            player_class = player_classes.loc[player_classes["Class_name"]
                                              == level_class[1], "Class"].item()

        elif len(level_class) == 3:
            level = level_class[0]
            player_class = player_classes.loc[player_classes["Class_name"]
                                              == f"{level_class[1]} {level_class[2]}", "Class"].item()

        sql_response = "INSERT INTO attendance (Date, Raid, Name, Level, Class, ID) VALUES (?, ?, ?, ?, ?, ?);"

        cur.execute(sql_response, (timestamp, raid, name,
                    level, player_class, discord_ID))

        if cur.rowcount == 1:
            con.commit()

        else:
            await ctx.reply(f"Something is wrong with the record: {record}")
            con.rollback()

        sql_response = "UPDATE dkp SET Earned_DKP = Earned_DKP + ? WHERE ID == ?;"
        cur.execute(sql_response, (modifier, discord_ID))
        # await ctx.reply(sql_response)

        if cur.rowcount == 1:
            con.commit()

        else:
            await ctx.reply(f":exclamation:Something is wrong with the record: `{record}`")
            con.rollback()

    if len(seen_players) > 0:
        await ctx.reply(f":dragon:{', '.join(seen_players)} earned `{modifier}` DKP for `{raid}` this hour.")

    if len(rejected) > 0:
        sep = "\n"
        await ctx.reply(f":question:Some logs got rejected. If you feel generous, after these people register, try:```!logs {raid}\n{sep.join(rejected)}```")


@client.command()
@commands.has_role("officer")
async def welcome(ctx):

    embed = discord.Embed(
        title="Welcome to the guild! ",
        description=":wave:We’re glad to have you. ")

    embed.add_field(
        name=":one:",
        value="Declare your mains on the <#851549677815070751> here, on the Ex Astra server. \n Some useful commands include: `!main <character name> <level> <class>`, `!toons`, `!dkp`",
        inline=False)

    embed.add_field(
        name=":two:",
        value="Join the Aegis Alliance Server invite below and introduce yourself here:\n <#465750297336086530> (link will be usable once you join the invite below)",
        inline=False)

    embed.add_field(
        name=":three:",
        value="Register your toon on [Aegis Website](https://aegisrap.com).\nThis is how you'll be able to keep track of your RAP (Raid Attendance Points) for Aegis Alliance Raids.",
        inline=False)

    embed.add_field(
        name=":four:",
        value=" Have a question?\n :man_raising_hand:Write it in the <#864599563204296724> channel!",
        inline=False)

    embed.add_field(
        name=":five:",
        value="Need to talk to an officer? Tag an officer using <@&849337092324327454> in the <#838976036167090247> or other text channels.",
        inline=False)

    embed.add_field(
        name=":six:",
        value="Check our <#870938136472088586>, <#851872447057100840>, and <#856424309026979870> channels for upcoming events",
        inline=False)

    embed.add_field(
        name=":seven:",
        value="Check our <#851834766302249020> channel if you need assistance with your epic",
        inline=False)

    await ctx.send(embed=embed)

@client.command()
async def rap(ctx, toon=None):

    import os
    st = os.stat('rap.html')
    mtime = st.st_mtime

    current_time = datetime.datetime.now()

    elapsed = current_time - datetime.datetime.fromtimestamp(mtime)
    elapsed = chop_microseconds(elapsed)

    if elapsed < datetime.timedelta(minutes = 1):
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
    rap_totals = rap_totals[len(rap_totals) - 1][['Name', 'Unnamed: 7']]
    rap_totals['Name'] = rap_totals['Name'].apply(titlecase)
    rap_totals.columns = ['Name', 'RAP']

    if toon == None:
        user_name = format(ctx.author)
        discord_id = str(ctx.message.guild.get_member_named(user_name).id)

    if toon != None:
        toon = toon.capitalize()
        user_name = format(toon)
        discord_id = census.loc[census['Name'] == toon, 'ID'].item()

    inner_merged = pd.merge(
        rap_totals, census, left_on="Name", right_on="Name", how="inner")

    inner_merged = inner_merged[['ID', 'Name', 'RAP']]

    inner_merged = inner_merged.sort_values(by=['Name'])

    rap_totals = inner_merged.loc[inner_merged['ID'] == discord_id]

    rap_list = discord.Embed(
        title=f":dragon:RAP for `{user_name}`",
        description="Consult the [Aegis Website](https://aegisrap.com) for rules and declarations.\nRAP may be inconsistent between toons, depending on\n player discrepancies between Ex Astra and AEGIS.",
        colour=discord.Colour.from_rgb(241, 196, 15))

    rap_list.add_field(
        name="Character Declaration",
        value=f"{len(rap_totals)} linked character(s) with RAP are declared in AEGIS.",
        inline=False)

    if len(rap_totals) > 0:

        rap_list.add_field(
            name=":bust_in_silhouette: Name",
            value=rap_totals.Name.to_string(index=False),
            inline=True)

        rap_list.add_field(
            name=":arrow_up:️ Current RAP",
            value=rap_totals.RAP.to_string(index=False), inline=True)

    rap_list.set_footer(text=RAP_age)

    await ctx.reply(embed=rap_list)


@client.command()
@commands.has_role("treasurer")
async def bank(ctx):

    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    engine = sqlalchemy.create_engine('sqlite:///ex_astra.db', echo=False)

    attachment = ctx.message.attachments[0]
    banker_name = Path(attachment.url).stem.split("-")[0]
    inventory_keyword = Path(attachment.url).stem.split("-")[1]

    await ctx.reply(f"Parsing `{inventory_keyword}` for `{banker_name}`")

    req = Request(attachment.url, headers={'User-Agent': 'Mozilla/5.0'})
    stream = urlopen(req).read()
    inventory = pd.read_csv(io.StringIO(stream.decode('utf-8')), sep="\t")

    inventory.insert(0, "Banker", banker_name)

    inventory.insert(0, "Time", current_time)

    sql_response = "DELETE FROM bank WHERE Banker == ?"

    cur.execute(sql_response, (banker_name, ))
    con.commit()

    inventory.to_sql("bank", engine, if_exists="append", index=False)


@client.command()
async def find(ctx, *, name):

    name = titlecase(name)

    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    engine = sqlalchemy.create_engine('sqlite:///ex_astra.db', echo=False)
    bank = pd.read_sql_table("bank", con=engine)
    trash = pd.read_sql_table("trash", con=engine)
    bank = bank[~bank['Name'].isin(trash['Name'])]

    bank["Name"] = bank["Name"].apply(titlecase)

    bank["Name"] = bank["Name"].str.replace("`", "'")

    search_results = bank[bank["Name"].str.contains(
        name)][["Banker", "Name", "Location", "Count", "Time"]]

    unique_bankers = search_results["Banker"].unique()

    if len(unique_bankers) == 0:

        await ctx.reply(f"None of the bankers currently have `{name}`.")

    else:
        for i in unique_bankers:

            banker_results = search_results.loc[search_results["Banker"] == i]

            search_embed = discord.Embed(
                title=f":gem: Treasury Query for `{name}`",
                description=f"Found on `{i}`",
                colour=discord.Colour.from_rgb(241, 196, 15))

            search_embed.add_field(
                name="Item Characteristics",
                value=f"{len(banker_results)} matching item(s) found.",
                inline=False)

            search_embed.add_field(
                name=":bust_in_silhouette: Item",
                value=banker_results.Name.to_string(index=False),
                inline=True)

            search_embed.add_field(
                name=":question: Location",
                value=banker_results.Location.to_string(index=False),
                inline=True)

            search_embed.add_field(
                name=":arrow_up:️ Count",
                value=banker_results.Count.to_string(index=False), inline=True)

            search_embed.set_footer(text="Fetched at local time")

            search_embed.timestamp = datetime.datetime.now(
                pytz.timezone('US/Pacific'))

            await ctx.reply(embed=search_embed)


@client.command()
@commands.has_role("treasurer")
async def banktotals(ctx):

    engine = sqlalchemy.create_engine('sqlite:///ex_astra.db', echo=False)
    bank = pd.read_sql_table("bank", con=engine)
    trash = pd.read_sql_table("trash", con=engine)
    bank = bank[~bank['Name'].isin(trash['Name'])]

    current_time = datetime.datetime.now().strftime("%Y-%m-%d-%H-%M-%S")

    banktotals_file = "banktotals-" + current_time + ".txt"

    banktotals = bank.groupby(['Name'])['Count'].sum().to_frame()

    banktotals = tabulate(banktotals, headers="keys", tablefmt="psql")

    f = open(banktotals_file, "w")
    f.write(banktotals)
    f.close()

    await ctx.reply(f':moneybag:Here is a text file with all the bank totals.', file=discord.File(banktotals_file))
    return


@client.command()
# @commands.has_role("treasurer")
async def who(ctx, level: int = None, player_class: str = None):

    if (level == None or level < 1 or level > 60):
        await ctx.reply("You think you're funny, huh?")
        return

    if player_class is not None:
        player_class = get_player_class(player_class)

    current_time = datetime.datetime.now().strftime("%Y-%m-%d-%H-%M-%S")

    engine = sqlalchemy.create_engine('sqlite:///ex_astra.db', echo=False)

    census = pd.read_sql_table("census", con=engine)

    result = census.loc[(census['Class'] == player_class) & (
        census['Level'] == level) & (census['Status'] != "Dropped"), ['Name', 'ID']]

    result['ID'] = "<@" + result['ID'] + ">"

    result = result.to_csv(index=False, header=False, sep='\t')

    await ctx.reply(f"Here are registered {level} {player_class}s.")

    await ctx.reply(result)

    return

# @client.command()
# async def claim(ctx):
#     import sqlalchemy as db
#
#     engine = db.create_engine('sqlite:///ex_astra.db')
#     connection = engine.connect()
#     metadata = db.MetaData()
#     census = db.Table('census', metadata, autoload=True, autoload_with=engine)
#
#     query = db.update(census).values(ID = 816198379344232488).where(census.columns.Name == "Test")
#     results = connection.execute(query)
#
#     query = db.select(census.ID).where(census.columns.Name == 'Test').where(census.columns.ID == 816198379344232488)
#     results = connection.execute(query).fetchall()
#
#     await ctx.reply(results)

@client.command()
async def claim(ctx, toon):
    from sqlalchemy.ext.automap import automap_base
    from sqlalchemy.orm import Session
    from sqlalchemy import create_engine

    toon = toon.capitalize()
    
    discord_id = ctx.message.guild.get_member_named(format(ctx.author)).id

    Base = automap_base()

    engine = create_engine('sqlite:///ex_astra.db')

    Base.prepare(engine, reflect=True)

    Census = Base.classes.census

    session = Session(engine)

    claimed_toon = session.query(Census).filter(Census.Name == toon).one()

    old_owner = claimed_toon.ID

    old_main = session.query(Census).filter(Census.ID == old_owner).filter(Census.Status == "Main").one()

    old_main = old_main.Name

    if claimed_toon.Status == "Bot":

        claimed_toon.ID = discord_id

        session.commit()

        new_main = session.query(Census).filter(Census.ID == discord_id).filter(Census.Status == "Main").one()

        new_main = new_main.Name

        await ctx.reply(f":white_check_mark:`{new_main}` has taken control of `{toon}` from `{old_main}`." )

    if claimed_toon.Status != "Bot":

        await ctx.reply(f":exclamation:`{toon}` can only change ownership if `{old_main}` declares the toon as a `!bot`." )


@client.command()
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

client.run(DISCORD_TOKEN)
