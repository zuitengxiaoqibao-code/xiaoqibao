from sqlalchemy import JSON, Column, DateTime, Integer, MetaData, String, Table

metadata = MetaData()

quotes = Table(
    "quote_snapshots",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("symbol", String(6), nullable=False, index=True),
    Column("observed_at", DateTime, nullable=False, index=True),
    Column("source", String(32), nullable=False),
    Column("payload", JSON, nullable=False),
)


def create_schema(engine) -> None:
    metadata.create_all(engine)

