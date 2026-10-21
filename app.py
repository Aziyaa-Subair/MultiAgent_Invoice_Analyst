import asyncio
import tempfile
import threading
import uuid
from pathlib import Path

import pandas as pd
import streamlit as st

from agents.extractor import extract_invoice_async
from agents.hs_client import fetch_requirements, lookup_codes
from agents.query_agent import ask_session, make_client
from agents.summarizer import summarize
from export import (
    HEADER_OPTIONS, HS_COLS, XLSX_MIME, add_hs_columns, build_excel, details_table, excel_name,
    find_issues, hs_codes_in, hs_column, role_column, table_frame,
)
from features import BASES, append_sheets, build_landed_cost, checklist_table
from models import to_number

SAMPLE_DIR = Path("data/sample_invoices")
SUPPORTED = {".pdf", ".png", ".jpg", ".jpeg"}
MAX_FILES_PER_RUN = 12
MAX_FILES_PER_SESSION = 24
MAX_QUESTIONS_PER_SESSION = 10
MAX_HS_LOOKUPS_PER_CLICK = 25
MAX_MB = 5

st.set_page_config(page_title="Invoice Analyst Agent", page_icon="🧾", layout="wide")
st.title("🧾 Invoice Analyst Agent")
st.caption(
    "Multi-agent demo: extractor → SQLite via a FastMCP server → query agent → summary agent. "
    "Use the sample or synthetic invoices only. Do not upload confidential documents."
)

# ---- per-visitor state: each visitor gets their own database file
if "session_id" not in st.session_state:
    sid = uuid.uuid4().hex
    st.session_state.session_id = sid
    st.session_state.db_path = Path(tempfile.gettempdir()) / f"invoices_{sid}.db"
    st.session_state.results = []       # list of (source file name, InvoiceData)
    st.session_state.chat = []
    st.session_state.hs_info = {}       # HS code (digits) -> portal answer
    st.session_state.hs_docs = {}       # 12-digit HS code -> document checklist
    st.session_state.version = 0        # bumps on every extraction/clear: resets the editor and column pickers
    st.session_state.uploader_key = 0   # changing this empties the file uploader
    st.session_state.files_done = 0      # usage counters are NOT reset by "Clear all"
    st.session_state.questions_done = 0


def clear_all():
    """Wipe this visitor's data: database, results, answers and selected files."""
    try:
        st.session_state.db_path.unlink(missing_ok=True)
    except OSError:
        pass
    st.session_state.results = []
    st.session_state.chat = []
    st.session_state.hs_info = {}
    st.session_state.hs_docs = {}
    st.session_state.version += 1
    st.session_state.uploader_key += 1
    st.session_state.use_samples = False
    st.session_state.question_text = ""


@st.cache_resource
def _runtime():
    """ONE long-lived event loop (in a background thread) shared by every click and every visitor,
    plus a lock so that two visitors never use the shared model connection at the same moment."""
    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True).start()
    return loop, threading.Lock()


def run(coro):
    """Run async work on that one loop. asyncio.run() would create a new loop for every click and close it,
    which breaks the model's HTTP connections ('Event loop is closed')."""
    loop, lock = _runtime()
    with lock:
        return asyncio.run_coroutine_threadsafe(coro, loop).result()




async def save_to_db(invoices, db_path):
    async with make_client(db_path) as client:
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


async def process(paths, db_path):
    results, errors = [], []
    for p in paths:
        try:
            results.append((p.name, await extract_invoice_async(str(p))))
        except Exception as e:
            errors.append(f"{p.name}: {str(e)[:150]}")
    if results:
        await save_to_db([inv for _, inv in results], db_path)
    return results, errors


# ---- 1. upload / extract
st.subheader("1. Upload invoices")
uploaded = st.file_uploader(
    f"PDF, PNG or JPG. Upload one file for one Excel, or several (up to {MAX_FILES_PER_RUN}) "
    "to get all their items in one Excel.",
    type=["pdf", "png", "jpg", "jpeg"],
    accept_multiple_files=True,
    key=f"uploader_{st.session_state.uploader_key}",
)
use_samples = st.checkbox("Use the built-in sample invoices instead", key="use_samples")

