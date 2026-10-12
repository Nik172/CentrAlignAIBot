# CentrAlign AI — Autonomous AI Task Worker (Prototype)

A prototype autonomous AI worker that takes a natural-language goal and independently plans, executes, and verifies the task using real tools against mock company systems — with genuine failure recovery, human escalation, and independent verification.

Built for the CentrAlign AI Engineering hiring challenge.

---

## What It Does

Given a goal like *"Find the invoice from Company X, extract the amount and due date, and enter it into the internal system,"* the system:

1. **Plans** a draft approach via an LLM call
2. **Executes** step-by-step, re-deciding the next action every iteration based on fresh state
3. **Classifies failures** (transient / ambiguous / permanent) and retries, adapts, or escalates
4. **Escalates to a human** when it can't safely proceed, instead of guessing
5. **Independently verifies** the outcome by re-querying the real system state — never trusting its own self-report
6. **Logs** every decision as a structured audit trail

The same core engine runs **two unrelated workflows** — invoice entry and support-ticket triage — against two separate mock backends, with **zero changes to the orchestration/decision/verification code**, proving generalization.

---

## Architecture

```
TASK CONFIG (goal + success criteria + tools)
        │
        ▼
    PLANNER (LLM) → draft plan
        │
        ▼
┌──────────────────────────────────────────────────┐
│              ORCHESTRATOR (control loop)          │
│  loop: check circuit breaker                      │
│    → DECISION ENGINE (LLM): pick single next step │
│    → ACT | ASK_HUMAN | REPLAN | DECLARE_DONE       │
│  on failure: ERROR CLASSIFIER (rule-based)         │
│    transient → retry  |  ambiguous/permanent → ask │
└──────────────────────────────────────────────────┘
        │
        ▼
  TOOL LAYER: execute(params) → Observation
    • FileReaderTool   • ApiTool
        │
        ▼
  MOCK COMPANY ENVIRONMENTS (FastAPI + SQLite)
    • Invoice System (5001)   • Ticket System (5002)
    • Shared chaos-injection layer
        │
        ▼
  VERIFIER → independently re-queries real system state
        │
        ▼
  AUDIT LOG (JSONL) + TASK SUMMARY

Cross-cutting: LLM PROVIDER LAYER
  Groq (primary) → Gemini (fallback), each with
  internal model-candidate retry
```

**Why re-reasoning each step:** the Decision Engine is called once per step, not once per task — given fresh state every time, so it adapts to failures instead of blindly running a precommitted plan.

**Why the Verifier is independent:** it re-queries the mock backend directly rather than trusting the executor's self-report — this catches cases where the agent believes it succeeded but the system actually rejected the write.

**Why error classification is rule-based, not LLM-based:** retry/escalate decisions need to be predictable and auditable, not subject to model judgment.

---

## Setup

