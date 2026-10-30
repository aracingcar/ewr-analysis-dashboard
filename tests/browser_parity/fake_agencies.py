"""Deterministic stand-in for the state water agencies' Hydstra service, so observed-data runs can be compared without a network.

`install()` replaces requests.get with a function that answers the getter's get_ts_traces requests (the same JSON shape the real service
returns: see mdba_gauge_getter.gauge_getter.extract_data) with a synthetic daily series per site. It runs under CPython and Pyodide alike.
"""

import json
import math
import random
from datetime import date, timedelta
from typing import Any
from urllib.parse import unquote, urlsplit


def _series(site: str, variable: str, start: date, end: date) -> list[dict[str, Any]]:
    rng = random.Random(f"{site}/{variable}")
    base = 300 + 700 * (int(site) % 7) / 7
    out = []
    day = start
    while day <= end:
        phase = math.sin(2 * math.pi * (day.timetuple().tm_yday - 120) / 365.25)
        flow = max(0.0, base * (1 + 0.9 * phase) + rng.gauss(0, base * 0.15))
        value = flow if variable == "141.00" else 1.0 + flow / 2000
        if rng.random() < 0.01:
            out.append({"v": "", "t": int(day.strftime("%Y%m%d") + "000000"), "q": 255})  # a gap, as agencies publish
        else:
            out.append({"v": f"{value:.3f}", "t": int(day.strftime("%Y%m%d") + "000000"), "q": 10})
        day += timedelta(days=1)
    return out


def respond(url: str) -> dict[str, Any]:
    params = json.loads(unquote(urlsplit(url).query))["params"]
    start = date(int(params["start_time"][:4]), int(params["start_time"][4:6]), int(params["start_time"][6:8]))
    end = date(int(params["end_time"][:4]), int(params["end_time"][4:6]), int(params["end_time"][6:8]))
    traces = [
        {
            "error_num": 0,
            "compressed": "0",
            "site": site,
            "quality_codes": {"10": "Good quality", "255": "Missing"},
            "trace": _series(site, params["varto"], start, end),
            "varfrom_details": {"variable": params["varfrom"]},
            "varto_details": {"variable": params["varto"]},
        }
        for site in params["site_list"].split(",")
    ]
    return {"error_num": 0, "return": {"traces": traces}}


def install() -> list[str]:
    """Patch requests.get; returns the list the URLs requested are appended to."""
    import requests

    seen: list[str] = []

    def get(url: str, **kwargs: Any) -> Any:
        seen.append(url)
        response = requests.Response()
        response.status_code = 200
        response._content = json.dumps(respond(url)).encode()
        response.url = url
        return response

    vars(requests)["get"] = get
    return seen
