from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.automap import automap_base
from collections import defaultdict
from choice_transformer import DiscordChoiceTransformer, item_format, general_format
from AutoCompletion import AutoCompletion
import logging

logger = logging.getLogger(__name__)


class DBConnectionManager:
    def __init__(
        self, db_url, search_column="name", format=general_format
    ):
        self.engine = create_async_engine(db_url, echo=False)
        self.AsyncSession = sessionmaker(
            bind=self.engine, class_=AsyncSession, expire_on_commit=False
        )
        self.tables = None
        self.auto_completer = None
        self.search_column = search_column
        self.format = format

    async def prepare_tables(self):
        async with self.engine.begin() as conn:
            Base = automap_base()
            await conn.run_sync(Base.prepare)
            self.tables = defaultdict(lambda: None)
            for table_name in Base.classes.keys():
                self.tables[table_name] = Base.classes[table_name]
            logger.info("Database tables prepared successfully.")

    def get_table(self, table_name):
        return self.tables.get(table_name, None)

    def initialize_auto_completer(self, table_name):
        if self.tables and self.tables[table_name]:
            choice_transformer_instance = DiscordChoiceTransformer(self.format)
            self.auto_completer = AutoCompletion(
                async_session_factory=self.AsyncSession,
                table=self.tables[table_name],
                choice_transformer=choice_transformer_instance,
                search_column=self.search_column,
            )
            logger.info(f"{table_name} auto-completion initialized successfully.")
        else:
            logger.error(
                "Cannot initialize auto-completer: Tables not ready or table name is incorrect."
            )

    async def get_auto_completer(self, table_name):
        if not self.tables:
            await self.prepare_tables()
        if not self.auto_completer:
            self.initialize_auto_completer(table_name)
        return self.auto_completer
