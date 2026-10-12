"""
Read-only viewer for orchestrator audit logs (JSONL). Does NOT replace the
CLI task runner — tasks still run via `python run_task.py <config>` in a
terminal. This renders the resulting log afterwards (or mid-run, via the
Refresh button) for a clearer visual trace than raw terminal output.
"""
import json
from pathlib import Path

import streamlit as st

st.set_page_config(page_title="CentrAlign Agent — Execution Trace", layout="wide")
st.title("🤖 CentrAlign Agent — Execution Trace Viewer")

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

log_files = sorted(LOG_DIR.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)

if not log_files:
    st.info("No log files found yet. Run a task first, e.g.:\n\n`python run_task.py tasks/configs/invoice_entry.json`")
    st.stop()

selected = st.sidebar.selectbox("Select a run", log_files, format_func=lambda p: p.name)
st.sidebar.button("🔄 Refresh")

ICONS = {
    "TASK_START": "🚀", "PLAN_CREATED": "🗺️", "DECISION": "🤔",
    "OBSERVATION": "👁️", "ERROR_CLASSIFIED": "⚠️", "RETRYING": "🔁",
    "CIRCUIT_BREAKER_TRIPPED": "🛑", "CIRCUIT_BREAKER_FORCED_ESCALATION": "🛑",
    "HUMAN_RESPONSE": "🧑", "REPLAN": "🔄", "VERIFICATION": "✅",
    "VERIFICATION_NOT_PASSED_CONTINUING": "🟡", "TASK_END": "🏁",
    "MAX_STEPS_REACHED": "⏱️", "PLANNER_ERROR": "❌", "DECISION_ENGINE_ERROR": "❌",
    "INVALID_DECISION": "❌", "PARAM_PARSE_ERROR": "❌",
}

lines = selected.read_text(encoding="utf-8").strip().splitlines()

for line in lines:
    try:
        entry = json.loads(line)
    except json.JSONDecodeError:
        continue
    event = entry.get("event", "UNKNOWN")
    icon = ICONS.get(event, "•")
    ts = entry.get("timestamp", "")[11:19]
    with st.container(border=True):
        st.markdown(f"**{icon} `{event}`** &nbsp;&nbsp; `{ts}`")
        details = {k: v for k, v in entry.items() if k not in ("event", "timestamp")}
        if details:
            st.json(details, expanded=False)