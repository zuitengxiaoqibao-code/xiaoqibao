from typing import Protocol, TypeVar

from qibao_api.contracts.market import AssetKind
from qibao_api.libu_compliance.repository import ComplianceRepository


Result = TypeVar("Result")


class HistorySource(Protocol[Result]):
    def fetch_daily(self, symbol: str, limit: int) -> Result: ...


class AuthorizedHistorySource:
    def __init__(
        self,
        source: HistorySource[Result],
        compliance: ComplianceRepository,
        feature: str,
        asset: AssetKind | str,
    ) -> None:
        self._source = source
        self._compliance = compliance
        self._feature = feature
        self._asset = AssetKind(asset)

    def fetch_daily(self, symbol: str, limit: int = 250) -> Result:
        self._compliance.require_feature_sources(self._feature, self._asset)
        return self._source.fetch_daily(symbol, limit)


class QuoteSource(Protocol[Result]):
    async def fetch(self, symbol: str) -> Result: ...


class AuthorizedQuoteSource:
    def __init__(
        self,
        source: QuoteSource[Result],
        compliance: ComplianceRepository,
        features: tuple[str, ...],
        asset: AssetKind | str,
    ) -> None:
        if not features:
            raise ValueError("at least one guarded feature is required")
        self._source = source
        self._compliance = compliance
        self._features = features
        self._asset = AssetKind(asset)

    async def fetch(self, symbol: str) -> Result:
        self._require_sources()
        return await self._source.fetch(symbol)

    async def fetch_snapshot(self, symbol: str) -> Result:
        self._require_sources()
        return await self._source.fetch_snapshot(symbol)

    def _require_sources(self) -> None:
        for feature in self._features:
            self._compliance.require_feature_sources(feature, self._asset)


class AuthorizedFinanceSource:
    def __init__(
        self,
        source,
        compliance: ComplianceRepository,
        feature: str,
        asset: AssetKind | str,
    ) -> None:
        self._source = source
        self._compliance = compliance
        self._feature = feature
        self._asset = AssetKind(asset)

    def fetch(self, symbol: str):
        self._compliance.require_feature_sources(self._feature, self._asset)
        return self._source.fetch(symbol)


class AuthorizedClassificationSource:
    def __init__(
        self,
        source,
        compliance: ComplianceRepository,
        feature: str,
        asset: AssetKind | str,
    ) -> None:
        self._source = source
        self._compliance = compliance
        self._feature = feature
        self._asset = AssetKind(asset)

    async def fetch(self, symbol: str):
        self._compliance.require_feature_sources(self._feature, self._asset)
        return await self._source.fetch(symbol)
