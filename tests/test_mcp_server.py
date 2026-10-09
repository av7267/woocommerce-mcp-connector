"""Live test of the WooCommerce MCP server over stdio, with pass/fail checks.

Run (with your venv active and .env loaded):
    set -a; source .env; set +a
    python test_mcp_server.py
"""
import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

params = StdioServerParameters(
    command=sys.executable,          # the same Python you are running now (your venv)
    args=["server.py"],
    env=dict(os.environ),            # pass WOO_* variables through to the server
)

results = []


def check(name: str, condition: bool, detail: str = "") -> None:
    results.append(bool(condition))
    print(f"{'PASS' if condition else 'FAIL'}  {name}" + (f"  -> {detail}" if detail and not condition else ""))


async def call(session: ClientSession, tool: str, **args):
    """Call a tool and return its result as a dict."""
    r = await session.call_tool(tool, arguments=args)
    if getattr(r, "structuredContent", None):
        return r.structuredContent
    return json.loads(r.content[0].text)


async def main() -> None:
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # 1. Discovery
            tools = {t.name: t for t in (await session.list_tools()).tools}
            expected = {"test_connection", "list_orders", "get_order", "search_orders"}
            check("all four tools are exposed", expected <= set(tools), str(set(tools)))
            check("every tool has a description", all(t.description for t in tools.values()))

            # 2. Connection / auth
            conn = await call(session, "test_connection")
            check("test_connection ok", conn.get("ok") is True, str(conn))

            # 3. List + pagination
            page1 = await call(session, "list_orders", per_page=2, page=1)
            orders = page1.get("orders", [])
            check("list_orders returns <= per_page orders", 0 < len(orders) <= 2, str(page1)[:200])
            check("list_orders has pagination fields",
                  all(k in page1 for k in ("page", "per_page", "total", "total_pages", "has_more")))

            if page1.get("total_pages", 1) > 1:
                page2 = await call(session, "list_orders", per_page=2, page=2)
                ids1 = {o["id"] for o in orders}
                ids2 = {o["id"] for o in page2.get("orders", [])}
                check("page 2 differs from page 1", ids1.isdisjoint(ids2) and ids2)

            # 4. Status filter
            some_status = orders[0]["status"] if orders else "processing"
            filtered = await call(session, "list_orders", status=some_status, per_page=50)
            check(f"status filter '{some_status}' only returns that status",
                  all(o["status"] == some_status for o in filtered.get("orders", [])))

            # 5. Get one order
            first_id = orders[0]["id"]
            one = await call(session, "get_order", order_id=first_id)
            check("get_order returns the requested order", one.get("id") == first_id, str(one)[:200])

            # 6. Search
            term = (orders[0].get("customer_name") or "").split(" ")[0] or "a"
            found = await call(session, "search_orders", query=term)
            check(f"search_orders('{term}') returns results", len(found.get("orders", [])) > 0, str(found)[:200])

            # 7. Privacy: emails masked, no address/phone fields
            email = orders[0].get("customer_email", "")
            check("customer email is masked", email == "" or "***" in email, email)
            check("no address/phone fields leak",
                  not any(k in orders[0] for k in ("billing", "shipping", "phone", "address_1")))

            # 8. Failure cases return structured errors, not crashes
            missing = await call(session, "get_order", order_id=999999999)
            check("unknown order -> not_found", missing.get("error") == "not_found", str(missing))

            empty = await call(session, "search_orders", query="   ")
            check("empty search -> error", "error" in empty, str(empty))

    passed = sum(results)
    print(f"\n{passed}/{len(results)} checks passed")
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    asyncio.run(main())



    

    

