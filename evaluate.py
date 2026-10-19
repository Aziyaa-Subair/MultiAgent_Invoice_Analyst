import pandas as pd

KEY_PATH = "data/sample_invoices/answer_key.csv"
OUT_PATH = "output/invoices.xlsx"

key = pd.read_csv(KEY_PATH)
inv = pd.read_excel(OUT_PATH, sheet_name="Invoices")
lines = pd.read_excel(OUT_PATH, sheet_name="Line Items")

counts = lines.groupby("invoice_number").size().rename("line_item_count")
got = inv.merge(counts, left_on="invoice_number", right_index=True, how="left")
got["date"] = pd.to_datetime(got["date"]).dt.strftime("%Y-%m-%d")
got["tax"] = got["tax"].fillna(0)  # no tax printed = 0 (null and 0 are treated as equal)
got = got.add_suffix("_got")

df = key.merge(got, left_on="invoice_number", right_on="invoice_number_got", how="left")

PAIRS = [
    ("invoice_number", "invoice_number_got"),
    ("invoice_date", "date_got"),
    ("supplier_name", "supplier_got"),
    ("currency", "currency_got"),
    ("line_item_count", "line_item_count_got"),
    ("subtotal", "subtotal_got"),
    ("tax", "tax_got"),
    ("total", "total_got"),
    ("totals_should_match", "totals_match_got"),
]


def same(a, b):
    if pd.isna(a) or pd.isna(b):
        return bool(pd.isna(a) and pd.isna(b))
    try:
        return abs(float(a) - float(b)) <= 0.01
    except (TypeError, ValueError):
        return str(a).strip().lower() == str(b).strip().lower()


errors, total_ok, total_n = [], 0, 0
print(f"{'field':<22}{'correct':>8}")
for exp_col, got_col in PAIRS:
    ok = [same(r[exp_col], r[got_col]) for _, r in df.iterrows()]
    total_ok += sum(ok)
    total_n += len(ok)
    print(f"{exp_col:<22}{sum(ok):>4}/{len(ok)}")
    for (_, r), good in zip(df.iterrows(), ok):
        if not good:
            errors.append(f"  {r['file']}: {exp_col} expected {r[exp_col]!r}, got {r[got_col]!r}")

print(f"\nOverall field accuracy: {total_ok}/{total_n} = {100 * total_ok / total_n:.1f}%")
if errors:
    print("\nMistakes:")
    print("\n".join(errors))
else:
    print("\nNo mistakes on this test set.")