# WooCommerce Private MCP Connector

A robust, read-only private connector for WooCommerce, built for integration with **Razorpay Agent Studio** via the [Model Context Protocol (MCP)](https://modelcontextprotocol.io/).

This connector allows an AI Agent to inspect and search merchant orders, check connectivity, and paginate through customer order histories with built-in rate-limit resilience, exponential backoff, structured error reporting, and privacy-conscious PII masking.

---

## Architecture & Features

- **Standardized MCP Interface**: Exposes standard tools (`test_connection`, `list_orders`, `get_order`, `search_orders`) over `stdio` transport.
- **Dual Authentication Modes**:
  - **HTTPS (Production)**: Uses standard HTTP Basic Authentication with WooCommerce REST API Consumer Key and Consumer Secret.
  - **HTTP (Local Development)**: Gracefully falls back to query parameter authentication for local Docker environments.
- **Enterprise Rate-Limit & Failure Resilience**:
  - Automatically captures HTTP `429 Too Many Requests` and HTTP `5xx` server errors.
  - Honors `Retry-After` HTTP headers when present.
  - Performs exponential backoff with full jitter up to configurable maximum retry thresholds.
- **Privacy & PII Protection**:
  - Customer emails are masked by default (`j***@example.com`).
  - Sensitive customer details such as billing/shipping addresses and phone numbers are excluded from agent payloads.
  - Compact order payloads minimize token consumption for downstream LLMs.
- **Strict Read-Only Guardrails**: Eliminates risk by strictly prohibiting create, update, delete, or refund mutations.

---

## Project Structure

```
.
├── AGENT_CAPABILITIES.md    # Specification of capabilities, limitations, and error codes
├── mcp_tool_spec.json       # Formal JSON schema specification of exposed MCP tools
├── server.py                # MCP Server entry point (stdio transport)
├── src/
│   ├── __init__.py
│   └── woo_client.py        # Core WooCommerce REST API client with backoff and PII masking
├── tests/
│   ├── test_woo_client.py   # Unit test suite with mock HTTP responses (offline/CI ready)
│   └── test_mcp_server.py   # Live end-to-end smoke test against a running WooCommerce instance
├── docker-compose.yml       # Local WordPress + WooCommerce environment (for development)
├── local-rest-ssl.php       # Development MU-plugin for local HTTP auth
├── requirements.txt         # Dependencies
├── .env.example             # Template for environment variables (no credentials)
└── README.md                # Setup, run, assumptions, and limitations guide
```

---

## Setup and Installation

### 1. Prerequisites
- Python 3.10+ (tested on 3.14)
- A WooCommerce store (cloud or local Docker) with REST API enabled.
- WooCommerce REST API credentials (Consumer Key and Consumer Secret) generated with **Read** permissions.

### 2. Environment Setup
Clone the repository, create a virtual environment, and install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Configure Credentials
Copy the `.env.example` file to `.env`:

```bash
cp .env.example .env
```

Edit `.env` with your store configuration:

```dotenv
WOO_BASE_URL=https://your-store.example.com
WOO_CONSUMER_KEY=ck_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
WOO_CONSUMER_SECRET=cs_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

> **Security Note**: Never commit your `.env` file to version control. The repository includes `.env` in `.gitignore`.

---

## Running the Connector

### Running as a Stdio MCP Server (Agent Studio / MCP Host)
The connector runs via standard I/O (stdio) to interface seamlessly with Agent Studio or any MCP client:

```bash
python server.py
```

### Connecting to an MCP Client / Agent Studio
To connect an MCP host (such as Claude Desktop, OpenAI MCP Tunnel, or Agent Studio) to this server locally, configure the stdio server definition:

```json
{
  "mcpServers": {
    "woocommerce-readonly": {
      "command": "/absolute/path/to/.venv/bin/python",
      "args": ["/absolute/path/to/server.py"],
      "env": {
        "WOO_BASE_URL": "https://your-store.example.com",
        "WOO_CONSUMER_KEY": "ck_...",
        "WOO_CONSUMER_SECRET": "cs_..."
      }
    }
  }
}
```

---

## Available Tools

| Tool | Parameters | Description |
|---|---|---|
| `test_connection` | None | Verifies credentials and connectivity; returns `ok: true` and `total_orders`. |
| `list_orders` | `status`, `after`, `before`, `customer_id`, `page` (default 1), `per_page` (1–100, default 20) | Lists orders newest-first with pagination metadata (`has_more`, `total_pages`). |
| `get_order` | `order_id` (int, required) | Fetches complete order details, line items, and fulfillment status for a specific order. |
| `search_orders` | `query` (str, required), `page`, `per_page` | Searches orders by customer name, order number, email, or item name. |

See [mcp_tool_spec.json](mcp_tool_spec.json) for the full JSON schema specifications, and [AGENT_CAPABILITIES.md](AGENT_CAPABILITIES.md) for full capability details.

---

## Testing

### 1. Automated Unit Tests (Offline / Mocked)
The unit test suite covers authentication errors (401/403), 404 handling, 429 rate-limiting retries, 5xx backoff, network timeouts, connection drops, pagination, query search, and PII masking without needing live credentials or internet access:

```bash
pytest -v
```

All 10 tests run and pass out-of-the-box.

### 2. Live Smoke Test (End-to-End against WooCommerce)
If you have a live or local Docker WooCommerce instance running with credentials in `.env`:

```bash
python tests/test_mcp_server.py
```

This launches the MCP server in a subprocess, initializes the MCP session over stdio, exercises all 4 tools, verifies pagination and PII masking, and checks error responses.

---

## Assumptions and Limitations

### Assumptions
1. **API Version**: The connector assumes WooCommerce REST API v3 (`/wp-json/wc/v3/`).
2. **Key Permissions**: The API key only requires **Read** permissions. Read/Write keys may be used, but the connector exposes no write primitives.
3. **Transport Security**: In production environments, HTTPS is assumed. HTTP is supported exclusively for local development with query parameter fallback.
4. **Agent Studio Hosting**: As Agent Studio runs in Razorpay's environment, local stdio connectors are bridged via a secure tunnel (e.g., OpenAI Secure MCP Tunnel) or hosted as an approved microservice.

### Limitations
1. **Read-Only Scope**: The connector intentionally cannot create orders, update order status, issue refunds, or modify inventory.
2. **Page Size Cap**: WooCommerce limits `per_page` to a maximum of 100. Requests requesting more than 100 will be capped at 100.
3. **No Raw Customer PII**: Full customer street addresses and phone numbers are excluded to preserve customer privacy.
4. **Query Performance**: The free-text search primitive relies on WooCommerce's core WordPress search indexing, which may vary depending on the merchant's database configuration.

> Note: the passwords in `docker-compose.yml` are local development defaults for a disposable test database, not real credentials.
