"""The request script behind tests/test_browser_parity.py.

`run(call, read_example)` drives the dashboard's API the way the page does, against whichever server `call` talks to: the native
server (real HTTP) or the in-browser one (Pyodide, via src/browser_backend.py). It returns every answer in order so the two can be
compared. This file has no imports beyond the standard library because it also runs inside Pyodide.

`call(method, path, headers=None, body=b"")` -> (status, response body bytes).
"""

import json
import time
from collections.abc import Callable
from typing import Any

Call = Callable[..., tuple[int, bytes]]

UPLOADS = [  # (example file, scenario id, gauges in it)
    ("dummy_broken_scenario_A.csv", "pa", "404216 404243"),
    ("dummy_broken_scenario_A_level_salinity.csv", "pb", "404216 404243"),
    ("dummy_goulburn_scenario_A.csv", "pc", "405201 405202 405203 405232"),
    ("dummy_goulburn_scenario_B_wetter.csv", "pd", "405201 405202 405203 405232"),
]


def _json(raw: bytes) -> Any:
    return json.loads(raw)


def _wait(call: Call, job: str, limit: float = 600.0) -> dict[str, Any]:
    deadline = time.time() + limit
    while time.time() < deadline:
        _, raw = call("GET", f"/api/job?id={job}")
        answer: dict[str, Any] = _json(raw)
        if answer.get("status") != "running":
            return answer
        time.sleep(0.5)
    raise TimeoutError(f"job {job} still running after {limit} s")


def run(call: Call, read_example: Callable[[str], bytes]) -> dict[str, Any]:
    out: dict[str, Any] = {}

    def get(name: str, path: str) -> Any:
        status, raw = call("GET", path)
        out[name] = {"status": status, "body": _json(raw)}
        return out[name]["body"]

    def post(name: str, path: str, headers: dict[str, str], body: bytes) -> Any:
        status, raw = call("POST", path, headers, body)
        out[name] = {"status": status, "body": _json(raw)}
        return out[name]["body"]

    ping = get("ping", "/api/ping")
    ping.pop("observed", None)  # differs on purpose: the browser cannot reach the agencies' servers

    rows: dict[str, list[dict[str, Any]]] = {}
    for filename, scn, gauges in UPLOADS:
        started = post(
            f"upload {scn}",
            "/api/run",
            {"X-Gauges": gauges, "X-Format": "Standard time-series", "X-Filename": filename, "X-Scn-Id": scn},
            read_example(filename),
        )
        finished = _wait(call, started["job"])
        out[f"job {scn}"] = finished
        rows[scn] = finished.get("rows") or []

    pa = rows["pa"]
    pick = pa[0]
    gauge, pu, ewr = pick["gauge"], pick["pu"], pick["ewr"]
    q = lambda **kw: "&".join(f"{k}={v}" for k, v in kw.items())  # noqa: E731  (values here are plain tokens)
    enc = lambda v: v.replace(" ", "%20").replace(":", "%3A").replace(",", "%2C")  # noqa: E731

    get("ewrs", f"/api/ewrs?gauge={gauge}")
    get("heatmap", "/api/heatmap?" + q(base="pa", gauge=gauge, cols=10, xlim=10000, dmax=30))
    get("heatmap diff", "/api/heatmap?" + q(base="pa", comp="pb", gauge=gauge, cols=10, xlim=10000, dmax=30))
    for kind in ("hydro", "fdc"):
        get(f"curves {kind}", "/api/curves?" + q(base="pa", gauge=gauge, kind=kind))
    for kind in ("dfdc", "mdfdc"):
        get(f"curves {kind}", "/api/curves?" + q(base="pa", comp="pb", gauge=gauge, kind=kind))
    get("ewryears", "/api/ewryears?" + q(base="pa", gauge=gauge, ewr=enc(ewr), pu=enc(pu)))
    get("ewryears diff", "/api/ewryears?" + q(base="pa", comp="pb", gauge=gauge, ewr=enc(ewr), pu=enc(pu)))
    get("interevents", "/api/interevents?" + q(scn="pa", gauge=gauge, ewr=enc(ewr), pu=enc(pu)))
    get("spells", "/api/spells?" + q(base="pa", gauge=gauge, thr=100))
    get("regimes", "/api/regimes?" + q(base="pa", gauge=gauge))
    goulburn = rows["pc"][0]
    get("goulburn ewryears", "/api/ewryears?" + q(base="pc", comp="pd", gauge=goulburn["gauge"], ewr=enc(goulburn["ewr"]), pu=enc(goulburn["pu"])))

    schema = get("uewr schema", "/api/uewr/schema")
    out["uewr schema"]["body"] = {"kinds": sorted(schema), "handlers": {k: sorted(v) for k, v in schema.items()}}
    spec = {
        "code": "U_PARITY1",
        "name": "Parity fresh",
        "kind": "F",
        "handler": "flow_handle",
        "gauge": gauge,
        "pus": [pu],
        "objectives": [],
        "regime": None,
        "params": {"FlowThresholdMin": 200, "Duration": 5, "TargetFrequency": 50, "MaxInter-event": 2},
    }
    json_headers = {"Content-Type": "application/json"}
    post("uewr preview", "/api/uewr/preview", json_headers, json.dumps({"spec": spec, "scn": "pa"}).encode())
    saved = post("uewr save", "/api/uewr", json_headers, json.dumps(spec).encode())
    spec_id = saved["spec"]["id"]
    started = post("uewr run", "/api/uewr/run", json_headers, json.dumps({"ids": [spec_id], "scns": ["pa", "pc"]}).encode())
    out["uewr job"] = _wait(call, started["job"])
    post("uewr invalid", "/api/uewr/preview", json_headers, json.dumps({"spec": {**spec, "params": {**spec["params"], "Duration": -1}}, "scn": "pa"}).encode())
    post("uewr delete", f"/api/uewr/delete?id={spec_id}", json_headers, b"{}")
    get("uewr list", "/api/uewr")
    post("forget", "/api/forget?id=pd", {}, b"")
    return out
