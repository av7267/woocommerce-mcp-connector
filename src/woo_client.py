"""Read-only WooCommerce REST client with auth, pagination, and rate-limit handling."""
from __future__ import annotations

import os
import random
import time
from typing import Any, Callable
from urllib.parse import urlparse

import requests


class WooError(Exception):
    """Base error. `code` is a stable string the agent can act on."""

    code = "woo_error"

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class WooAuthError(WooError):
    code = "auth_failed"


class WooNotFound(WooError):
    code = "not_found"


class WooRateLimited(WooError):
    code = "rate_limited"


class WooUnavailable(WooError):
    code = "unavailable"


def _mask_email(email: str) -> str:
    if not email or "@" not in email:
        return ""
    user, domain = email.split("@", 1)
    return f"{user[:1]}***@{domain}"


def slim_order(o: dict[str, Any], mask_pii: bool = True) -> dict[str, Any]:
    """Return only the fields an agent needs. Addresses and phone numbers are dropped."""
    billing = o.get("billing") or {}
    email = billing.get("email", "")
    return {
        "id": o.get("id"),
        "number": o.get("number"),
        "status": o.get("status"),
        "currency": o.get("currency"),
        "total": o.get("total"),
        "date_created": o.get("date_created"),
        "date_modified": o.get("date_modified"),
        "payment_method": o.get("payment_method_title"),
        "customer_id": o.get("customer_id"),
        "customer_name": f"{billing.get('first_name', '')} {billing.get('last_name', '')}".strip(),
        "customer_email": _mask_email(email) if mask_pii else email,
        "items": [
            {"name": li.get("name"), "quantity": li.get("quantity"), "total": li.get("total")}
            for li in o.get("line_items", [])
        ],
    }


class WooClient:
    def __init__(
        self,
        base_url: str,
        consumer_key: str,
        consumer_secret: str,
        *,
        max_retries: int = 5,
        timeout: float = 15.0,
        max_backoff: float = 30.0,
        sleep: Callable[[float], None] = time.sleep,
    ):
        if not (base_url and consumer_key and consumer_secret):
            raise WooAuthError("Missing WOO_BASE_URL, WOO_CONSUMER_KEY or WOO_CONSUMER_SECRET")
        self.base_url = base_url.rstrip("/")
        self.key = consumer_key
        self.secret = consumer_secret
        self.max_retries = max_retries
        self.timeout = timeout
        self.max_backoff = max_backoff
        self._sleep = sleep
        self._session = requests.Session()
        # WooCommerce accepts HTTP Basic only over HTTPS. Plain-HTTP (local dev)
        # needs the key/secret as query parameters instead.
        self._https = urlparse(self.base_url).scheme == "https"

    @classmethod
    def from_env(cls, **kw) -> "WooClient":
        return cls(
            os.environ.get("WOO_BASE_URL", ""),
            os.environ.get("WOO_CONSUMER_KEY", ""),
            os.environ.get("WOO_CONSUMER_SECRET", ""),
            **kw,
        )

    # ---- core request ----------------------------------------------------
    def _request(self, path: str, params: dict[str, Any] | None = None):
        url = f"{self.base_url}/wp-json/wc/v3/{path.lstrip('/')}"
        params = {k: v for k, v in (params or {}).items() if v is not None}
        auth = None
        if self._https:
            auth = (self.key, self.secret)
        else:
            params["consumer_key"] = self.key
            params["consumer_secret"] = self.secret

        last_status = None
        for attempt in range(self.max_retries + 1):
            try:
                resp = self._session.get(url, params=params, auth=auth, timeout=self.timeout)
            except (requests.Timeout, requests.ConnectionError) as e:
                last_status = None
                if attempt == self.max_retries:
                    raise WooUnavailable(f"Could not reach store: {type(e).__name__}") from e
                self._sleep(self._backoff(attempt))
                continue

            status = resp.status_code
            if status == 200:
                return resp
            if status in (401, 403):
                raise WooAuthError("Authentication failed: check key/secret and key permissions", status)
            if status == 404:
                raise WooNotFound("Resource not found", status)
            if status == 429 or status >= 500:
                last_status = status
                if attempt == self.max_retries:
                    break
                self._sleep(self._retry_delay(resp, attempt))
                continue
            raise WooError(f"Unexpected response {status}", status)

        if last_status == 429:
            raise WooRateLimited("Rate limit still exceeded after retries; try again later", 429)
        raise WooUnavailable(f"Store returned {last_status} after retries", last_status)

    def _backoff(self, attempt: int) -> float:
        return min(self.max_backoff, (2 ** attempt) * 0.5) + random.uniform(0, 0.25)

    def _retry_delay(self, resp: requests.Response, attempt: int) -> float:
        ra = resp.headers.get("Retry-After")
        if ra:
            try:
                return min(self.max_backoff, max(0.0, float(ra)))
            except ValueError:
                pass  # HTTP-date form: fall back to backoff
        return self._backoff(attempt)

    # ---- primitives ------------------------------------------------------
    def test_connection(self) -> dict[str, Any]:
        resp = self._request("orders", {"per_page": 1})
        return {"ok": True, "total_orders": int(resp.headers.get("X-WP-Total", 0))}

    def list_orders(
        self,
        *,
        status: str | None = None,
        after: str | None = None,
        before: str | None = None,
        customer: int | None = None,
        page: int = 1,
        per_page: int = 20,
        mask_pii: bool = True,
    ) -> dict[str, Any]:
        per_page = max(1, min(int(per_page), 100))
        resp = self._request(
            "orders",
            {
                "status": status, "after": after, "before": before,
                "customer": customer, "page": page, "per_page": per_page,
                "orderby": "date", "order": "desc",
            },
        )
        total_pages = int(resp.headers.get("X-WP-TotalPages", 1))
        return {
            "orders": [slim_order(o, mask_pii) for o in resp.json()],
            "page": page,
            "per_page": per_page,
            "total": int(resp.headers.get("X-WP-Total", 0)),
            "total_pages": total_pages,
            "has_more": page < total_pages,
        }

    def get_order(self, order_id: int, mask_pii: bool = True) -> dict[str, Any]:
        resp = self._request(f"orders/{int(order_id)}")
        return slim_order(resp.json(), mask_pii)

    def search_orders(self, query: str, *, page: int = 1, per_page: int = 20,
                      mask_pii: bool = True) -> dict[str, Any]:
        if not query or not query.strip():
            raise WooError("query must not be empty")
        per_page = max(1, min(int(per_page), 100))
        resp = self._request("orders", {"search": query.strip(), "page": page, "per_page": per_page})
        total_pages = int(resp.headers.get("X-WP-TotalPages", 1))
        return {
            "orders": [slim_order(o, mask_pii) for o in resp.json()],
            "page": page,
            "per_page": per_page,
            "total": int(resp.headers.get("X-WP-Total", 0)),
            "total_pages": total_pages,
            "has_more": page < total_pages,
        }
