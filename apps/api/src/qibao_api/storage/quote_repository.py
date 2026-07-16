from sqlalchemy import desc, insert, select

from qibao_api.contracts.market import Quote
from qibao_api.storage.database import quotes


class QuoteRepository:
    def __init__(self, engine) -> None:
        self.engine = engine

    def save(self, quote: Quote) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                insert(quotes).values(
                    symbol=quote.symbol,
                    observed_at=quote.observed_at,
                    source=quote.source,
                    payload=quote.model_dump(mode="json"),
                )
            )

    def latest(self, symbol: str) -> Quote | None:
        statement = (
            select(quotes.c.payload)
            .where(quotes.c.symbol == symbol)
            .order_by(desc(quotes.c.observed_at))
            .limit(1)
        )
        with self.engine.connect() as connection:
            payload = connection.execute(statement).scalar_one_or_none()
        return Quote.model_validate(payload) if payload else None
