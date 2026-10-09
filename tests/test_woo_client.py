# tests/test_woo_client.py
"""Unit tests for WooClient.
These tests cover authentication, pagination, search, error handling, timeouts, connection failures, and PII masking.
They use the `requests-mock` library to stub HTTP responses.
"""

import os
import json
import pytest
import requests
import requests_mock
from pathlib import Path

# Ensure the project root is on sys.path for imports
import sys
sys.path.append(str(Path(__file__).resolve().parents[1]))

from src.woo_client import (
    WooClient,
    WooAuthError,
    WooNotFound,
    WooRateLimited,
    WooUnavailable,
    WooError,
)

@pytest.fixture
def client():
    """Create a WooClient instance pointing at a dummy base URL.
    The consumer key/secret are dummy values; authentication is mocked.
    """
    return WooClient(
        "https://example.com",
        "ck_dummy",
        "cs_dummy",
        max_retries=2,
        timeout=1.0,
        max_backoff=0.1,
    )

def _mock_response(m, url, status=200, json_data=None, headers=None):
    """Helper to register a mock response.
    """
    headers = headers or {}
    m.get(url, status_code=status, json=json_data, headers=headers)

def test_authentication_error(client):
    with requests_mock.Mocker() as m:
        # Any request returns 401
        _mock_response(m, "https://example.com/wp-json/wc/v3/orders", status=401)
        with pytest.raises(WooAuthError) as exc:
            client.list_orders()
        assert exc.value.status == 401

def test_not_found_error(client):
    with requests_mock.Mocker() as m:
        _mock_response(m, "https://example.com/wp-json/wc/v3/orders/9999", status=404)
        with pytest.raises(WooNotFound) as exc:
            client.get_order(9999)
        assert exc.value.status == 404

def test_rate_limit_retry(client):
    # Simulate two 429 responses followed by a successful one.
    with requests_mock.Mocker() as m:
        url = "https://example.com/wp-json/wc/v3/orders"
        m.get(url, [{"status_code": 429}, {"status_code": 429}, {"status_code": 200, "json": [], "headers": {"X-WP-TotalPages": "1", "X-WP-Total": "0"}}])
        result = client.list_orders(per_page=5)
        assert result["orders"] == []

def test_rate_limit_exhausted(client):
    with requests_mock.Mocker() as m:
        url = "https://example.com/wp-json/wc/v3/orders"
        # All attempts return 429 (max_retries=2 => three attempts total)
        for _ in range(3):
            m.get(url, status_code=429)
        with pytest.raises(WooRateLimited):
            client.list_orders()

def test_server_error_retry(client):
    # 500 errors should be retried similarly to 429.
    with requests_mock.Mocker() as m:
        url = "https://example.com/wp-json/wc/v3/orders"
        m.get(url, [{"status_code": 500}, {"status_code": 200, "json": [], "headers": {"X-WP-TotalPages": "1", "X-WP-Total": "0"}}])
        result = client.list_orders()
        assert result["orders"] == []

def test_timeout_and_unavailable(client):
    with requests_mock.Mocker(real_http=False) as m:
        url = "https://example.com/wp-json/wc/v3/orders"
        # Simulate a timeout on the first call, then a successful one.
        def raise_timeout(request, context):
            raise requests.Timeout("timeout simulated")
        m.get(url, text=raise_timeout)
        # After the first timeout the client will retry; we register a good response.
        m.get(url, json=[], status_code=200, headers={"X-WP-TotalPages": "1", "X-WP-Total": "0"})
        result = client.list_orders()
        assert result["orders"] == []

def test_connection_error_unavailable(client):
    with requests_mock.Mocker(real_http=False) as m:
        url = "https://example.com/wp-json/wc/v3/orders"
        def raise_conn(request, context):
            raise requests.ConnectionError("connection failure")
        m.get(url, text=raise_conn)
        # Register a successful response for the retry
        m.get(url, json=[], status_code=200, headers={"X-WP-TotalPages": "1", "X-WP-Total": "0"})
        result = client.list_orders()
        assert result["orders"] == []

def test_pagination(client):
    with requests_mock.Mocker() as m:
        base = "https://example.com/wp-json/wc/v3/orders"
        # The same endpoint returns different pages on sequential requests.
        # Requests also include per_page/order params, so matching the URL
        # without query params keeps this test independent of query ordering.
        m.get(base, [
            {"json": [{"id": 1}, {"id": 2}], "headers": {"X-WP-TotalPages": "2", "X-WP-Total": "3"}},
            {"json": [{"id": 3}], "headers": {"X-WP-TotalPages": "2", "X-WP-Total": "3"}},
        ])
        # First call (default page=1)
        res1 = client.list_orders(page=1, per_page=2)
        assert len(res1["orders"]) == 2
        assert res1["has_more"] is True
        # Second page
        res2 = client.list_orders(page=2, per_page=2)
        assert len(res2["orders"]) == 1
        assert res2["has_more"] is False

def test_search_orders(client):
    with requests_mock.Mocker() as m:
        url = "https://example.com/wp-json/wc/v3/orders"
        m.get(url, json=[{"id": 5, "billing": {"email": "john@example.com", "first_name": "John", "last_name": "Doe"}}], headers={"X-WP-TotalPages": "1", "X-WP-Total": "1"})
        result = client.search_orders("john")
        assert len(result["orders"]) == 1
        order = result["orders"][0]
        # Email should be masked
        assert order["customer_email"].startswith("j***@")

def test_pii_masking_disabled(client):
    with requests_mock.Mocker() as m:
        url = "https://example.com/wp-json/wc/v3/orders"
        m.get(url, json=[{"id": 6, "billing": {"email": "alice@example.com", "first_name": "Alice", "last_name": "Smith"}}], headers={"X-WP-TotalPages": "1", "X-WP-Total": "1"})
        result = client.list_orders(mask_pii=False)
        order = result["orders"][0]
        assert order["customer_email"] == "alice@example.com"