col_extract, col_clear, _ = st.columns([1, 1, 6])
with col_extract:
    extract_clicked = st.button("Extract", type="primary")
with col_clear:
    st.button("Clear all", on_click=clear_all)
st.caption(
    f"Files processed this session: {st.session_state.files_done}/{MAX_FILES_PER_SESSION}"
)

if extract_clicked:
    paths = []
    if use_samples:
        paths = sorted(p for p in SAMPLE_DIR.iterdir() if p.suffix.lower() in SUPPORTED)
    else:
        tmp = Path(tempfile.mkdtemp())
        for f in uploaded or []:
            if f.size > MAX_MB * 1024 * 1024:
                st.error(f"{f.name} is larger than {MAX_MB} MB and was skipped.")
                continue
            dest = tmp / Path(f.name).name
            n = 2
            while dest.exists():  # two uploads with the same file name
                dest = tmp / f"{Path(f.name).stem}_{n}{Path(f.name).suffix}"
                n += 1
            dest.write_bytes(f.getvalue())
            paths.append(dest)

    if not paths:
        st.warning("Upload at least one file, or tick the sample option.")
    elif len(paths) > MAX_FILES_PER_RUN:
        st.error(f"Please process at most {MAX_FILES_PER_RUN} files at a time.")
    elif st.session_state.files_done + len(paths) > MAX_FILES_PER_SESSION:
        st.error("Session limit reached for this demo. Refresh the page to start over.")
    else:
        with st.spinner(f"Extracting {len(paths)} file(s) and saving through the MCP server..."):
            new, errors = run(process(paths, st.session_state.db_path))
        merged = dict(st.session_state.results)   # same file name = replaced, not duplicated
        merged.update(dict(new))
        st.session_state.results = list(merged.items())
        st.session_state.files_done += len(paths)
        st.session_state.version += 1             # fresh editor and column pickers for the new data
        for e in errors:
            st.error(e)

results = st.session_state.results
invoices = [inv for _, inv in results]
ver = st.session_state.version

