# Agent Capabilities and Limitations

## What the Agent Can Do

| Capability | Description |
|------------|-------------|
| **List Orders** | Retrieve a paginated list of orders. Supports optional filtering by `status`, `after`, `before`, and `customer_id`. Returns a compact representation that masks PII by default. |
| **Get Order** | Fetch a single order by its numeric ID, including line items and status. PII is masked. |
| **Search Orders** | Free-text search matching order number, customer name, customer email, or product title. The query must be non-empty. |
| **Test Connection** | Verify that the store is reachable and return the total number of orders in the store. |
| **Pagination** | Both `list_orders` and `search_orders` expose `page`, `per_page`, `has_more`, and `total_pages` fields so the agent can iterate through large result sets. |
| **Rate‑Limit Handling** | The client automatically retries on HTTP 429 (rate‑limited) and 5xx responses using exponential back‑off and respects `Retry‑After` headers. |
| **Timeout & Retry** | Network timeouts and connection errors trigger retries up to the configured `max_retries`. |
| **PII Protection** | Customer email addresses are masked (`j***@example.com`). Phone numbers and addresses are omitted. Customer names are included in the compact order response. The Python client supports disabling email masking for controlled debugging; the MCP tools do not expose that option. |

## What the Agent **Cannot** Do

- **Create, update or delete** orders, products, or any other resources – the connector is deliberately read‑only.
- **Process refunds or cancellations** – those actions are out of scope for this MCP interface.
- **Expose raw WooCommerce objects** – only a curated subset of fields is returned to keep the payload small and to protect sensitive data.
- **Bypass authentication** – a valid consumer key/secret pair must be supplied via environment variables (`WOO_BASE_URL`, `WOO_CONSUMER_KEY`, `WOO_CONSUMER_SECRET`).
- **Handle more than 100 items per page** – the WooCommerce API caps `per_page` at 100; the client enforces this limit.
- **Provide its own public endpoint or tunnel** – the server uses MCP stdio transport. Deployers must run it in an Agent Studio-compatible MCP host or provide an approved secure bridge; this repository does not configure or provision a tunnel.

## Authentication

The connector uses the standard WooCommerce REST API authentication:
- When the store URL uses **HTTPS**, the consumer key and secret are sent via HTTP Basic Auth.
- For **HTTP** (local development only), the credentials are added as query parameters `consumer_key` and `consumer_secret`. Use HTTPS for real stores because URLs and query parameters may be logged.

All credentials are read from environment variables; no secrets are hard‑coded.

## Error Handling

| Error | Agent‑friendly `code` | When it occurs |
|-------|----------------------|----------------|
| Authentication failure | `auth_failed` | HTTP 401/403 |
| Resource not found | `not_found` | HTTP 404 |
| Rate limit exceeded | `rate_limited` | HTTP 429 after all retries |
| Service unavailable | `unavailable` | Network timeout, connection error, or repeated 5xx responses |
| Generic error | `woo_error` | Any other unexpected status code |

These codes can be used by an Agent Studio workflow to decide whether to retry, abort, or fallback.
