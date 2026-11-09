"""Smoke test (spec 104, AC-104.4): requests to a running service show up in /metrics.

It reaches the service only through its URL. Without SMOKE_BASE_URL it is skipped. It only reads,
so it runs in every environment (no `@pytest.mark.writes`, #474). Several instances may sit
behind the URL, each counting only its own requests, so it repeats the requests and the scrape
until one instance has counted both (#520).
"""

from __future__ import annotations

import time
import urllib.error
import urllib.request

import pytest

HEALTH = 'http_requests_total{method="GET",route="/health",status_code="200"}'
UNMATCHED = 'http_requests_total{method="GET",route="unmatched",status_code="404"}'


def _get(url: str) -> int:
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            return int(response.status)
    except urllib.error.HTTPError as err:
        return err.code


@pytest.mark.smoke
def test_requests_are_counted_in_metrics(smoke_base_url: str) -> None:
    """AC-104.4: /health and an unknown path appear with method, route and status_code labels."""
    text = ""
    for _ in range(20):
        assert _get(smoke_base_url + "/health") == 200
        assert _get(smoke_base_url + "/no-such-path-for-smoke") == 404
        with urllib.request.urlopen(smoke_base_url + "/metrics", timeout=10) as response:
            text = response.read().decode()
        if HEALTH in text and UNMATCHED in text:
            break
        time.sleep(0.25)
    assert HEALTH in text
    assert UNMATCHED in text
    assert "/no-such-path-for-smoke" not in text
