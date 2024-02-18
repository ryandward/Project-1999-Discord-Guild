from sqlalchemy import select
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
        self.search_column = search_column
        self.max_choices = max_choices
        logger.info(
            f"AutoCompletion initialized. Keyword: '{self.search_column}', max choices: {self.max_choices}"
        )

    async def autocomplete(self, current: str):
        if not current:
            logger.info("Empty query received; skipping database query.")
            return []

        logger.info(f"Autocomplete requested for '{current}'. Querying database.")
        choices = await self._query_database(current)

        if not choices:
            logger.info("No matches found.")
            return []

        logger.info("Transforming query results for autocomplete.")
        transformed_choices = [
            self.choice_transformer.transform(row) for row in choices
        ]
        logger.info(f"Transformed {len(transformed_choices)} choices.")

        return transformed_choices[: self.max_choices]

    async def _query_database(self, current: str):
        async with self.AsyncSession() as session:
            stmt = self._create_query(current)
            logger.info(f"Executing query: {stmt}")
            results = await session.execute(stmt)
            choices = results.all()
            logger.info(f"Query returned {len(choices)} results.")
        return choices

    def _create_query(self, current: str):
        return (
            select(
                getattr(self.table, self.search_column),
                func.count(getattr(self.table, self.search_column)).label(
                    "quantity"
                ),
            )
            .where(getattr(self.table, self.search_column).ilike(f"%{current}%"))
            .group_by(getattr(self.table, self.search_column))
        )