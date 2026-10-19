from dotenv import load_dotenv
from pydantic_ai import Agent

from config import MODEL
from models import InvoiceData, InvoiceSummary, QueryResult

load_dotenv()

summary_agent = Agent(
    MODEL,
    output_type=InvoiceSummary,
    retries=2,
    system_prompt=(
        "You write short business summaries for a non-technical manager. "
        "Use only the facts given. Put anything unusual in 'flags': "
        "mismatched totals, missing fields, or one supplier dominating spend."
    ),
)


async def summarize(invoices: list[InvoiceData], answers: list[QueryResult]) -> InvoiceSummary:
    facts = "\n".join(
        f"- {i.invoice_number} | {i.supplier_name} | {i.total} {i.currency} "
        f"| totals_match={i.totals_match()}"
        for i in invoices
    )
    qa = "\n".join(f"Q: {a.question}\nA: {a.answer}" for a in answers)
    prompt = f"Invoices processed this run:\n{facts}\n\nDatabase findings:\n{qa}"
    async with summary_agent:  # reopens the shared model connection
        result = await summary_agent.run(prompt)
    return result.output