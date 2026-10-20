import sys
from dataclasses import asdict
from pathlib import Path

# make hs_lookup.py (in the project root) importable when this file is started as a script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastmcp import FastMCP  # noqa: E402

mcp = FastMCP("qatar-hs-lookup")

# If hs_lookup.py is missing or a package it needs is not installed, the server must still
# start, so the app can show the real reason instead of "Connection closed".
try:
    from hs_lookup import get_full_detail, search_hs_code
    _IMPORT_ERROR = None
except Exception as e:  # noqa: BLE001
    search_hs_code = None
    get_full_detail = None
    _IMPORT_ERROR = f"{type(e).__name__}: {e}"

_NOT_LOADED = ("HS lookup module could not be loaded ({err}). Put hs_lookup.py in the project folder "
               "and run: pip install requests certifi")


@mcp.tool()
def lookup_hs_code(code: str, mode: str = "auto") -> list[dict]:
    """Look up an HS code (or a chapter/heading prefix) on Qatar's eCustoms portal.
    Returns, for each match: the full HS code, description, unit of measure, ad valorem duty rate
    and any other government agency whose approval is required.
    mode: 'auto' (short prefix = all matches, 6+ digits = first match), 'first' or 'all'."""
    if search_hs_code is None:
        return [{"query": code, "hs_code": "", "found": False, "error": _NOT_LOADED.format(err=_IMPORT_ERROR)}]
    return [asdict(item) for item in search_hs_code(code, mode)]


@mcp.tool()
def get_import_requirements(hs_code: str) -> dict:
    """Full detail for ONE full 12-digit HS code: its description and duty rate and, for every
    government agency whose approval is required, the documents that agency asks for."""
    if get_full_detail is None:
        return {"hs_code": hs_code, "found": False, "error": _NOT_LOADED.format(err=_IMPORT_ERROR)}
    return asdict(get_full_detail(hs_code))


if __name__ == "__main__":
    mcp.run()