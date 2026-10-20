"""Offline tests: no API key, no network. Run with:  pytest"""
import io
from datetime import date

import pandas as pd
import pytest

from export import (HS_COLS, add_hs_columns, build_excel, convert_numeric, export_to_excel, find_issues,
                    hs_codes_in, hs_column, table_frame, unique_headers)
from features import append_sheets, build_landed_cost, checklist_table
from models import InvoiceData, ItemTable, NamedValue, TableRow, find_col, to_number


def make_invoice(number, cols, rows, subtotal, tax, total, **roles):
    return InvoiceData(
        invoice_number=number, invoice_date=date(2026, 10, 12), supplier_name="Supplier", customer_name="Customer",
        currency="QAR", subtotal=subtotal, tax=tax, total=total,
        table=ItemTable(columns=cols, rows=[TableRow(cells=r) for r in rows], **roles),
    )


@pytest.fixture
def inv_hs():
    return make_invoice(
        "GSP-1", ["No", "Description", "HS Code", "Qty", "Unit Price", "Amount"],
        [["1", "Brake pads", "8708.30", "12", "85.00", "1,020.00"], ["2", "Oil filter", "8421.23", "40", "12.50", "500.00"]],
        1520.0, 0.0, 1520.0, description_column="Description", quantity_column="Qty",
        unit_price_column="Unit Price", amount_column="Amount", hs_code_column="HS Code")


@pytest.fixture
def inv_vat():
    return make_invoice(
        "ASO-2", ["Description", "Qty", "Unit Price", "VAT %", "VAT Amount", "Amount (excl. VAT)"],
        [["Paper", "20", "95.00", "5%", "95.00", "1,900.00"], ["Toner", "6", "310.00", "5%", "93.00", "1,860.00"]],
        3760.0, 188.0, 3948.0, description_column="Description", quantity_column="Qty",
        unit_price_column="Unit Price", amount_column="Amount (excl. VAT)")


@pytest.fixture
def inv_plain():
    return make_invoice(
        "MCS-3", ["Description", "Unit", "Qty", "Rate", "Amount"],
        [["Cleaning", "Month", "1", "2,500.00", "2,500.00"], ["Windows", "Visit", "4", "350.00", "1,400.00"]],
        3900.0, 0.0, 3900.0, description_column="Description", quantity_column="Qty",
        unit_price_column="Rate", amount_column="Amount")


def sheets(data: bytes):
    return pd.read_excel(io.BytesIO(data), sheet_name=None, dtype=object)


# ------------------------------------------------------------ numbers and headers
def test_to_number():
    assert to_number("1,020.00") == 1020.0
    assert to_number("5%") == 5.0
    assert to_number("QAR 12.5") == 12.5
    assert to_number("abc") is None and to_number("") is None and to_number(None) is None


def test_find_col_exact_then_ignoring_case():
    cols = ["Description", "Qty"]
    assert find_col(cols, "Qty") == 1 and find_col(cols, " qty ") == 1
    assert find_col(cols, "Price") is None and find_col(cols, None) is None


def test_headers_are_kept_exactly_as_printed(inv_vat):
    assert list(table_frame(inv_vat).columns) == ["Description", "Qty", "Unit Price", "VAT %", "VAT Amount", "Amount (excl. VAT)"]


def test_repeated_or_empty_headers_are_numbered():
    assert unique_headers(["Amount", "Amount", ""]) == ["Amount", "Amount (2)", "Column 3"]


def test_short_rows_are_padded():
    inv = make_invoice("X", ["A", "B", "C"], [["1", "2"]], None, None, 1.0)
    assert table_frame(inv).iloc[0].tolist() == ["1", "2", ""]


# ------------------------------------------------------------ totals and checks
def test_totals_match(inv_hs, inv_vat):
    assert inv_hs.totals_match() and inv_vat.totals_match()
    inv_hs.total = 1600.0
    assert not inv_hs.totals_match()


def test_edited_amount_is_reported(inv_hs):
    frames = {"a.pdf": table_frame(inv_hs)}
    assert find_issues(frames, [("a.pdf", inv_hs)]) == []
    frames["a.pdf"].loc[0, "Amount"] = "9,999.00"
    msgs = find_issues(frames, [("a.pdf", inv_hs)])
    assert any("totals do not add up" in m for m in msgs) and any("row 1" in m for m in msgs)


def test_duplicate_invoice_numbers(inv_hs):
    frames = {"a.pdf": table_frame(inv_hs), "b.pdf": table_frame(inv_hs)}
    assert any("appears in 2 files" in m for m in find_issues(frames, [("a.pdf", inv_hs), ("b.pdf", inv_hs)]))


# ------------------------------------------------------------ HS code handling
def test_hs_column_by_role_and_by_name(inv_hs, inv_vat):
    assert hs_column(inv_hs, table_frame(inv_hs)) == "HS Code"
    assert hs_column(inv_vat, table_frame(inv_vat)) is None
    inv_hs.table.hs_code_column = None   # the model gave no role: fall back to the header name
    assert hs_column(inv_hs, table_frame(inv_hs)) == "HS Code"


def test_hs_codes_are_digits_and_unique(inv_hs):
    inv_hs.table.rows.append(TableRow(cells=["3", "Pads 2", "8708.30", "1", "10.00", "10.00"]))
    assert hs_codes_in({"a.pdf": table_frame(inv_hs)}, [("a.pdf", inv_hs)]) == ["870830", "842123"]


def test_hs_columns_are_added_right_after_hs_code(inv_hs):
    info = {"870830": {"hs_matched_code": "870830100001", "hs_duty_pct": 5.0}}
    out = add_hs_columns(table_frame(inv_hs), "HS Code", info)
    cols = list(out.columns)
    assert cols[cols.index("HS Code") + 1] == HS_COLS["hs_matched_code"]
    assert out[HS_COLS["hs_duty_pct"]].tolist()[0] == 5.0


