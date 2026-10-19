import sqlite3
import sys
from pathlib import Path

from fastmcp import FastMCP

# Optional first argument = path to the SQLite file (the web app uses one per visitor).
DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "invoices.db"
DB_PATH = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DB
mcp = FastMCP("invoice-db")


def _conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS invoices (
            invoice_number TEXT PRIMARY KEY,
            invoice_date TEXT,
            supplier_name TEXT,
            customer_name TEXT,
            currency TEXT,
            subtotal REAL,
            tax REAL,
            total REAL
        )""")
    return conn


@mcp.tool()
def save_invoice(invoice_number: str, supplier_name: str, total: float,
                 invoice_date: str | None = None, customer_name: str | None = None,
                 currency: str | None = None, subtotal: float | None = None,
                 tax: float | None = None) -> str:
    """Save or update an invoice record."""
    with _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO invoices VALUES (?,?,?,?,?,?,?,?)",
            (invoice_number, invoice_date, supplier_name, customer_name,
             currency, subtotal, tax, total),
        )
    return f"Saved {invoice_number}"


@mcp.tool()
def list_invoices(supplier: str | None = None, limit: int = 50) -> list[dict]:
    """List invoices, optionally filtered by supplier name (partial match)."""
    sql, params = "SELECT * FROM invoices", []
    if supplier:
        sql += " WHERE supplier_name LIKE ?"
        params.append(f"%{supplier}%")
    sql += " ORDER BY invoice_date DESC LIMIT ?"
    params.append(limit)
    with _conn() as c:
        return [dict(r) for r in c.execute(sql, params)]


@mcp.tool()
def totals_by_supplier() -> list[dict]:
    """Total billed, tax, and invoice count per supplier and currency."""
    with _conn() as c:
        rows = c.execute("""
            SELECT supplier_name, currency, COUNT(*) AS invoice_count,
                   ROUND(SUM(total), 2) AS total_billed,
                   ROUND(SUM(COALESCE(tax, 0)), 2) AS total_tax
            FROM invoices GROUP BY supplier_name, currency
            ORDER BY total_billed DESC""")
        return [dict(r) for r in rows]


@mcp.tool()
def totals_by_month() -> list[dict]:
    """Total billed per month (YYYY-MM) and currency."""
    with _conn() as c:
        rows = c.execute("""
            SELECT substr(invoice_date, 1, 7) AS month, currency,
                   COUNT(*) AS invoice_count, ROUND(SUM(total), 2) AS total_billed
            FROM invoices WHERE invoice_date IS NOT NULL
            GROUP BY month, currency ORDER BY month""")
        return [dict(r) for r in rows]


if __name__ == "__main__":
    mcp.run()  # stdio transport