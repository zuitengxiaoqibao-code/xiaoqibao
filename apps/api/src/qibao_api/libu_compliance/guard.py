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
