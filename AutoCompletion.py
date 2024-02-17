from sqlalchemy import select

import logging
import time

from Trie import Trie
from RichLogger import RichLogger
from sqlalchemy import func

logger = RichLogger(__name__)
class AutoCompletion:
    def __init__(
        self,
        async_session_factory,
        table,
        choice_transformer,
        search_column,
        max_choices=25,
    ):
        self.AsyncSession = async_session_factory
        self.table = table
        self.choice_transformer = choice_transformer
        self.max_choices = max_choices
        self.search_column = search_column

    async def query_database(self, current):
        async with self.AsyncSession() as session:
            stmt = select(
                getattr(self.table, self.search_column),
                func.count(getattr(self.table, self.search_column)).label('quantity')
            ).where(
                getattr(self.table, self.search_column).ilike(f"%{current}%")
            ).group_by(getattr(self.table, self.search_column))
            results = await session.execute(stmt)
            return results.all()  # Adjust based on how you wish to handle results

    async def autocomplete(self, current: str):
        if not current:
            logger.info("Empty query received; skipping database query.")
            return []

        logger.info(f"Autocomplete requested for '{current}'. Querying database.")
        choices = await self.query_database(current)
        transformed_choices = [self.choice_transformer(row) for row in choices]

        logger.info(
            f"Database query completed for '{current}'. {len(transformed_choices)} choices fetched."
        )

        return transformed_choices[: self.max_choices]