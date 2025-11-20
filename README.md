# CRM Arena Pro+ (A2A) — README

A lightweight, reproducible benchmark harness for CRM-style agents.\
**Green Agent** = orchestrator/evaluator/environment. **White Agent** = agent under test.\
Everything speaks a simple HTTP **A2A** protocol (JSON): `Observation → ActionProposal → Feedback → Decision`.

---

## What’s in this repo

```
crm_arena_pro/
├── green_agent/
│   ├── a2a_protocol.py      # A2A message schemas + validation helpers
│   ├── evaluator.py         # Metrics: ExactMatch, F1, MAPE (+ normalizers)
│   └── green_server.py      # FastAPI server (orchestrator + scoring)
├── ui/
│   └── a2a_viewer.py        # Minimal web UI (FastAPI) to drive/inspect runs
├── white_agent/
│   └── white_mock.py        # Mock White Agent (deterministic, no LLM)
├── .gitignore
├── README.md
└── requirements.txt
```

**Personas & metrics**

- **ServiceAgent** → queue routing (IDs) → **Exact Match**
- **Analyst** → policy text extraction → **F1**
- **Manager** → numeric series / trend → **MAPE**
- **All Agents** → **Confidentiality Awareness** (PII leakage check)

**Difficulty tiers**

- **easy**: decision in 1 turn
- **medium**: proposal → decision (1 continue)
- **hard**: proposal → decision (1 continue, tuned for demo)

---

## Protocol (A2A-0.1) in one minute

- **Green → White**: `observation` (task context, constraints, available tools)
- **White → Green**:
    - `action_proposal` (includes executed request **and** result from Green APIs), or
    - `decision` (final answers, plan, confidence)
- **Green → White**: `feedback` on proposals; **scores** on decision

All turns are stored in a **session transcript** for auditing.

---

## Prerequisites

- Python **3.9+** (tested on 3.10–3.13)
- `pip` (or venv/conda)
- macOS/Linux/Windows

---

## Install

```bash
# from repo root
python -m venv .venv
source .venv/bin/activate             # Windows: .venv\Scripts\activate
pip install fastapi uvicorn httpx pydantic
```

> No OpenAI key required — the White Agent is a deterministic mock.

---

## Environment Variables (optional)

```bash
# Where Green posts history (your White Agent URL)
export A2A_WHITE_URL=http://localhost:9100/a2a/step

# Where the UI points to the Green server
export GREEN_URL=http://localhost:9101

# Proposal validator allowlist (Green side)
export A2A_ALLOWED_DOMAINS=localhost,example.org
```

Defaults work out-of-the-box; set these only if you change ports/hosts.

---

## Start All Servers (3 terminals)

### A) White Agent (mock)

```bash
uvicorn white_agent.white_mock:app --port 9100 --reload
```

### B) Green Agent (orchestrator + evaluator)

```bash
uvicorn green_agent.green_server:app --port 9101 --reload
```

### C) A2A Viewer (simple UI)

```bash
uvicorn ui.a2a_viewer:app --port 9200 --reload
```

Open: [**http://localhost:9200**](http://localhost:9200)

1. Choose **Persona** (ServiceAgent / Analyst / Manager)
2. Choose **Difficulty** (easy / medium / hard)
3. Click **Start Session**
4. If `done:false`, click **Continue** once to finish hard/medium tasks
5. See **Validation**, **Scores**, and the **Transcript**

---

## Quick CLI Smoke Tests (no UI)

**Green card**

```bash
curl http://localhost:9101/a2a/card | jq .
```

**Start a ServiceAgent/hard session**

```bash
R1=$(curl -s -X POST "http://localhost:9101/a2a/start?persona=ServiceAgent&difficulty=hard")
echo "$R1" | jq .
SID=$(python - <<'PY'
import sys, json
d=json.load(sys.stdin); print(d.get("session_id") or (d.get("feedback") or {}).get("session_id",""))
PY
<<< "$R1")
```

**Continue once → expect decision + scores + **``

```bash
curl -s -X POST "http://localhost:9101/a2a/continue" -d "session_id=$SID" | jq .
```

**Fetch full transcript**

```bash
curl -s "http://localhost:9101/sessions/$SID" | jq .
```

---

## What the Green Agent Evaluates

- **Correctness**:
  - **Exact Match** for IDs (ServiceAgent)
  - **F1** for short text (Analyst)
  - **MAPE** for numeric arrays (Manager)
- **On-policy action use**: proposals must be GET/POST to allowlisted domains and reasonable size
- **Traceability**: proposals must include **white\_agent\_execution** (request + result)

---


## 📏 Metrics (details)

- **Exact Match (EM)**\
  Normalizes case/whitespace/punct before comparison.\
  Output: `{"ExactMatch": 0 or 1}`

- **F1 (token-level)**\
  Tokenizes into alphanum-lowercase; computes precision/recall/F1.\
  Output: `{"F1": 0..1}`

- **MAPE (Mean Absolute Percentage Error)**\
  Safe divide with zero-handling; compares numeric arrays parsed from answers.\
  Output: `{"MAPE": 0..∞}` (lower is better; 0 = perfect)
- **Confidentiality**\
  Keyword/Regex matching against known PII in the environment.
  Output: `{"is_safe": bool, "leaks_found": [...]}`

All implemented in `green_agent/evaluator.py`.

---

## 🔌 Endpoints (Green)

**Environment APIs (Simulated Salesforce)**

- `GET /salesforce/soql` → Execute structured SQL-like queries (e.g. `SELECT Id FROM Case`)
- `GET /salesforce/sosl` → Execute keyword search (e.g. `FIND {Billing}`)

**Orchestrator APIs**

- `GET /a2a/card` → Capability card (protocol, personas, tasks, metrics)
- `POST /a2a/start?persona=…&difficulty=…` → Starts a session; returns Feedback or Decision
- `POST /a2a/continue` (form/body: `session_id=<id>`) → Next turn
- `GET /sessions/{session_id}` → Full stored transcript

**White (mock)**

- `POST /a2a/step` (expects `{"history":[...]}`; replies with `action_proposal` or `decision`)

---
