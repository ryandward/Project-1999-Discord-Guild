from Buttons import DeleteButton, DMButton
import discord
from discord.ext import commands
from datetime import datetime


class BotUtils(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.start_time = datetime.now()

    def create_cog_view(self, user_id):
        view = discord.ui.View(timeout=None)
        view.add_item(DeleteButton(user_id))
        return view

    @discord.app_commands.command(
        name="online", description="Check if the bot is online."
    )
    async def online(self, interaction: discord.Interaction):
        """Check if the bot is online."""

        await interaction.response.send_message(
            "I'm online!", view=self.create_cog_view(interaction.user.id)
        )

    @discord.app_commands.command(name="ping", description="Check the bot's latency.")
    async def ping(self, interaction: discord.Interaction):
        """Check the bot's latency."""
        latency = round(self.bot.latency * 1000)  # Convert to milliseconds

        await interaction.response.send_message(
            f":ping_pong: Latency is `{latency} ms`",
            view=self.create_cog_view(interaction.user.id),
        )

    @discord.app_commands.command(
        name="serverinfo", description="Displays information about the server."
    )
    async def server_info(self, interaction: discord.Interaction):
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "This command can only be used in a server."
            )
            return
        embed = discord.Embed(
            title=f"{guild.name} Information", color=discord.Color.blue()
        )
        embed.add_field(name="Server ID", value=guild.id, inline=False)
        embed.add_field(
            name="Creation Date",
            value=guild.created_at.strftime("%Y-%m-%d"),
            inline=False,
        )
        embed.add_field(name="Owner", value=guild.owner.mention, inline=False)
        embed.add_field(name="Member Count", value=guild.member_count, inline=False)

        await interaction.response.send_message(
            embed=embed, view=self.create_cog_view(interaction.user.id)
        )

    @discord.app_commands.command(
        name="uptime", description="Shows how long the bot has been online."
    )
    async def uptime(self, interaction: discord.Interaction):
        now = datetime.now()
        delta = now - self.start_time
        hours, remainder = divmod(int(delta.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        await interaction.response.send_message(
            f"Uptime: {hours}h {minutes}m {seconds}s",
            view=self.create_cog_view(interaction.user.id),
        )

    @discord.app_commands.command(
        name="userinfo", description="Displays information about a user."
    )
    @discord.app_commands.describe(
        member="The member to get info about. Leave empty for yourself."
    )
    async def user_info(
        self, interaction: discord.Interaction, member: discord.Member = None
    ):
        if member is None:
            member = (
                interaction.user
            )  # This will be an instance of discord.Member if in a guild context

        # Use member.display_name to get the server-specific name or nickname
        embed = discord.Embed(
            title=f"{member.display_name}'s Information", color=discord.Color.green()
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="ID", value=member.id, inline=False)
        embed.add_field(
            name="Server Join Date",
            value=member.joined_at.strftime("%Y-%m-%d"),
            inline=False,
        )
        embed.add_field(
            name="Roles",
            value=", ".join(
                [role.name for role in member.roles if role.name != "@everyone"]
            ),
            inline=False,
        )

        await interaction.response.send_message(
            embed=embed, view=self.create_cog_view(interaction.user.id)
        )
