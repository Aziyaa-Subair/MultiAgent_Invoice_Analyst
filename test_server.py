import asyncio
from pathlib import Path
from fastmcp import Client


async def main():
    async with Client(Path("mcp_server/server.py")) as c:

        tools = await c.list_tools()
        print("Tools:", [t.name for t in tools])
        await c.call_tool("save_invoice", {
            "invoice_number": "TEST-1", "supplier_name": "Test Co",
            "total": 100.0, "currency": "QAR", "invoice_date": "2026-10-01",
        })
        result = await c.call_tool("totals_by_supplier", {})
        print(result.data)


asyncio.run(main())