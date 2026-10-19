from pathlib import Path

from agents.extractor import extract_invoice
from export import excel_name, export_to_excel, invoice_xlsx_bytes

SUPPORTED = {".pdf", ".png", ".jpg", ".jpeg"}
files = sorted(
    p for p in Path("data/sample_invoices").iterdir()
    if p.suffix.lower() in SUPPORTED
)
print(f"Found {len(files)} files")

results, failed = [], []
for f in files:
    try:
        inv = extract_invoice(str(f))
        results.append((f.name, inv))
        print(f"OK   {f.name}: {inv.invoice_number}, {len(inv.table.rows)} items, total={inv.total}, match={inv.totals_match()}")
    except Exception as e:
        failed.append(f.name)
        print(f"FAIL {f.name}: {e}")

if results:
    # one Excel per invoice, named after the source file
    out_dir = Path("output/per_invoice")
    out_dir.mkdir(parents=True, exist_ok=True)
    used = set()
    for name, inv in results:
        base = excel_name(name)[:-5]  # file name without ".xlsx"
        fname, n = base, 2
        while fname in used:  # e.g. a.pdf and a.png would both become a.xlsx
            fname, n = f"{base}_{n}", n + 1
        used.add(fname)
        (out_dir / f"{fname}.xlsx").write_bytes(invoice_xlsx_bytes(inv))

    # plus one combined file (evaluate.py reads this one)
    export_to_excel([inv for _, inv in results], "output/invoices.xlsx")
    print(f"\n{len(results)} extracted, {len(failed)} failed")
    print(f"Per-invoice files: {out_dir}")
    print("Combined file:     output/invoices.xlsx")
    if failed:
        print("Failed files:", ", ".join(failed))
else:
    print("\nNothing extracted, so no Excel file was written.")