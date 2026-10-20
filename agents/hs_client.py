import re
from pathlib import Path

from fastmcp import Client
from fastmcp.client.transports import PythonStdioTransport

HS_SERVER = Path(__file__).resolve().parent.parent / "mcp_server" / "hs_server.py"


def _pct(text: str | None) -> float | None:
    m = re.search(r"-?\d+(?:\.\d+)?", text or "")
    return float(m.group()) if m else None


def _summary(items: list[dict]) -> dict:
    """One result row for one HS code (the first match; the note says if there were more)."""
    found = next((i for i in items if i.get("found")), None)
    if not found:
        err = (items[0].get("error") if items else None) or "No result"
        return {"hs_matched_code": None, "hs_description": None, "hs_duty_pct": None, "hs_uom": None,
                "hs_approval_required": None, "hs_approval_agencies": None, "hs_note": f"Not found: {err}"}
    agencies = found.get("approval_agencies") or ""
    agencies = agencies.replace("Approval required from: ", "") if found.get("approval_required") else "None"
    return {
        "hs_matched_code": found.get("hs_code"),
        "hs_description": found.get("description_en"),
        "hs_duty_pct": _pct(found.get("ad_valorem_rate")),
        "hs_uom": found.get("uom"),
        "hs_approval_required": "Yes" if found.get("approval_required") else "No",
        "hs_approval_agencies": agencies,
        "hs_note": found.get("note") or "",
    }


async def lookup_codes(codes: list[str]) -> dict[str, dict]:
    """Ask the HS-lookup MCP server about each code. One bad code never stops the others."""
    out: dict[str, dict] = {}
    async with Client(PythonStdioTransport(HS_SERVER)) as client:
        for code in codes:
            try:
                res = await client.call_tool("lookup_hs_code", {"code": code, "mode": "auto"})
                out[code] = _summary(res.data or [])
            except Exception as e:
                out[code] = _summary([{"found": False, "error": f"lookup failed: {str(e)[:120]}"}])
    return out



async def fetch_requirements(codes: list[str]) -> dict[str, dict]:
    """Ask the HS MCP server for the document checklist of each full 12-digit code."""
    out: dict[str, dict] = {}
    async with Client(PythonStdioTransport(HS_SERVER)) as client:
        for code in codes:
            try:
                res = await client.call_tool("get_import_requirements", {"hs_code": code})
                out[code] = res.data or {"found": False, "error": "Empty answer"}
            except Exception as e:
                out[code] = {"hs_code": code, "found": False, "error": f"lookup failed: {str(e)[:120]}"}
    return out