from sqlalchemy import select

import logging
import time

from Trie import Trie


class AutoCompletion:
    def __init__(
        self,
        async_session_factory,
        table,
        choice_transformer,
        max_choices=25,
        cache_lifetime=60,
        search_column="name",
    ):
        self.root = Trie()
        self.cache_timestamps = {}
        self.AsyncSession = async_session_factory
        self.table = table
        self.choice_transformer = choice_transformer
        self.max_choices = max_choices
        self.cache_lifetime = cache_lifetime
        self.search_column = search_column

    async def query_database(self, current):
        async with self.AsyncSession() as session:
            stmt = select(getattr(self.table, self.search_column)).where(
                getattr(self.table, self.search_column).ilike(f"%{current}%")
            )
            results = await session.execute(stmt)
            return results.scalars().all()

    async def autocomplete(self, current: str):
        now = time.time()

        if not current:
            logger.info("Empty query received; skipping cache and database query.")
            return []

        logger.info(f"Autocomplete requested for '{current}'.")

        if (
            current in self.cache_timestamps
            and now - self.cache_timestamps[current] < self.cache_lifetime
        ):
            choices = self.root.search(current.lower())
            if choices:
                logger.info(
                    f"Cache hit for '{current}'. {len(choices)} choices returned after filtering."
                )
                return choices[: self.max_choices]

        logger.info(f"No suitable cache found for '{current}'. Querying database.")
        choices = await self.query_database(current)
        transformed_choices = [self.choice_transformer(row) for row in choices]

        for choice in transformed_choices:
            if not self.root.contains(choice.name.lower()):
                self.root.insert(choice.name.lower(), choice)

        self.cache_timestamps[current.lower()] = now
        logger.info(
            f"Database query completed and trie updated for '{current}'. {len(transformed_choices)} choices fetched."
        )

        return transformed_choices[: self.max_choices]


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
