"""Runs the dashboard's own server code inside the browser (Pyodide), so a statically hosted page needs no Python server.

The page's /api/... requests are handed to `handle`, which feeds them to the same `server.Handler` the local server uses: the routing,
validation, py_ewr calls and JSON are the code in server.py, not a copy. Only the transport differs:

    - there is no socket, so the request and response are in-memory buffers;
    - WebAssembly has no threads or worker processes, so background jobs run to completion inside the request that starts them
      (the page's polling then finds the job already done);
    - uploaded series live in the browser's in-memory file system and are gone when the tab is closed.

Observed data: the agencies' APIs do not allow cross-origin browser requests, so the getter's requests go through the forwarding proxy
(proxy/worker.js) whose address `configure` is given. Without one, Observed is reported unavailable.
"""

import io
import json
import os
import sys
import threading
import types
from concurrent.futures import Future
from email.message import Message
from typing import Any, cast

os.cpu_count = lambda: 1  # one gauge at a time: server.evaluate_gauges falls back to this without a pool


class _InlineThread:
    """threading.Thread stand-in that runs the target when started (Pyodide cannot start threads)."""

    def __init__(self, target: Any = None, args: tuple[Any, ...] = (), kwargs: dict[str, Any] | None = None, daemon: Any = None, **_: Any) -> None:
        self._target, self._args, self._kwargs = target, args, kwargs or {}

    def start(self) -> None:
        if self._target is not None:
            self._target(*self._args, **self._kwargs)

    def join(self, timeout: float | None = None) -> None:
        return None


class BrokenProcessPool(RuntimeError):
    pass


class ProcessPoolExecutor:
    """Worker processes do not exist in WebAssembly (the module is absent); server.evaluate_gauges then evaluates gauges one by one."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise OSError("worker processes are not available in the browser")


class _InlineExecutor:
    """ThreadPoolExecutor stand-in for observed.fetch_many: runs each submitted call at once (no threads in WebAssembly)."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def __enter__(self) -> "_InlineExecutor":
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    def submit(self, fn: Any, *args: Any, **kwargs: Any) -> Future[Any]:
        future: Future[Any] = Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except Exception as exc:
            future.set_exception(exc)
        return future


_process = types.ModuleType("concurrent.futures.process")
_process.BrokenProcessPool = BrokenProcessPool  # type: ignore[attr-defined]
_process.ProcessPoolExecutor = ProcessPoolExecutor  # type: ignore[attr-defined]
sys.modules["concurrent.futures.process"] = _process
import concurrent.futures  # noqa: E402

concurrent.futures.__dict__["ProcessPoolExecutor"] = ProcessPoolExecutor
threading.Thread = _InlineThread  # type: ignore[misc,assignment]

import observed  # noqa: E402
import server  # noqa: E402  (imported after the threading patch so server.threading.Thread is the inline one)

observed.ThreadPoolExecutor = _InlineExecutor  # type: ignore[misc,assignment]

HOST = "localhost:8792"
OBSERVED_UNAVAILABLE = (
    "Observed data cannot be fetched from a web page without a forwarding proxy: the state water agencies' data services do not allow "
    "requests from other websites (see proxy/README.md). Run the dashboard locally (python3 run.py) to use it."
)
OBSERVED_PROXY = ""


def configure(observed_proxy: str = "") -> None:
    """Route the observed-data getter's HTTP requests through the proxy at this address ("" = Observed unavailable).

    The rewriting is observed.route_requests_through (the getter's requests are the adapter's business). Inside Pyodide `requests` is first
    switched to browser XMLHttpRequest, which the proxy's CORS headers allow.
    """
    global OBSERVED_PROXY
    OBSERVED_PROXY = observed_proxy.rstrip("/")
    if not OBSERVED_PROXY:
        return
    observed.route_requests_through(OBSERVED_PROXY)


def _json(status: int, obj: Any) -> tuple[int, dict[str, str], bytes]:
    return status, {"Content-Type": "application/json"}, json.dumps(obj).encode()


class _Server:
    server_address = ("127.0.0.1", 8792)
    token = None


class _Request(server.Handler):
    """One request against Handler's do_GET/do_POST with in-memory streams."""

    def __init__(self, method: str, path: str, headers: dict[str, str], body: bytes) -> None:  # no socket: skip BaseHTTPRequestHandler.__init__
        self.server = _Server()  # type: ignore[assignment]
        self.command, self.path, self.request_version = method, path, "HTTP/1.1"
        self.requestline = f"{method} {path} HTTP/1.1"
        self.client_address = ("127.0.0.1", 0)
        message = Message()
        message["Host"] = HOST
        for name, value in headers.items():
            if name.lower() not in ("host", "origin"):
                message[name] = value
        message["Content-Length"] = str(len(body))
        self.headers = message
        self.rfile = io.BytesIO(body)
        self.wfile = io.BytesIO()
        self.close_connection = True

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return None

    def log_request(self, code: Any = "-", size: Any = "-") -> None:
        return None


def handle(method: str, path: str, headers: dict[str, str], body: bytes) -> tuple[int, dict[str, str], bytes]:
    """Answer one API request: (status, response headers, body)."""
    if path.split("?")[0].startswith("/api/observed/") and not OBSERVED_PROXY:
        return _json(503, {"message": OBSERVED_UNAVAILABLE})
    request = _Request(method, path, headers, body)
    {"GET": request.do_GET, "POST": request.do_POST}.get(method, lambda: request.send_error(405))()
    raw = cast(io.BytesIO, request.wfile).getvalue()
    head, _, payload = raw.partition(b"\r\n\r\n")
    lines = head.decode("latin-1").split("\r\n")
    status = int(lines[0].split()[1])
    out: dict[str, str] = {}
    for line in lines[1:]:
        name, _, value = line.partition(":")
        out[name.strip()] = value.strip()
    if path.split("?")[0] == "/api/ping":
        info = json.loads(payload)
        info["observed"] = {"available": bool(OBSERVED_PROXY), "bom": False, "message": OBSERVED_UNAVAILABLE}
        payload = json.dumps(info).encode()
    return status, out, payload


sys.modules.setdefault("browser_backend", sys.modules[__name__])
