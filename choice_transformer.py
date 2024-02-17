import discord

class ChoiceTransformer:
    def transform(self, row):
        """Transform a database row into a discord.app_commands.Choice."""
        raise NotImplementedError

class DiscordChoiceTransformer(ChoiceTransformer):
    def __init__(self, format):
        # format is a callable that takes a row and returns a discord.app_commands.Choice
        self.format = format

    def transform(self, row):
        # Use the provided format to transform the row into a Choice
        return self.format(row)

# Formatting function for "item" type
item_format = lambda row: discord.app_commands.Choice(
    name=f"{row[0]} x{row[1]}" if row[1] > 1 else row[0], 
    value=row[0]
)

# Formatting function for "general" type
general_format = lambda row: discord.app_commands.Choice(
    name=row[0], 
    value=row[0]
)
