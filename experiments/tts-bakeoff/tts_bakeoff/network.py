from __future__ import annotations

import socket
from contextlib import contextmanager
from typing import Iterator


class NetworkDenied(RuntimeError):
    """A local benchmark adapter attempted an undeclared network connection."""


@contextmanager
def deny_network() -> Iterator[None]:
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_create_connection = socket.create_connection

    def blocked(*_args: object, **_kwargs: object) -> None:
        raise NetworkDenied("network access is disabled for local benchmark adapters")

    socket.socket.connect = blocked  # type: ignore[method-assign]
    socket.socket.connect_ex = blocked  # type: ignore[method-assign]
    socket.create_connection = blocked  # type: ignore[assignment]
    try:
        yield
    finally:
        socket.socket.connect = original_connect  # type: ignore[method-assign]
        socket.socket.connect_ex = original_connect_ex  # type: ignore[method-assign]
        socket.create_connection = original_create_connection  # type: ignore[assignment]
