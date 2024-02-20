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

// Interfaces used by DatabaseUtils
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

// Interfaces used by other modules from DatabaseUtils
interface Suggestion {
  name: string;
  value: string;
}



// 3. Bank Utilities
interface Item {
  banker: string;
  quantity: number;
  location: string;
}


const BankUtils = {
  dbUtils: Object.create(DatabaseUtils).init(db),

  // Internal helper functions
  async search(itemName: string) {
    const tableName = 'bank';
    const searchColumn = 'name';
    return await this.dbUtils.getRows(tableName, searchColumn, itemName);
  },

  async suggest(partialName: string) {
    const tableName = 'bank';
    const searchColumn = 'name';
    return await this.dbUtils.getSuggestionsAndCount(tableName, searchColumn, partialName);
  },

  // Command definitions
  commands: [
    {
      name: 'find_test',
      description: 'Searches for an item in the bank.',
      options: [
        {
          name: 'item',
          type: 3, // Assuming this is the correct type for a string
          description: 'The item to search for',
          required: true,
          autocomplete: true,
        },
      ],

      // Command handlers
      execute: async (interaction: CommandInteraction) => {
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
        } else {
          headers = ["Banker", "Quantity", "Location"];
          data = items.map((item: Item) => [item.banker, item.quantity.toString(), item.location]);
        }
        const t = table([headers, ...data]);
        await interaction.reply(`:white_check_mark: \`${itemName}\` was found in the bank.` + `\`\`\`\n${t}\n\`\`\``);
      },
      autocomplete: async (interaction: AutocompleteInteraction) => {
        const partialName = interaction.options.getFocused(true).value;
        const suggestions = await BankUtils.suggest(partialName);
        await interaction.respond(suggestions.map((suggestion: Suggestion) => ({ name: suggestion.name, value: suggestion.value })));
      },
    }, // find_test
    // Additional commands can be added in a similar manner
  ]
};


// 4. Client Initialization

const client = new Client({ intents: [GatewayIntentBits.Guilds] });

client.on('ready', () => {
  if (client.user) {
    logger.info(`Logged in as ${client.user.tag}!`);
  }
});

// 5. Command Registration

// Define the Command interface
interface Command {
  options: any[];
  description: any;
  name: string;
  execute: (interaction: CommandInteraction<CacheType>) => Promise<void>;
  autocomplete?: (interaction: AutocompleteInteraction<CacheType>) => Promise<void>;
  buttons?: (interaction: CommandInteraction<CacheType>) => Promise<void>;
}

// Create a command registry
const commandRegistry: { [moduleName: string]: Command[] } = {
  BankUtils: BankUtils.commands,
  // Add other modules here...
};
// Flatten the command registry to get all commands
const allCommands = Object.values(commandRegistry).flat();


// 6. Event Handlers
  
client.on('interactionCreate', async (interaction: Interaction) => {
  if (!interaction.isCommand() && !interaction.isAutocomplete()) return;

  // Finding the command within the registry that matches the interaction
  const command = allCommands.find(cmd => cmd.name === interaction.commandName);
    if (!command) {
    logger.warn(`No handler found for: ${interaction.commandName}`);
    return;
  }

  if (interaction.isCommand() && command.execute) {
    await command.execute(interaction);
  } else if (interaction.isAutocomplete() && command.autocomplete) {
    await command.autocomplete(interaction);
  }
});

// 7. Bot Initialization
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


// 8. Registering the commands

function getCommandDetails(commands: Command[]) {
  return commands.map(cmd => ({
    name: cmd.name,
    description: cmd.description,
    options: cmd.options || [],
  }));
}
await rest.put(
  Routes.applicationGuildCommands(process.env.BOT_SELF, process.env.GUILD_ID),
  { body: getCommandDetails(allCommands) }
);

logger.info('Successfully reloaded application (/) commands.');

// 9. Login to Discord
await client.login(process.env.DISCORD_TOKEN);
