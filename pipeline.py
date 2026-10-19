import asyncio
from pathlib import Path

import pandas as pd
from fastmcp import Client

from agents.extractor import extract_invoice
from agents.query_agent import ask
from agents.summarizer import summarize
from export import export_to_excel

SERVER = Path(__file__).resolve().parent / "mcp_server" / "server.py"
SUPPORTED = {".pdf", ".png", ".jpg", ".jpeg"}

QUESTIONS = [
    "Which supplier has the highest total billed in each currency, and how much?",
    "What is the total billed per month in each currency?",
]


def extract_all():
    files = sorted(
        p for p in Path("data/sample_invoices").iterdir()
        if p.suffix.lower() in SUPPORTED
    )
    print(f"Found {len(files)} files")
    invoices = []
    for f in files:
        try:
            inv = extract_invoice(str(f))
            invoices.append(inv)
            print(f"OK   {f.name}: {inv.invoice_number}, match={inv.totals_match()}")
        except Exception as e:
            print(f"FAIL {f.name}: {e}")
    return invoices


async def save_to_db(invoices):
    """Save through the MCP server so the database has one writer."""
    async with Client(SERVER) as client:
        for inv in invoices:
            await client.call_tool("save_invoice", {
                "invoice_number": inv.invoice_number,
                "supplier_name": inv.supplier_name,
                "total": inv.total,
                "invoice_date": inv.invoice_date.isoformat() if inv.invoice_date else None,
                "customer_name": inv.customer_name,
                "currency": inv.currency,
                "subtotal": inv.subtotal,
                "tax": inv.tax,
            })
    print(f"Saved {len(invoices)} invoices via MCP server")


async def run_agents(invoices):
    await save_to_db(invoices)
    answers = []
    for q in QUESTIONS:
        a = await ask(q)
        print(f"\nQ: {a.question}\nA: {a.answer}")
        answers.append(a)
    summary = await summarize(invoices, answers)
    return answers, summary


def main():
    invoices = extract_all()  # sync, runs before the async part
    if not invoices:
        print("Nothing extracted.")
        return

    answers, summary = asyncio.run(run_agents(invoices))

    export_to_excel(invoices, "output/invoices.xlsx")
    rows = [("Headline", summary.headline)]
    rows += [("Key figure", k) for k in summary.key_figures]
    rows += [("Flag", f) for f in summary.flags]
    rows += [("Question", f"{a.question} -> {a.answer}") for a in answers]
    with pd.ExcelWriter("output/invoices.xlsx", mode="a", engine="openpyxl") as w:
        pd.DataFrame(rows, columns=["Type", "Detail"]).to_excel(w, sheet_name="Summary", index=False)

    print("\nHEADLINE:", summary.headline)
    for f in summary.flags:
        print("FLAG:", f)


if __name__ == "__main__":
    main()