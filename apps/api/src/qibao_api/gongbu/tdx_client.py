import socket
from collections.abc import Callable, Sequence

from mootdx.quotes import Quotes

TDX_SERVERS: tuple[tuple[str, int], ...] = (
    ("119.97.185.59", 7709),
    ("124.70.133.119", 7709),
    ("116.205.183.150", 7709),
    ("123.60.73.44", 7709),
    ("116.205.163.254", 7709),
)


def probe_tdx_server(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def select_tdx_server(
    servers: Sequence[tuple[str, int]] = TDX_SERVERS,
    probe: Callable[[str, int], bool] = probe_tdx_server,
) -> tuple[str, int]:
    for host, port in servers:
        if probe(host, port):
            return host, port
    raise ConnectionError("no reachable mootdx server")


def create_tdx_client():
    server = select_tdx_server()
    return Quotes.factory(market="std", server=server)

