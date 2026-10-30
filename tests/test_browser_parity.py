"""Parity: the in-browser server (Pyodide) must give the same answers as the native server for the same requests.

The request script is tests/browser_parity/scenario.py. It runs once against the real HTTP server and once against src/browser_backend.py
inside Pyodide (node), booted from a site built by scripts/build_pages.py, i.e. the files that are published. Needs node and Pyodide
(`npm ci` in tests/browser_parity); skipped otherwise. Slow (a few minutes): marked `slow`.
"""

import http.client
import importlib.util
import json
import math
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import pytest

import server

ROOT = Path(__file__).resolve().parents[1]
PARITY = ROOT / "tests/browser_parity"
EXAMPLES = ROOT / "data/example_scenarios"
RTOL, ATOL = 1e-9, 1e-12
VOLATILE = {"elapsed", "job", "id", "uewr_id", "created", "updated"}  # job/definition ids, timestamps and timings differ run to run

pytestmark = pytest.mark.slow


def _scenario():
    spec = importlib.util.spec_from_file_location("parity_scenario", PARITY / "scenario.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _native(tmp_path, monkeypatch) -> dict[str, Any]:
    monkeypatch.setattr(server, "STORE", tmp_path / "store")
    monkeypatch.setattr(server, "FLOWS", {})
    monkeypatch.setattr(server, "_EVAL_CACHE", {})
    httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    port = httpd.server_address[1]

    def call(method, path, headers=None, body=b""):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=600)
        conn.request(method, path, body=body or None, headers={**(headers or {}), "Content-Length": str(len(body))})
        response = conn.getresponse()
        data = response.read()
        conn.close()
        return response.status, data

    try:
        result: dict[str, Any] = _scenario().run(call, lambda name: (EXAMPLES / name).read_bytes())
        return result
    finally:
        httpd.shutdown()


def _browser(tmp_path) -> dict[str, Any]:
    if shutil.which("node") is None or not (PARITY / "node_modules/pyodide").exists():
        pytest.skip("needs node and Pyodide: run `npm ci` in tests/browser_parity")
    site = tmp_path / "site"
    subprocess.run([sys.executable, str(ROOT / "scripts/build_pages.py"), str(site)], check=True, capture_output=True)
    output = tmp_path / "browser.json"
    subprocess.run(
        ["node", str(PARITY / "run_pyodide.mjs"), str(site), str(EXAMPLES), str(PARITY / "scenario.py"), str(output)], check=True, cwd=PARITY, timeout=1800
    )
    result: dict[str, Any] = json.loads(output.read_text())
    return result


def _differences(native: Any, browser: Any, where: str = "") -> list[str]:
    """Every place the two answers differ (numbers within RTOL/ATOL count as equal; job ids and timings are ignored)."""
    if isinstance(native, dict) and isinstance(browser, dict):
        found = []
        for key in sorted((set(native) | set(browser)) - VOLATILE):
            if key not in native or key not in browser:
                found.append(f"{where}/{key}: only in {'browser' if key in browser else 'native'}")
            else:
                found += _differences(native[key], browser[key], f"{where}/{key}")
        return found
    if isinstance(native, list) and isinstance(browser, list):
        if len(native) != len(browser):
            return [f"{where}: length {len(native)} vs {len(browser)}"]
        return [d for i, (a, b) in enumerate(zip(native, browser, strict=True)) for d in _differences(a, b, f"{where}[{i}]")]
    if isinstance(native, (int, float)) and isinstance(browser, (int, float)) and not isinstance(native, bool) and not isinstance(browser, bool):
        return [] if math.isclose(native, browser, rel_tol=RTOL, abs_tol=ATOL) else [f"{where}: {native!r} vs {browser!r}"]
    return [] if native == browser else [f"{where}: {native!r} vs {browser!r}"]


def test_browser_server_matches_native_server(tmp_path, monkeypatch):
    native = _native(tmp_path, monkeypatch)
    browser = _browser(tmp_path)

    # The script must have exercised real answers, not two identical sets of errors.
    for name in ("job pa", "job pb", "job pc", "job pd", "uewr job"):
        assert native[name]["status"] == "done", (name, native[name])
    assert len(native["job pc"]["rows"]) > 10
    for name in ("heatmap", "curves fdc", "ewryears", "regimes", "uewr preview", "uewr save"):
        assert native[name]["status"] == 200, (name, native[name])
    assert native["uewr invalid"]["status"] == 400

    differences = _differences(native, browser)
    assert not differences, "\n".join(differences[:40])
