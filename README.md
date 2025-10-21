# CRM Arena Pro+ (A2A) — README

A lightweight, reproducible benchmark harness for CRM-style agents.\
**Green Agent** = orchestrator/evaluator. **White Agent** = agent under test.\
Everything speaks a simple HTTP **A2A** protocol (JSON): `Observation → ActionProposal → Feedback → Decision`.

---

## ✨ What’s in this repo

```
crm_arena_pro/
├── green_agent/
│   ├── __init__.py
│   ├── a2a_protocol.py      # A2A message schemas + validation helpers
│   ├── evaluator.py         # Metrics: ExactMatch, F1, MAPE (+ normalizers)
│   └── green_server.py      # FastAPI server (orchestrator + scoring)
├── white_agent/
│   ├── __init__.py
│   └── white_mock.py        # Mock White Agent (deterministic, no LLM)
└── ui/
    └── a2a_viewer.py        # Minimal web UI (FastAPI) to drive/inspect runs
```

**Personas & metrics**

- **ServiceAgent** → queue routing (IDs) → **Exact Match**
- **Analyst** → policy text extraction → **F1**
- **Manager** → numeric series / trend → **MAPE**

**Difficulty tiers**

- **easy**: decision in 1 turn
- **medium**: proposal → decision (1 continue)
- **hard**: proposal → decision (1 continue, tuned for demo)

---

## 🧉 Protocol (A2A-0.1) in one minute

- **Green → White**: `observation` (task context, constraints)
- **White → Green**:
  - `action_proposal` (includes executed request **and** result), or
  - `decision` (final answers, plan, confidence)
- **Green → White**: `feedback` on proposals; **scores** on decision

All turns are stored in a **session transcript** for auditing.

---

## ✅ Prerequisites

- Python **3.9+** (tested on 3.10–3.13)
- `pip` (or venv/conda)
- macOS/Linux/Windows

---

## 📦 Install

```bash
# from repo root
python -m venv .venv
source .venv/bin/activate             # Windows: .venv\Scripts\activate
pip install fastapi uvicorn httpx pydantic
```

> No OpenAI key required — the White Agent is a deterministic mock.

---

## ⚙️ Environment Variables (optional)

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

## 🚀 Start All Servers (3 terminals)

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

## 🤪 Quick CLI Smoke Tests (no UI)

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

## 🧠 What the Green Agent Evaluates

- **Correctness**:
  - **Exact Match** for IDs (ServiceAgent)
  - **F1** for short text (Analyst)
  - **MAPE** for numeric arrays (Manager)
- **On-policy action use**: proposals must be GET/POST to allowlisted domains and reasonable size
- **Traceability**: proposals must include **white\_agent\_execution** (request + result)

---

## 🎨 Suggested 1-Minute Demo Flow

1. **ServiceAgent → medium**: proposal (queue lookup) → decision → **EM=1**
2. **Analyst → hard**: proposal (KB lookup) → decision → **F1** printed
3. **Manager → hard**: proposal (fetch series) → decision → **MAPE** (0 if perfect)

In the UI, show **Validation** (action\_valid: true), **Scores**, and **Transcript**.

---

## 🔧 Troubleshooting

**UI says “failed to fetch”**

- Start all three servers; confirm Green card:
  ```bash
  curl http://localhost:9101/a2a/card
  ```
- The viewer proxies `/api/start`, `/api/continue`, `/api/session/*` — no CORS needed.\
  If you edited ports, `export GREEN_URL=http://localhost:<your-port>` before starting the viewer.

**Hard tasks never finish**

- Ensure Green sends **full history** each turn (already in `green_server.py`).
- Ensure White hard cases are **proposal → decision** (one Continue).\
  The provided `white_mock.py` already does this.

**500 “Unexpected token 'I'… not valid JSON”**

- That’s the UI parsing an HTML 500 page.\
  Check Green logs; a common cause is a NameError in `/a2a/continue`.\
  The current file includes the fix (creates the `items` list and uses `_build_full_history_envelope`).

**Circular import / future import error**

- We removed `from __future__ import annotations` (unnecessary on 3.13) and fixed self-imports.\
  If you edited `a2a_protocol.py`, ensure it doesn’t import itself and restart without `--reload` once:
  ```bash
  uvicorn green_agent.green_server:app --port 9101
  ```

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

All implemented in ``.

---

## 🔌 Endpoints (Green)

- `GET /a2a/card` → Capability card (protocol, personas, tasks, metrics)
- `POST /a2a/start?persona=…&difficulty=…` → Starts a session; returns Feedback or Decision
- `POST /a2a/continue` (form/body: `session_id=<id>`) → Next turn
- `GET /sessions/{session_id}` → Full stored transcript

**White (mock)**

- `GET /a2a/card`
- `POST /a2a/step` (expects `{"history":[...]}`; replies with `action_proposal` or `decision`)

---

## 🧪 Validation & Reproducibility

- Deterministic mock endpoints remove network drift.
- Green stores the **complete** A2A transcript; you can audit every turn.
- Difficulty tiers enforce step count (easy=1, medium=2, hard=2 turns).

---

## 🦭 Mapping to the Grading Rubric

- **Analysis (9.1):** Docs note ambiguity, drift, traceability; fixed via normalization & full transcripts.
- **Faithfulness (9.2):** Same task families & metrics; results comparable to original.
- **Quality Assurance (9.3):** Personas × difficulties, edge cases, and complementary metrics.
- **Evaluator Quality (9.4):** Unified evaluator, deterministic, transparent logging.
- **Validation (9.5):** Manual transcript checks, metric recomputation, stress tests.
- **Reliability (9.6):** Offline mocks, allowlist validator, multi-seed reproducibility.
- **Bias/Contamination (9.7):** Allowlist + deterministic data reduce leakage; plan multilingual/holdout variants.
- **Impact (9.8):** Clear code layout, UI viewer, protocol docs, ready to extend.

---

## 🌱 Optional: Upgrading to a real LLM later

Right now everything is deterministic (great for class demo).\
To convert **White** to an LLM-backed agent:

- Replace rule branches in `white_mock.py` with `client.chat.completions.create(...)`
- Parse the model’s text into the A2A `action_proposal` or `decision` JSON
- Keep the Green side unchanged — it already evaluates any compliant White

---

## 📔 License / Attribution

Class project scaffold for agentic evaluation.\
Credit: CRM Arena Pro+ Green Agent (W. Chang).\
Based on an A2A-style orchestration inspired by AgentBeats patterns.

---

## 😟 Need help fast?

- Verify cards:
  ```bash
  curl http://localhost:9101/a2a/card
  curl http://localhost:9100/a2a/card
  ```
- Start a session and continue once; inspect transcript:
  ```bash
  # start
  curl -X POST "http://localhost:9101/a2a/start?persona=ServiceAgent&difficulty=hard"
  # continue
  curl -X POST "http://localhost:9101/a2a/continue" -d "session_id=<SID>"
  # transcript
  curl "http://localhost:9101/sessions/<SID>"
  ```

If anything still looks off, paste the JSON you got back (and any server stack trace) and which persona/difficulty you ran.

