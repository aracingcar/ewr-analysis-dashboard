"""observed.route_requests_through: the getter's requests go to the forwarding proxy (used by the in-browser server)."""

import pytest
import requests

import observed


@pytest.fixture
def sent(monkeypatch):
    calls: list[tuple[str, dict]] = []

    def recorder(url, **kwargs):
        calls.append((url, kwargs))
        return "response"

    monkeypatch.setattr(requests, "get", recorder)  # restored after the test, undoing route_requests_through
    return calls


def test_agency_requests_are_rewritten_to_the_proxy_with_a_timeout(sent):
    observed.route_requests_through("https://proxy.example/", timeout=30)
    query = '{"params":{"site_list":"410001"},"function":"get_ts_traces"}'
    assert requests.get(f"https://realtimedata.waternsw.com.au/cgi/webservice.exe?{query}") == "response"
    assert sent == [(f"https://proxy.example/realtimedata.waternsw.com.au/cgi/webservice.exe?{query}", {"timeout": 30})]


def test_request_without_a_query_and_an_explicit_timeout_are_kept(sent):
    observed.route_requests_through("https://proxy.example")
    requests.get("https://water.data.sa.gov.au/Export/BulkExportJson", timeout=5)
    assert sent == [("https://proxy.example/water.data.sa.gov.au/Export/BulkExportJson", {"timeout": 5})]


def test_plain_http_is_refused_rather_than_forwarded(sent):
    observed.route_requests_through("https://proxy.example")
    with pytest.raises(requests.exceptions.InvalidSchema):
        requests.get("http://realtimedata.waternsw.com.au/cgi/webservice.exe")
    assert sent == []
