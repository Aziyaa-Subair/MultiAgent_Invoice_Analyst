import asyncio
import time
from io import BytesIO
from pathlib import Path

import pdfplumber
from dotenv import load_dotenv
from pydantic_ai import Agent, BinaryContent

from config import MODEL
from models import InvoiceData

load_dotenv()

extractor_agent = Agent(
    MODEL,
    output_type=InvoiceData,
    retries=2,
    system_prompt=(
        "You extract structured data from invoices. Only use information present in the document. "
        "If a field is missing, return null. Never guess amounts. "
        "Copy the total exactly as printed, even if it looks wrong. Dates must be YYYY-MM-DD. "
        "ITEM TABLE: reproduce the invoice's item table exactly as printed. "
        "'columns' = the column headers exactly as printed (same spelling, case and punctuation), left to right. "
        "Do not rename, translate, merge, split, reorder, add or drop columns. "
        "'rows' = one row per item line, one cell per column, values exactly as printed "
        "(keep thousands separators and % signs); use an empty string for a blank cell. "
        "Never put subtotal, VAT or total lines in the rows. "
        "If the input contains a TABLES section, use it for the headers and for which cell belongs to which "
        "column; use the plain text only for everything else. "
        "Then name the roles by copying the matching header from 'columns': description_column, "
        "quantity_column, unit_price_column, amount_column (the per-line total), and hs_code_column "
        "(HS code / tariff code, if present). Leave a role null if no column matches. "
        "Other invoice-level details that are printed (PO number, VAT/TRN number, BL or AWB number, "
        "container number, incoterms, payment terms) go in 'other_fields' with their printed labels."
    ),
)

IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}


def read_pdf_text(path: str) -> str:
    """Plain text of the PDF, followed by a TABLES section with the detected tables (cells joined by ' | ')."""
    with pdfplumber.open(path) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)
        tables = []
        for page in pdf.pages:
            for t in page.extract_tables():
                tables.append("\n".join(
                    " | ".join((c or "").replace("\n", " ").strip() for c in row) for row in t
                ))
    if text.strip() and tables:
        text += "\n\n--- TABLES (cells separated by ' | ') ---\n" + "\n\n".join(tables)
    return text


def pdf_to_image_bytes(path: str) -> bytes:
    """Render page 1 of an image-only PDF to PNG bytes."""
    with pdfplumber.open(path) as pdf:
        img = pdf.pages[0].to_image(resolution=150).original
        buf = BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()


def build_input(path: str):
    suffix = Path(path).suffix.lower()

    if suffix in IMAGE_TYPES:
        return [
            "Extract the invoice data from this image.",
            BinaryContent(data=Path(path).read_bytes(), media_type=IMAGE_TYPES[suffix]),
        ]

    if suffix == ".pdf":
        text = read_pdf_text(path)
        if text.strip():
            return f"Invoice text:\n\n{text}"
        return [
            "Extract the invoice data from this scanned page.",
            BinaryContent(data=pdf_to_image_bytes(path), media_type="image/png"),
        ]

    raise ValueError(f"Unsupported file type: {suffix}")


def extract_invoice(path: str, attempts: int = 4) -> InvoiceData:
    prompt = build_input(path)
    for attempt in range(1, attempts + 1):
        try:
            return extractor_agent.run_sync(prompt).output
        except Exception as e:
            if attempt == attempts:
                raise
            wait = 5 * attempt
            print(f"  retry {attempt}/{attempts - 1}, waiting {wait}s: {str(e)[:80]}")
            time.sleep(wait)


async def extract_invoice_async(path: str, attempts: int = 4) -> InvoiceData:
    """Async version for the web app. `async with` reopens the shared model connection."""
    prompt = build_input(path)
    for attempt in range(1, attempts + 1):
        try:
            async with extractor_agent:
                result = await extractor_agent.run(prompt)
            return result.output
        except Exception:
            if attempt == attempts:
                raise
            await asyncio.sleep(5 * attempt)