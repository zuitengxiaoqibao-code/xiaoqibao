from dataclasses import dataclass

from qibao_api.contracts.market import AssetKind


@dataclass(frozen=True)
class AssetDomain:
    kind: AssetKind
    route_prefix: str


class AssetRegistry:
    def __init__(self, domains: dict[AssetKind, AssetDomain]) -> None:
        self._domains = domains

    @classmethod
    def default(cls) -> "AssetRegistry":
        return cls(
            {
                AssetKind.A_SHARE: AssetDomain(AssetKind.A_SHARE, "/a-shares"),
                AssetKind.CONVERTIBLE_BOND: AssetDomain(
                    AssetKind.CONVERTIBLE_BOND,
                    "/convertible-bonds",
                ),
            }
        )

    def get(self, kind: AssetKind) -> AssetDomain:
        return self._domains[kind]