```bash
git clone <your-repo-url>
cd centrAlignInternAgent
python -m venv centrvenv
centrvenv\Scripts\activate        # Windows
# source centrvenv/bin/activate   # macOS/Linux

pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` with free API keys from [Groq](https://console.groq.com) and [Google AI Studio](https://aistudio.google.com):
```
GEMINI_API_KEY=your_real_gemini_key
GROQ_API_KEY=your_real_groq_key
GEMINI_MODEL=gemini-2.5-flash
GROQ_MODEL=openai/gpt-oss-20b
```

Run tests to confirm setup:
```bash
python -m pytest tests/ -v
```

---

## Running

**Terminal 1:**
```bash
uvicorn mock_envs.internal_system_app.main:app --port 5001
```

**Terminal 2:**
```bash
uvicorn mock_envs.ticket_system_app.main:app --port 5002
```

**Terminal 3 — run a task:**
```bash
python run_task.py tasks/configs/invoice_entry.json
```

**Optional log viewer:**
```bash
streamlit run ui/streamlit_log_viewer.py
```

### Demo scenarios

| Config | Demonstrates |
|---|---|
| `tasks/configs/invoice_entry.json` | Full loop: find → extract → policy check → submit → verify |
| `tasks/configs/invoice_entry_companyY.json` | Missing data → agent asks a human instead of guessing |
| `tasks/configs/ticket_triage.json` | Same core code, different task domain |

### Trigger live chaos injection

```powershell
Invoke-RestMethod -Uri "http://localhost:5001/admin/chaos" -Method POST `
  -ContentType "application/json" `
  -Body '{"target": "/invoices", "mode": "error_500", "times": 1}'
```
Modes: `timeout`, `error_500`, `missing_field`, `rename_field`.

---

## Key Design Decisions

- **No agent framework** (LangChain/LangGraph, etc.) — orchestrator, planner, decision engine, error classifier, and verifier are hand-built, to demonstrate the actual mechanics rather than hide them behind abstractions.
- **Pydantic schemas** as the single source of truth for every structured object, including LLM output.
- **Tool parameters as JSON strings**, not nested dicts — works around Gemini's free-tier structured-output limitations.
- **Multi-provider LLM fallback with model-candidate retry** — built after hitting real Gemini quota exhaustion and Groq model deprecation live during development; this is a genuine reliability mechanism, exercised for real.
- **Independent, rule-based verification and error classification** — deliberately not LLM-driven, so success/failure handling stays predictable and testable without live model calls (see `tests/test_orchestrator_chaos.py`).
- **Generalization proven, not claimed** — invoice entry and ticket triage share 100% of `core/`; only task configs and mock backends differ.

---

## Models, APIs & Libraries Used

- **LLMs:** Groq (`openai/gpt-oss-20b`, primary) and Google Gemini (`gemini-2.5-flash`, fallback), via a custom multi-provider client with automatic failover
- **Backend:** FastAPI + raw SQLite (two mock company systems), Jinja2 for the invoice UI
- **Other:** `pydantic`, `httpx`, `python-dotenv`, `pytest`, `streamlit`, `google-genai`, `groq`
- **No pre-built agent frameworks** — orchestration logic is original
- **AI coding tools:** Built in collaboration with Claude for scaffolding, debugging, and architecture discussion; all design decisions and tradeoffs are my own and I can explain/modify every component

---

## Assumptions

- Mock environments stand in for real company systems — no real data/credentials used
- Success criteria are defined per task upfront, not inferred by the agent
- A flat policy document is sufficient company memory for this prototype's scope
- Blocking CLI-based human-in-the-loop is acceptable for a prototype
- Regex-based document extraction is acceptable since the mock document format is fully controlled

---

## What I'd Build Next

1. LLM-based field extraction to replace regex parsing (closes the main generalization gap)
2. Browser automation tool (Playwright), wired into the invoice form that already exists but isn't driven
3. Retrieval-based company memory (Chroma) instead of flat-text policy injection
4. Persistent episodic/failure memory so the agent improves at recurring failure types across runs
5. A third, structurally different task domain to further stress-test generalization
6. Non-blocking human-in-the-loop (async/webhook-based) instead of blocking CLI input

---

## Project Structure

```
core/
├── schemas.py            # Pydantic data contracts
├── llm_client.py          # Multi-provider LLM abstraction
├── planner.py              # Goal → draft plan
├── decision_engine.py      # Per-step decision-making
├── orchestrator.py          # Main control loop
├── error_classifier.py      # Rule-based failure classification
├── verifier.py                # Independent success verification
├── human_interface.py          # CLI human-in-the-loop
└── tools/                       # file_reader_tool.py, api_tool.py, base.py

mock_envs/
├── shared/chaos.py               # Fault-injection layer
├── internal_system_app/           # Mock invoice system
└── ticket_system_app/              # Mock ticket system

tasks/              # Task configs, policy docs, sample data
ui/                  # Streamlit log viewer
tests/                # Unit + integration tests
run_task.py            # CLI entry point
```