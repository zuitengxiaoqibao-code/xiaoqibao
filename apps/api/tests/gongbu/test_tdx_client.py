from qibao_api.gongbu.tdx_client import select_tdx_server


def test_select_tdx_server_skips_unreachable_nodes() -> None:
    servers = [("first", 7709), ("second", 7709)]

    selected = select_tdx_server(servers, probe=lambda host, port: host == "second")

    assert selected == ("second", 7709)
