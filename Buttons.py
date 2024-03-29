import discord
import re


class DeleteButton(
    discord.ui.DynamicItem[discord.ui.Button], template=r"delete:user:(?P<id>[0-9]+)"
):
    def __init__(self, user_id: int) -> None:
        super().__init__(
            discord.ui.Button(
                label="Delete",
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
    ):
        user_id = int(match["id"])
        return cls(user_id)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # Only allow the user who created the button to interact with it.
        return interaction.user.id == self.user_id

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message("Response deleted!", ephemeral=True)
        await interaction.message.delete()

class RequestButton(
    discord.ui.DynamicItem[discord.ui.Button], template=r"request:user:(?P<id>[0-9]+):role:(?P<role_id>\w+)"
):
    def __init__(self, user_id: int, role_id: int) -> None:
        super().__init__(
            discord.ui.Button(
                label="Request",
                style=discord.ButtonStyle.success,
                custom_id=f"request:user:{user_id}:role:{role_id}",
            )
        )
        self.user_id: int = user_id
        self.role_id: int = role_id

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match: re.Match[str],
    ):
        user_id = int(match["id"])
        role_id = int(match["role_id"])
        return cls(user_id, role_id)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.user_id

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(f"<@&{self.role_id}> {interaction.user.mention} is making a request for {interaction.message.content}!")
    
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

    # This is called when the button is clicked and the custom_id matches the template.
    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match: re.Match[str],
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
