// Import necessary modules
import { AutocompleteInteraction, CacheType, Client, CommandInteraction, CommandInteractionOptionResolver, GatewayIntentBits, Interaction, REST, Routes } from 'discord.js';
import dotenv from 'dotenv';
import pgPromise, { IDatabase, IMain } from 'pg-promise';
import table from 'text-table';
import winston from 'winston';

// 1. Configuration and Setup
dotenv.config();
const pgp = pgPromise({});

const db = pgp({
  user: process.env.PGUSER,
  password: process.env.PGPASS,
  host: process.env.PGHOST,
  port: 5432,
  database: process.env.PGDATA
});

const logger = winston.createLogger({
  level: 'info',
  format: winston.format.combine(winston.format.colorize(), winston.format.simple()),
  transports: [new winston.transports.Console()]
});


// 2. Database Utilities
interface Row {
  [key: string]: any | null;
}

const DatabaseUtils = {
  db: null as IDatabase<IMain> | null,

  init(db: IDatabase<IMain>) {
    this.db = db;
    return this;
  },

  getInitializedDb(): IDatabase<IMain> {
    if (this.db === null) {
      throw new Error('Database connection not initialized');
    }
    return this.db;
  },


  async getRows(tableName: string, columnName: string, value: string) {
    try {
      this.db = this.getInitializedDb();
      const query = `SELECT * FROM ${tableName} WHERE ${columnName} = $1`;
      const result = await db.any(query, value);
      return result; // Returning the full result for flexibility
    } catch (error) {
      logger.error(error);
      return [];
    }
  },

  async getSuggestions(tableName: string, searchColumn: string, partialName: string) {
    try {
      this.db = this.getInitializedDb();
      const query = `SELECT DISTINCT ${searchColumn} FROM ${tableName} WHERE ${searchColumn} ILIKE $1 LIMIT 10`;
      const result = await db.any(query, [`%${partialName}%`]);
      return result.map((row: Row) => ({ name: row[searchColumn], value: row[searchColumn] }));
    } catch (error) {
      logger.error(error);
      return [];
    }
  },

  async getSuggestionsAndCount(tableName: string, searchColumn: string, partialName: string) {
    try {
      this.db = this.getInitializedDb();
      const query = `SELECT ${searchColumn}, COUNT(*) AS count FROM ${tableName} WHERE ${searchColumn} ILIKE $1 GROUP BY ${searchColumn} LIMIT 10`;
      const result = await this.db.any(query, [`%${partialName}%`]);
      return result.map((row: Row) => ({ name: "(" + row.count + "x) " + row[searchColumn], value: row[searchColumn], count: row.count }));
    } catch (error) {
      logger.error(error);
      return [];
    }
  }
};

// Initialize DatabaseUtils with the db connection
const databaseUtils = Object.create(DatabaseUtils).init(db);

// 3. Bank Utilities
interface Item {
  banker: string;
  quantity: number;
  location: string;
}

interface Suggestion {
  name: string;
  value: string;
}

const BankUtils = {
  dbUtils: databaseUtils,

  commandDetails: [
    {
      name: 'find_test',
      description: 'Searches for an item in the bank.',
      options: [
        {
          name: 'item',
          type: 3, // Discord API string type
          description: 'The item to search for',
          required: true,
          autocomplete: true,
        },
      ],
    },
    // Additional commands related to "bank" can be listed here
  ],

  async search(itemName: string) {
    const tableName = 'bank';
    const searchColumn = 'name';
    return await BankUtils.dbUtils.getRows(tableName, searchColumn, itemName);
  },

  async suggest(partialName: string) {
    const tableName = 'bank';
    const searchColumn = 'name';
    return await BankUtils.dbUtils.getSuggestionsAndCount(tableName, searchColumn, partialName);
  },

  commands: {
    search: {
      async execute(interaction: CommandInteraction) {
        const itemName = (interaction.options as CommandInteractionOptionResolver).getString('item');

        if (!itemName) {
          await interaction.reply({ content: `No items found matching "${itemName}".`, ephemeral: true });
          return;
        }

        const items = await BankUtils.search(itemName);
        let headers: string[], data: string[][]
        const allQuantitiesAreOne = items.every((item: Item) => item.quantity == 1);

        if (allQuantitiesAreOne) {
          headers = ["Banker", "Location"];
          data = items.map((item: Item) => [item.banker, item.location]);
        }
        else {
          headers = ["Banker", "Quantity", "Location"];
          data = items.map((item: Item) => [item.banker, item.quantity, item.location]);
        }
        const t = table([headers, ...data]);
        await interaction.reply(`:white_check_mark: \`${itemName}\` was found in the bank.` + `\`\`\`\n${t}\n\`\`\``);

      },

      async autocomplete(interaction: AutocompleteInteraction) {
        const partialName = interaction.options.getFocused();
        const suggestions = await BankUtils.suggest(partialName);
        await interaction.respond(suggestions.map((suggestion: Suggestion) => ({ name: suggestion.name, value: suggestion.value })));
      },
    },
    // Additional commands specific to the Bank context 
  },
};


// 4. Discord Client Initialization and Event Handlers
const client = new Client({ intents: [GatewayIntentBits.Guilds] });

client.on('ready', () => {
  if (client.user) {
    logger.info(`Logged in as ${client.user.tag}!`);
  }
});


interface Command {
  execute: (interaction: CommandInteraction<CacheType>) => Promise<void>;
  autocomplete?: (interaction: AutocompleteInteraction<CacheType>) => Promise<void>;
}

interface CommandRegistry {
  [commandName: string]: Command;
}

const commandRegistry: CommandRegistry = {
  find_test: BankUtils.commands.search,
  // Future commands
};

client.on('interactionCreate', async (interaction: Interaction) => {
  try {
    if (!interaction.isCommand() && !interaction.isAutocomplete()) {
      return;
    }

    const command = commandRegistry[interaction.commandName];
    if (!command) {
      logger.warn(`No handler found for: ${interaction.commandName}`);
      return;
    }

    if (interaction.isCommand()) {
      await command.execute(interaction);
    } else if (interaction.isAutocomplete() && command.autocomplete) {
      await command.autocomplete(interaction);
    }
  } catch (error) {
    logger.error('Error handling interaction:', error);
    // Optionally, inform the user an error occurred if appropriate
  }
});

// 5. Command Registration and Bot Login
logger.info('Started refreshing application (/) commands.');


let rest: REST | undefined;

if (process.env.DISCORD_TOKEN) {
  rest = new REST({ version: '10' }).setToken(process.env.DISCORD_TOKEN);
} else {
  logger.error('DISCORD_TOKEN is not set');
}

if (!rest) {
  throw new Error('REST client not initialized');
}

if (!process.env.BOT_SELF || !process.env.GUILD_ID) {
  throw new Error('Required environment variables are not set');
}

await rest.put(
  Routes.applicationGuildCommands(process.env.BOT_SELF, process.env.GUILD_ID),
  { body: BankUtils.commandDetails }
);

logger.info('Successfully reloaded application (/) commands.');

// Log in to the Discord client
await client.login(process.env.DISCORD_TOKEN);
