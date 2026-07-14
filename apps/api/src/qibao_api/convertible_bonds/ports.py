from typing import Protocol

from qibao_api.convertible_bonds.models import BondClauseSnapshot, BondQuote


class QuoteSource(Protocol):
    async def fetch(self, bond_code: str) -> BondQuote: ...


class ClauseSource(Protocol):
    async def fetch(self, bond_code: str) -> BondClauseSnapshot: ...