def test_numbers_become_numeric_but_codes_stay_text(inv_hs):
    out = convert_numeric(table_frame(inv_hs), protect={"HS Code"})
    assert out["Qty"].tolist() == [12.0, 40.0] and out["Amount"].tolist() == [1020.0, 500.0]
    assert out["HS Code"].tolist() == ["8708.30", "8421.23"] and out["No"].tolist() == ["1", "2"]


# ------------------------------------------------------------ Excel
def test_one_file_gives_items_and_details(inv_hs):
    f = table_frame(inv_hs)
    s = sheets(build_excel({"a.pdf": f}, {"a.pdf": list(f.columns)}, [("a.pdf", inv_hs)]))
    assert list(s) == ["Items", "Invoice details"]
    assert list(s["Items"].columns) == list(f.columns)


def test_several_files_one_sheet_has_source_file_and_blanks(inv_hs, inv_vat):
    res = [("hs.pdf", inv_hs), ("vat.pdf", inv_vat)]
    frames = {n: table_frame(i) for n, i in res}
    s = sheets(build_excel(frames, {n: list(f.columns) for n, f in frames.items()}, res, "one_sheet", ["Invoice number"]))
    all_items = s["All items"]
    assert list(all_items.columns)[:2] == ["Source file", "Invoice number"]
    assert len(all_items) == 4
    assert all_items.loc[all_items["Source file"] == "hs.pdf", "VAT %"].isna().all()
    assert all_items.loc[all_items["Source file"] == "vat.pdf", "HS Code"].isna().all()


def test_per_pdf_sheets_keep_each_invoices_own_columns(inv_hs, inv_plain):
    res = [("hs.pdf", inv_hs), ("plain.pdf", inv_plain)]
    frames = {n: table_frame(i) for n, i in res}
    s = sheets(build_excel(frames, {n: list(f.columns) for n, f in frames.items()}, res, "per_pdf"))
    assert list(s["hs"].columns) == list(frames["hs.pdf"].columns)
    assert list(s["plain"].columns) == ["Description", "Unit", "Qty", "Rate", "Amount"]


def test_only_selected_columns_are_written(inv_hs):
    f = table_frame(inv_hs)
    s = sheets(build_excel({"a.pdf": f}, {"a.pdf": ["Description", "HS Code"]}, [("a.pdf", inv_hs)]))
    assert list(s["Items"].columns) == ["Description", "HS Code"]


def test_combined_export_used_by_evaluate_script(tmp_path, inv_hs, inv_plain):
    out = tmp_path / "invoices.xlsx"
    export_to_excel([inv_hs, inv_plain], str(out))
    s = pd.read_excel(out, sheet_name=None)
    assert {"Invoices", "Line Items"} <= set(s)
    assert s["Line Items"].groupby("invoice_number").size().to_dict() == {"GSP-1": 2, "MCS-3": 2}


# ------------------------------------------------------------ landed cost
def landed_items(duties=(5.0, None), cbm=(None, None)):
    return pd.DataFrame({
        "Description": ["A", "B"], "Quantity": [10.0, 30.0], "Value": [1000.0, 3000.0],
        "Duty %": list(duties), "CBM or weight": list(cbm),
    })


def test_landed_cost_shared_by_value():
    out, notes = build_landed_cost(landed_items(), freight=400.0, local_costs=200.0, basis="Value")
    assert out["CIF value"].tolist() == [1100.0, 3300.0]
    assert out["Duty amount"].tolist() == [55.0, 0.0]
    assert out["Landed cost"].tolist() == [1205.0, 3450.0]
    assert out["Landed cost per unit"].tolist() == [120.5, 115.0]
    assert out["Uplift %"].tolist() == [20.5, 15.0]
    assert any("Duty % is missing for 1 item" in n for n in notes)


def test_landed_cost_shared_by_cbm():
    out, _ = build_landed_cost(landed_items(duties=(0.0, 0.0), cbm=(3.0, 1.0)), 400.0, 0.0, "CBM or weight")
    assert out["Freight + insurance share"].tolist() == [300.0, 100.0]


def test_landed_cost_needs_the_sharing_column():
    with pytest.raises(ValueError):
        build_landed_cost(landed_items(), 400.0, 0.0, "CBM or weight")


# ------------------------------------------------------------ import checklist and extra sheets
REQ = {
    "870830100001": {"found": True, "final_description": "Brake pads", "rate": "5", "agencies": [
        {"name_en": "Ministry of Transport", "website": "https://mot.gov.qa", "documents": ["Import permit", "Certificate"]},
        {"name_en": "Qatar General Standards", "website": "", "documents": []}]},
    "842123000001": {"found": True, "final_description": "Oil filters", "rate": "5", "agencies": []},
    "111111111111": {"found": False, "error": "No detail found for this code."},
}


def test_checklist_has_one_row_per_document():
    t = checklist_table(REQ)
    assert len(t[t["HS code"] == "870830100001"]) == 3
    assert t.loc[t["HS code"] == "842123000001", "Agency"].iloc[0] == "None (standard clearance)"
    assert "Not available" in t.loc[t["HS code"] == "111111111111", "Document"].iloc[0]


def test_extra_sheets_are_appended(inv_hs):
    f = table_frame(inv_hs)
    base = build_excel({"a.pdf": f}, {"a.pdf": list(f.columns)}, [("a.pdf", inv_hs)])
    s = sheets(append_sheets(base, {"Import checklist": checklist_table(REQ)}))
    assert list(s) == ["Items", "Invoice details", "Import checklist"]