if results:
    n_files = len(results)

    # ---- 2. review / edit: each invoice keeps ITS OWN column names
    st.subheader("2. Review and edit the extracted items")
    st.caption(
        "Each table has the column names printed on that invoice. "
        "Double-click a cell to correct it. Your edits go into the Excel file."
    )
    tabs = st.tabs([name for name, _ in results]) if n_files > 1 else [st.container()]
    edited: dict[str, pd.DataFrame] = {}
    for idx, ((name, inv), tab) in enumerate(zip(results, tabs)):
        with tab:
            st.caption(
                f"Invoice {inv.invoice_number} | {inv.supplier_name} | {inv.currency or '-'} | "
                f"total {inv.total:,.2f}"
            )
            frame = table_frame(inv)
            if frame.empty and len(frame.columns) == 0:
                st.warning("No item table was found in this file.")
                edited[name] = frame
            else:
                edited[name] = st.data_editor(frame, key=f"editor_{ver}_{idx}", hide_index=True)

    issues = find_issues(edited, results)
    if issues:
        with st.expander(f"⚠️ Checks: {len(issues)} thing(s) to look at", expanded=True):
            for msg in issues:
                st.warning(msg)
    else:
        st.success("Checks passed: totals add up, no duplicate invoice numbers, line maths is consistent.")

    with st.expander("Invoice details (one row per file)"):
        st.dataframe(details_table(results))

    # ---- 3. HS code lookup (second MCP server -> Qatar eCustoms)
    st.subheader("3. HS code duty and approvals (optional)")
    checklist_df = None
    landed_df = None
    codes = hs_codes_in(edited, results)
    hs_info = st.session_state.hs_info
    if not codes:
        st.info("No HS code column was found in these invoices, so there is nothing to look up.")
    else:
        todo = [c for c in codes if c not in hs_info]
        st.caption(
            f"HS codes found: {len(codes)} ({len(codes) - len(todo)} already looked up). "
            "Each is checked on Qatar's eCustoms portal through an MCP tool. "
            "For a short code (6 digits) the portal returns many matches and the first one is used, "
            "so confirm the full 12-digit code before relying on the duty rate."
        )
        if st.button("Look up HS codes", disabled=not todo):
            batch = todo[:MAX_HS_LOOKUPS_PER_CLICK]
            with st.spinner(f"Asking the HS lookup tool about {len(batch)} code(s)..."):
                try:
                    hs_info.update(run(lookup_codes(batch)))
                except Exception as e:
                    st.error("The HS lookup tool could not run. Check that hs_lookup.py is in the project "
                             f"folder. Details: {str(e)[:200]}")
            if len(todo) > len(batch):
                st.warning(f"Only the first {len(batch)} codes were looked up. Click again for the rest.")
        if hs_info:
            st.dataframe(pd.DataFrame(
                [{"hs_code": c, **hs_info[c]} for c in codes if c in hs_info]
            ))
        matched = sorted({v["hs_matched_code"] for v in hs_info.values() if v.get("hs_matched_code")})
        if matched:
            hs_docs = st.session_state.hs_docs
            todo_docs = [c for c in matched if c not in hs_docs]
            st.caption("Import document checklist: the documents each approving agency asks for "
                       "(uses the full 12-digit codes found above).")
            if st.button("Get import document checklist", disabled=not todo_docs):
                with st.spinner(f"Fetching the checklist for {len(todo_docs[:MAX_HS_LOOKUPS_PER_CLICK])} code(s)..."):
                    try:
                        hs_docs.update(run(fetch_requirements(todo_docs[:MAX_HS_LOOKUPS_PER_CLICK])))
                    except Exception as e:
                        st.error(f"The checklist could not be fetched. Details: {str(e)[:200]}")
            if hs_docs:
                checklist_df_all = checklist_table({c: d for c, d in hs_docs.items() if c in matched})
                st.dataframe(checklist_df_all)
                if st.checkbox("Add the import checklist to the Excel file", key=f"inc_check_{ver}"):
                    checklist_df = checklist_df_all
    final = {name: add_hs_columns(edited[name], hs_column(inv, edited[name]), hs_info) for name, inv in results}

    # ---- 4. landed cost
    st.subheader("4. Landed cost (optional)")
    with st.expander("Estimate the landed cost per item for one invoice"):
        st.caption("Estimate only: customs duty is normally charged on the CIF value (item value + freight + "
                   "insurance). Confirm rates and charges with your clearing agent.")
        pick = st.selectbox("Invoice", [n for n, _ in results], key=f"lc_file_{ver}") if n_files > 1 else results[0][0]
        inv_p = dict(results)[pick]
        fr = final[pick]
        desc_c = role_column(inv_p, inv_p.table.description_column)
        qty_c = role_column(inv_p, inv_p.table.quantity_column)
        amt_c = role_column(inv_p, inv_p.table.amount_column)
        duty_c = HS_COLS["hs_duty_pct"] if HS_COLS["hs_duty_pct"] in fr.columns else None
        if amt_c not in fr.columns:
            st.info("This invoice has no amount column, so a landed cost cannot be calculated.")
        else:
            n_rows = len(fr)
            inputs = pd.DataFrame({
                "Description": list(fr[desc_c]) if desc_c in fr.columns else [f"Item {i + 1}" for i in range(n_rows)],
                "Quantity": pd.to_numeric([to_number(v) for v in fr[qty_c]] if qty_c in fr.columns else [None] * n_rows,
                                          errors="coerce"),
                "Value": pd.to_numeric([to_number(v) for v in fr[amt_c]], errors="coerce"),
                "Duty %": pd.to_numeric(list(fr[duty_c]) if duty_c else [None] * n_rows, errors="coerce"),
                "CBM or weight": pd.to_numeric([None] * n_rows, errors="coerce"),
            })
            c1, c2, c3 = st.columns(3)
            freight = c1.number_input("Freight + insurance", min_value=0.0, step=100.0, key=f"lc_freight_{ver}")
            local = c2.number_input("Local costs (clearance, transport ...)", min_value=0.0, step=50.0,
                                    key=f"lc_local_{ver}")
            basis = c3.radio("Share these costs by", BASES, key=f"lc_basis_{ver}")
            st.caption("Amounts are in the invoice currency. Edit Duty % (and CBM or weight if you share by it).")
            lc_in = st.data_editor(
                inputs, key=f"lc_edit_{ver}_{pick}_{int(duty_c is not None)}", hide_index=True,
                disabled=["Description", "Quantity", "Value"],
            )
            try:
                lc, lc_notes = build_landed_cost(lc_in, freight, local, basis)
            except ValueError as e:
                lc, lc_notes = None, []
                st.warning(str(e))
            if lc is not None:
                st.dataframe(lc)
                m1, m2, m3 = st.columns(3)
                m1.metric("Total value", f"{lc['Value'].sum():,.2f}")
                m2.metric("Total duty", f"{lc['Duty amount'].sum():,.2f}")
                m3.metric("Total landed cost", f"{lc['Landed cost'].sum():,.2f}")
                for note in lc_notes:
                    st.caption(note)
                if st.checkbox("Add this landed cost table to the Excel file", key=f"inc_landed_{ver}"):
                    landed_df = lc.copy()
                    landed_df.insert(0, "Source file", pick)

    # ---- 5. choose columns + download
    st.subheader("5. Choose the Excel columns")
    mode = st.radio(
        "Columns in the Excel file",
        ["Select all", "Choose columns"],
        horizontal=True,
        key=f"col_mode_{ver}",
    )
    selected: dict[str, list[str]] = {}
    for idx, (name, inv) in enumerate(results):
        cols = list(final[name].columns)
        if mode == "Select all":
            selected[name] = cols
        else:
            with st.expander(f"{name}: the columns of this invoice", expanded=(idx == 0 or n_files == 1)):
                selected[name] = st.multiselect(
                    "Columns to include (names as printed on the invoice)",
                    cols, default=cols, key=f"cols_{ver}_{idx}",
                )

    layout = "one_sheet"
    if n_files > 1:
        choice = st.radio(
            "Layout",
            ["All items in one sheet (with a PDF name column)", "One sheet per PDF"],
            horizontal=True,
            key=f"layout_{ver}",
        )
        layout = "per_pdf" if choice == "One sheet per PDF" else "one_sheet"

    header_info: list[str] = []
    if layout == "one_sheet":
        header_info = st.multiselect(
            "Add invoice details as extra columns (optional)",
            list(HEADER_OPTIONS),
            default=["Invoice number"] if n_files > 1 else [],
            key=f"hinfo_{ver}",
        )

    if not any(selected.values()):
        st.info("Pick at least one column to build the Excel file.")
    else:
        xlsx_data = build_excel(final, selected, results, layout, header_info)
        extra_sheets = {}
        if checklist_df is not None:
            extra_sheets["Import checklist"] = checklist_df
        if landed_df is not None:
            extra_sheets["Landed cost"] = landed_df
        if extra_sheets:
            xlsx_data = append_sheets(xlsx_data, extra_sheets)
        st.download_button(
            "Download Excel",
            data=xlsx_data,
            file_name=excel_name(results[0][0]) if n_files == 1 else "combined_items.xlsx",
            mime=XLSX_MIME,
            key=f"dl_{ver}",
        )

    # ---- 6. ask questions (query agent -> MCP server -> SQLite)
    st.subheader("6. Ask about your invoices")
    q = st.text_input(
        "Example: Which supplier has the highest total billed in each currency?",
        key="question_text",
    )
    if st.button("Ask") and q.strip():
        if st.session_state.questions_done >= MAX_QUESTIONS_PER_SESSION:
            st.error("Question limit reached for this demo session.")
        else:
            with st.spinner("Query agent is calling the MCP server..."):
                try:
                    res = run(ask_session(q.strip(), st.session_state.db_path))
                    st.session_state.chat.append((q.strip(), res.answer))
                    st.session_state.questions_done += 1
                except Exception as e:
                    st.error(f"Query failed: {str(e)[:200]}")
    for question, answer in reversed(st.session_state.chat):
        st.markdown(f"**Q:** {question}")
        st.markdown(answer)

    # ---- 7. summary agent
    st.subheader("7. Summary")
    if st.button("Write summary"):
        with st.spinner("Summary agent is working..."):
            try:
                s = run(summarize(invoices, []))
                st.markdown(f"**{s.headline}**")
                for k in s.key_figures:
                    st.markdown(f"- {k}")
                for f in s.flags:
                    st.warning(f)
            except Exception as e:
                st.error(f"Summary failed: {str(e)[:200]}")