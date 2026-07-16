from qibao_api.assets.registry import AssetRegistry
from qibao_api.contracts.market import AssetKind


def test_a_share_and_convertible_bond_are_distinct_domains() -> None:
    registry = AssetRegistry.default()

    assert registry.get(AssetKind.A_SHARE).route_prefix == "/a-shares"
    assert registry.get(AssetKind.CONVERTIBLE_BOND).route_prefix == "/convertible-bonds"

