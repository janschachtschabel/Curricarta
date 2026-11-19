"""Stand-ins for the Kern export's child (app/exports/kern_child.py), started in a spawned process: a module
of its own, so that the child imports this and the exporter, not a test module and its fixtures."""

import socket
import time
from typing import Any, NoReturn

from app.exports.kern_child import run_child


def sleeping(*_: Any) -> None:
    """A build that does not end in a test's time."""
    time.sleep(60)


def breaking(*_: Any) -> NoReturn:
    """A child that dies without an answer."""
    raise SystemExit(3)


class _NoSocket(socket.socket):
    def __init__(self, *_: Any, **__: Any) -> None:
        raise OSError("the Kern export's child opened a socket")


def without_sockets(*args: Any) -> None:
    """The real child, every socket refused in it: one it opened would break the build."""
    socket.socket = _NoSocket  # type: ignore[misc]
    socket.create_connection = _NoSocket
    run_child(*args)
