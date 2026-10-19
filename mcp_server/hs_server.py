import sys
from dataclasses import asdict
from pathlib import Path

# make hs_lookup.py (in the project root) importable when this file is started as a script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastmcp import FastMCP  # noqa: E402

from hs_lookup import search_hs_code  # noqa: E402

mcp = FastMCP("qatar-hs-lookup")


@mcp.tool()
def lookup_hs_code(code: str, mode: str = "auto") -> list[dict]:
    """Look up an HS code (or a chapter/heading prefix) on Qatar's eCustoms portal.
    Returns, for each match: the full HS code, description, unit of measure, ad valorem duty rate
    and any other government agency whose approval is required.
    mode: 'auto' (short prefix = all matches, 6+ digits = first match), 'first' or 'all'."""
    return [asdict(item) for item in search_hs_code(code, mode)]


if __name__ == "__main__":
    mcp.run()