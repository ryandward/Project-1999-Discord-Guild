from sqlalchemy import select

import logging
import time

from Trie import Trie


class AutoCompletion:
    def __init__(self, async_session_factory, table, choice_transformer):
        self.root = Trie()  # Trie root node from previous examples
        self.cache_timestamps = {}  # Cache timestamps for freshness check
        self.AsyncSession = async_session_factory  # Async session factory for database access
        self.table = table  # Database table for autocomplete queries
        self.choice_transformer = choice_transformer  # Function to transform db rows into choices

    async def query_database(self, current):
        async with self.AsyncSession() as session:
            stmt = select(self.table.name).where(self.table.name.ilike(f"%{current}%"))
            results = await session.execute(stmt)
            return results.scalars().all()

    async def autocomplete(self, current: str):
        now = time.time()

        if not current:
            logger.info("Empty query received; skipping cache and database query.")
            return []

        logger.info(f"Autocomplete requested for '{current}'.")

        if current in self.cache_timestamps and now - self.cache_timestamps[current] < 60:
            choices = self.root.search(current)
            if choices:
                logger.info(f"Cache hit for '{current}'. {len(choices)} choices returned after filtering.")
                return choices[:25]

        logger.info(f"No suitable cache found for '{current}'. Querying database.")
        choices = await self.query_database(current)
        transformed_choices = [self.choice_transformer(row) for row in choices]

        for choice in transformed_choices:
            self.root.insert(choice.name.lower(), choice)

        self.cache_timestamps[current] = now
        logger.info(f"Database query completed and trie updated for '{current}'. {len(transformed_choices)} choices fetched.")

        return transformed_choices[:25]
    
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
