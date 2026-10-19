from pathlib import Path

from dotenv import load_dotenv
from fastmcp import Client
from fastmcp.client.transports import PythonStdioTransport
from pydantic_ai import Agent
from pydantic_ai.mcp import MCPToolset

from config import MODEL
from models import QueryResult

load_dotenv()

SERVER_PATH = Path(__file__).resolve().parent.parent / "mcp_server" / "server.py"

SYSTEM_PROMPT = (
    "You answer questions about invoices using ONLY the provided tools. "
    "Never invent numbers. If the data does not contain the answer, say so. "
    "Always state the currency next to amounts, and never add amounts "
    "in different currencies together."
)


def build_agent(toolset) -> Agent:
    return Agent(
        MODEL,
        output_type=QueryResult,
        toolsets=[toolset],
        retries=2,
        system_prompt=SYSTEM_PROMPT,
    )


def make_client(db_path) -> Client:
    """A client that starts the MCP server on a specific SQLite file."""
    return Client(PythonStdioTransport(SERVER_PATH, args=[str(db_path)]))


# Used by pipeline.py (command line): server uses its default data/invoices.db
query_agent = build_agent(MCPToolset(SERVER_PATH))


async def ask(question: str) -> QueryResult:
    async with query_agent:
        result = await query_agent.run(question)
    return result.output


# Used by the web app: one database per visitor session
async def ask_session(question: str, db_path) -> QueryResult:
    agent = build_agent(MCPToolset(make_client(db_path)))
    async with agent:
        result = await agent.run(question)
    return result.output