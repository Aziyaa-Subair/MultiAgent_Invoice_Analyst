import re
from datetime import date

from pydantic import BaseModel, Field


def to_number(raw) -> float | None:
    """'1,020.00' -> 1020.0, '5%' -> 5.0, 'QAR 12.5' -> 12.5. Anything else -> None."""
    if raw is None:
        return None
    t = str(raw).strip().replace(",", "").replace("%", "")
    t = re.sub(r"^(?:[A-Za-z]{3}|[$€£])\s*", "", t)
    return float(t) if re.fullmatch(r"-?\d+(?:\.\d+)?", t) else None


def find_col(columns: list[str], header: str | None) -> int | None:
    """Position of a header in the list of column names (exact match first, then ignoring case/spaces)."""
    if not header:
        return None
    for i, c in enumerate(columns):
        if c == header:
            return i
    h = header.strip().lower()
    for i, c in enumerate(columns):
        if c.strip().lower() == h:
            return i
    return None


class NamedValue(BaseModel):
    name: str = Field(description="Field name exactly as printed, e.g. 'PO No', 'TRN', 'Incoterms'")
    value: str | None = Field(None, description="Value exactly as printed, or null if blank")


class TableRow(BaseModel):
    cells: list[str] = Field(
        description=(
            "One value per column, in the SAME order as 'columns', exactly as printed "
            "(keep thousands separators and % signs). Use an empty string for a blank cell."
        )
    )


class ItemTable(BaseModel):
    columns: list[str] = Field(
        description="The column headers of the item table EXACTLY as printed on the invoice, left to right."
    )
    rows: list[TableRow] = Field(description="One row per item line. Never include subtotal/VAT/total rows.")
    description_column: str | None = Field(None, description="Header (copied from 'columns') of the item name/description column")
    quantity_column: str | None = Field(None, description="Header (copied from 'columns') of the quantity column")
    unit_price_column: str | None = Field(None, description="Header (copied from 'columns') of the unit price / rate column")
    amount_column: str | None = Field(
        None, description="Header (copied from 'columns') of the per-line total column that adds up to the subtotal"
    )
    hs_code_column: str | None = Field(
        None, description="Header (copied from 'columns') of the HS code / tariff code column, if there is one"
    )


class InvoiceData(BaseModel):
    invoice_number: str
    invoice_date: date | None = Field(None, description="ISO date, YYYY-MM-DD")
    supplier_name: str
    customer_name: str | None = None
    currency: str | None = Field(None, description="3-letter code, e.g. QAR, USD")
    table: ItemTable
    subtotal: float | None = None
    tax: float | None = None
    total: float
    other_fields: list[NamedValue] = Field(
        default_factory=list,
        description=(
            "Other invoice-level details that are printed, with their printed labels: PO number, "
            "VAT/TRN number, BL or AWB number, container number, incoterms, payment terms. Only what is printed."
        ),
    )

    def items_sum(self) -> float | None:
        """Sum of the amount column, or None if there is no usable amount column."""
        i = find_col(self.table.columns, self.table.amount_column)
        if i is None:
            return None
        nums = [to_number(r.cells[i]) for r in self.table.rows if i < len(r.cells)]
        nums = [n for n in nums if n is not None]
        return round(sum(nums), 2) if nums else None

    def totals_match(self, tol: float = 0.05, items_sum: float | None = None) -> bool:
        """Items add up to the subtotal, and subtotal + tax equals the total (checks that can be done)."""
        s = items_sum if items_sum is not None else self.items_sum()
        subtotal = self.subtotal if self.subtotal is not None else s
        tax = self.tax or 0.0
        items_ok = s is None or subtotal is None or abs(s - subtotal) <= tol
        total_ok = subtotal is None or abs(subtotal + tax - self.total) <= tol
        return items_ok and total_ok


class QueryResult(BaseModel):
    question: str
    answer: str = Field(description="Direct answer to the question, with numbers")
    data_used: list[str] = Field(description="Which tool calls/figures the answer is based on")


class InvoiceSummary(BaseModel):
    headline: str
    key_figures: list[str]
    flags: list[str] = Field(description="Anomalies, mismatches, or items to review")