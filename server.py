"""MCP server exposing read-only WooCommerce order tools.

Run:  python server.py          (stdio transport, for Agent Studio / MCP clients)
"""
from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from dotenv import load_dotenv

from src.woo_client import WooClient, WooError



load_dotenv()

mcp = MCPServer("woocommerce-readonly")
_client: WooClient | None = None


def client() -> WooClient:
    global _client
    if _client is None:
        _client = WooClient.from_env()
    return _client


def _safe(fn):
    """Turn connector errors into structured results the agent can read."""
    try:
        return fn()
    except WooError as e:
        return {"error": e.code, "message": str(e), "status": e.status}


@mcp.tool()
def test_connection() -> dict:
    """Check that the store URL and API credentials work. Returns total order count."""
    return _safe(lambda: client().test_connection())


@mcp.tool()
def list_orders(
    status: str | None = None,
    after: str | None = None,
    before: str | None = None,
    customer_id: int | None = None,
    page: int = 1,
    per_page: int = 20,
) -> dict:
    """List orders, newest first.

    status: pending, processing, on-hold, completed, cancelled, refunded, failed.
    after/before: ISO 8601 datetimes, e.g. 2026-10-01T00:00:00.
    per_page: 1-100. Use has_more and page to fetch further pages.
    """
    return _safe(lambda: client().list_orders(
        status=status, after=after, before=before, customer=customer_id,
        page=page, per_page=per_page))


@mcp.tool()
def get_order(order_id: int) -> dict:
    """Get one order by its numeric ID, including line items."""
    return _safe(lambda: client().get_order(order_id))


@mcp.tool()
def search_orders(query: str, page: int = 1, per_page: int = 20) -> dict:
    """Search orders by free text (order number, customer name or email, product name)."""
    return _safe(lambda: client().search_orders(query, page=page, per_page=per_page))


if __name__ == "__main__":
    mcp.run()
